// The graphics drawing service: the engine (Python) asks it to draw motion graphics to videos
// with transparency. It runs a tiny local web server (127.0.0.1 only, a random token per app
// start) that serves desktop/graphics/ and answers POST /draw with one JSON line per event,
// and draws in a hidden, transparent, offscreen Electron window: the same page and templates
// as the command-line renderer (graphics/capture.mjs, Playwright) and the preview.
//
// The engine finds it through AUTOEDIT_GRAPHICS_URL / AUTOEDIT_GRAPHICS_TOKEN (see engineEnv).
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import * as fs from "node:fs";
import * as http from "node:http";
import * as path from "node:path";

/** desktop/graphics, next to dist-electron/ in development and in the packaged app. */
export function graphicsDir(): string {
  return path.resolve(__dirname, "..", "..", "graphics");
}

const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css", ".json": "application/json",
  ".ttf": "font/ttf", ".otf": "font/otf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
};

export interface DrawJob {
  key: string;
  template: string;
  params: Record<string, unknown>;
  duration: number;
  fps: number;
  frames: number;
  quality?: string;
  out: string;
  meta: string;
}

/** What drawing needs from Electron (a fake in tests). */
export interface Capturer {
  /** Load the page; resolves when window.gfx is ready. */
  open(url: string): Promise<void>;
  /** Run JavaScript in the page and return its (JSON) result. */
  eval<T>(js: string): Promise<T>;
  /** A PNG of the page's top-left w x h pixels, with transparency, after the last change. */
  png(w: number, h: number): Promise<Buffer>;
  close(): void;
}

/** A Capturer on a hidden offscreen BrowserWindow (Electron only). */
export async function electronCapturer(): Promise<Capturer> {
  const { BrowserWindow } = await import("electron");
  const win = new BrowserWindow({
    show: false, width: 1400, height: 2300, frame: false, transparent: true, backgroundColor: "#00000000",
    webPreferences: { offscreen: true, backgroundThrottling: false, contextIsolation: true, sandbox: true },
  });
  win.webContents.setFrameRate(60);
  let last: Electron.NativeImage | null = null;
  let waiting: ((img: Electron.NativeImage) => void) | null = null;
  win.webContents.on("paint", (_e, _dirty, image) => {
    last = image;
    if (waiting) {
      const w = waiting;
      waiting = null;
      w(image);
    }
  });
  return {
    async open(url) {
      await win.loadURL(url);
      for (let i = 0; i < 200; i++) {
        if (await win.webContents.executeJavaScript("window.gfxReady === true")) return;
        await new Promise((r) => setTimeout(r, 50));
      }
      throw new Error("The graphics page did not start.");
    },
    eval: (js) => win.webContents.executeJavaScript(js),
    async png(w, h) {
      // ask for a fresh paint after the change and use it (offscreen windows paint on demand)
      const next = new Promise<Electron.NativeImage>((resolve) => {
        waiting = resolve;
        setTimeout(() => {
          if (waiting === resolve && last) {
            waiting = null;
            resolve(last);
          }
        }, 500);
      });
      win.webContents.invalidate();
      const image = await next;
      return image.crop({ x: 0, y: 0, width: w, height: h }).toPNG();
    },
    close: () => win.destroy(),
  };
}

function ffmpegSink(ffmpeg: string, out: string, fps: number) {
  const part = `${out}.part.mkv`;
  const proc = spawn(ffmpeg, ["-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "png", "-i", "-",
    "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra", part], { stdio: ["pipe", "ignore", "pipe"], windowsHide: true });
  let err = "";
  proc.stderr?.on("data", (d) => (err += String(d)));
  proc.stdin?.on("error", () => undefined);
  const done = new Promise<void>((resolve, reject) => {
    proc.on("error", reject);
    proc.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`FFmpeg failed (${code}): ${err.slice(-300)}`))));
  });
  return {
    write: (buf: Buffer) => new Promise<void>((resolve) => (proc.stdin!.write(buf) ? resolve() : proc.stdin!.once("drain", () => resolve()))),
    async finish() {
      proc.stdin!.end();
      await done;
      fs.renameSync(part, out);
    },
    abort() {
      try {
        proc.kill();
      } catch {
        /* gone */
      }
    },
  };
}

