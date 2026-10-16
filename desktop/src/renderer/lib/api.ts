// The bridge to the main process, or (with ?mock=1, for UI tests in a plain browser) a
// stand-in that replays a real engine run from fixture files.
import type { AppApi } from "../../shared/api";
import { fileUrl } from "../../shared/fileUrl";
import { createMockApi } from "./mockApi";

const useMock = typeof window !== "undefined" && (new URLSearchParams(window.location.search).has("mock") || !window.api);

export const api: AppApi = useMock ? createMockApi() : window.api;

/** URL the <video>/<img> elements use for a file on disk. */
export const mediaUrl = (path: string): string =>
  useMock
    ? // UI tests run in open-source Chromium, which has no H.264: the fixtures include WebM copies.
      `/fixtures/${encodeURIComponent((path.split(/[\\/]/).pop() ?? "").replace(/\.mp4$/i, ".webm"))}`
    : fileUrl(path);

export const isMock = useMock;
