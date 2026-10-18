// Resumable upload: the file goes in pieces; after a lost connection, a closed tab or a reload the
// same file (picked again) continues where it stopped, because the service says how much arrived.

import { ApiError, call, get, post, type UploadView } from "./api";

const KEY = "autoedit.uploads";
const RETRIES = 6;

type Saved = Record<string, { id: string; at: number }>;

function fingerprint(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function load(): Saved {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Saved;
    const day = Date.now() - 86_400_000;
    return Object.fromEntries(Object.entries(saved).filter(([, v]) => v.at > day));
  } catch {
    return {};
  }
}

function remember(file: File, id: string | null) {
  const saved = load();
  if (id) saved[fingerprint(file)] = { id, at: Date.now() };
  else delete saved[fingerprint(file)];
  try {
    localStorage.setItem(KEY, JSON.stringify(saved));
  } catch {
    // private mode: resuming after a reload is not possible, uploading still is
  }
}

export interface UploadOptions {
  projectId?: string | null;
  onProgress?: (sent: number, total: number) => void;
  signal?: AbortSignal;
}

const wait = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Paused", "AbortError"));
    }, { once: true });
  });

async function start(file: File, projectId?: string | null): Promise<UploadView> {
  const known = load()[fingerprint(file)];
  if (known) {
    try {
      const up = await get<UploadView>(`/v1/uploads/${known.id}`);
      if (up.status === "uploading" || up.status === "ready") return up;
    } catch {
      // expired or deleted: start again
    }
  }
  const up = await post<UploadView>("/v1/uploads", { filename: file.name, size: file.size, project_id: projectId ?? undefined });
  remember(file, up.id);
  return up;
}

/** Upload `file`; resolves with the checked upload (ready), or throws ApiError (e.g. 422 rejected). */
export async function uploadFile(file: File, opts: UploadOptions = {}): Promise<UploadView> {
  let up = await start(file, opts.projectId);
  let offset = up.received;
  opts.onProgress?.(offset, file.size);
  let failures = 0;
  while (up.status === "uploading" && offset < file.size) {
    if (opts.signal?.aborted) throw new DOMException("Paused", "AbortError");
    const piece = file.slice(offset, Math.min(file.size, offset + up.chunk_size));
    try {
      const r = await call<{ received: number }>("PUT", `/v1/uploads/${up.id}/chunk?offset=${offset}`, piece,
        { signal: opts.signal });
      offset = r.received;
      failures = 0;
      opts.onProgress?.(offset, file.size);
    } catch (err) {
      if ((err as Error).name === "AbortError") throw err;
      const e = err as ApiError;
      if (e.status && e.status < 500 && e.status !== 409 && e.status !== 429) throw e;
      if (++failures > RETRIES) throw e;
      await wait(e.retryAfter ? e.retryAfter * 1000 : Math.min(30_000, 1000 * 2 ** failures), opts.signal);
      // where are we? (the piece may have arrived even if the answer was lost)
      up = await get<UploadView>(`/v1/uploads/${up.id}`);
      offset = up.received;
      opts.onProgress?.(offset, file.size);
    }
  }
  if (up.status === "ready") return up;
  try {
    const done = await post<UploadView>(`/v1/uploads/${up.id}/complete`);
    remember(file, null);
    return done;
  } catch (err) {
    if ((err as ApiError).status === 422) remember(file, null);     // rejected: picking it again starts over
    throw err;
  }
}