/** Draw jobs with a capturer; `say` gets progress lines. Pictures on this PC are served by `serveFile`. */
export async function drawJobs(
  jobs: DrawJob[], capturer: Capturer, pageUrl: string, ffmpeg: string, say: (e: Record<string, unknown>) => void,
  serveFile: (file: string) => string, aborted: () => boolean,
): Promise<void> {
  const total = jobs.reduce((n, j) => n + j.frames, 0);
  let done = 0;
  await capturer.open(pageUrl);
  for (const job of jobs) {
    if (aborted()) throw new Error("cancelled");
    const params = { ...job.params };
    if (typeof params.image === "string" && !/^(https?:|data:)/i.test(params.image)) params.image = serveFile(params.image);
    const info = await capturer.eval<{ w: number; h: number; pad: number; tileW: number; tileH: number; report: unknown }>(
      `window.gfx.prepare(${JSON.stringify({ id: job.template, params, duration: job.duration, quality: job.quality ?? "final" })})`,
    );
    fs.mkdirSync(path.dirname(job.out), { recursive: true });
    const sink = ffmpegSink(ffmpeg, job.out, job.fps);
    try {
      for (let i = 0; i < job.frames; i++) {
        if (aborted()) throw new Error("cancelled");
        await capturer.eval(`window.gfx.seek(${i / job.fps})`);
        await sink.write(await capturer.png(info.tileW, info.tileH));
        done++;
        if (i % 5 === 0) say({ type: "progress", done, total });
      }
      await sink.finish();
    } catch (e) {
      sink.abort();
      throw e;
    }
    const meta = { w: info.w, h: info.h, pad: info.pad, tileW: info.tileW, tileH: info.tileH, report: info.report, fps: job.fps, frames: job.frames, renderer: await capturer.eval("window.gfx.version") };
    fs.writeFileSync(job.meta, JSON.stringify(meta));
    say({ type: "job", key: job.key });
  }
}

export interface GraphicsService {
  url: string;
  token: string;
  close(): Promise<void>;
}

/** Start the service. `makeCapturer` defaults to the hidden Electron window. */
export function startGraphicsService(makeCapturer: () => Promise<Capturer> = electronCapturer, root = graphicsDir()): Promise<GraphicsService> {
  const token = randomBytes(16).toString("hex");
  const served = new Map<string, string>();
  let chain: Promise<void> = Promise.resolve(); // one drawing at a time
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://x");
    if (req.method === "POST" && url.pathname === "/draw") {
      if (req.headers["x-graphics-token"] !== token) {
        res.writeHead(403);
        res.end("forbidden");
        return;
      }
      let body = "";
      req.on("data", (d) => (body += String(d)));
      req.on("end", () => {
        let spec: { jobs: DrawJob[]; ffmpeg?: string };
        try {
          spec = JSON.parse(body);
        } catch {
          res.writeHead(400);
          res.end("bad request");
          return;
        }
        res.writeHead(200, { "content-type": "application/x-ndjson" });
        let closed = false;
        res.on("close", () => (closed = true)); // the engine cancelled
        const say = (e: Record<string, unknown>) => {
          if (!closed) res.write(JSON.stringify(e) + "\n");
        };
        chain = chain.then(async () => {
          let capturer: Capturer | null = null;
          try {
            capturer = await makeCapturer();
            const base = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
            await drawJobs(spec.jobs, capturer, `${base}/page.html`, spec.ffmpeg || "ffmpeg", say, (file) => {
              const name = `/img-${served.size}${path.extname(file).toLowerCase()}`;
              served.set(name, file);
              return `${base}${name}`;
            }, () => closed);
            say({ type: "done" });
          } catch (e) {
            say({ type: "error", message: (e as Error).message });
          } finally {
            capturer?.close();
            res.end();
          }
        });
      });
      return;
    }
    if (req.method !== "GET") {
      res.writeHead(405);
      res.end();
      return;
    }
    const extra = served.get(url.pathname);
    const file = extra ?? path.normalize(path.join(root, decodeURIComponent(url.pathname)));
    if (!extra && !file.startsWith(path.resolve(root))) {
      res.writeHead(404);
      res.end();
      return;
    }
    fs.stat(file, (err, st) => {
      if (err || !st.isFile()) {
        res.writeHead(404);
        res.end();
        return;
      }
      res.writeHead(200, { "content-type": TYPES[path.extname(file).toLowerCase()] ?? "application/octet-stream", "cache-control": "no-store" });
      fs.createReadStream(file).pipe(res);
    });
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () =>
      resolve({
        url: `http://127.0.0.1:${(server.address() as { port: number }).port}`,
        token,
        close: () => new Promise((done) => server.close(() => done())),
      }),
    ),
  );
}
