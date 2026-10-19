// Draw graphics to frames with a headless Chromium (Playwright) and pack them into videos with
// alpha for FFmpeg. The Electron app does the same with an offscreen window (src/main/graphics.ts);
// both load the same page.html over a tiny local web server and write the same files.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { createReadStream, existsSync, mkdirSync, renameSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const HERE = dirname(fileURLToPath(import.meta.url));
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css", ".json": "application/json", ".ttf": "font/ttf", ".otf": "font/otf", ".png": "image/png" };

/** Serve this folder (read-only) on 127.0.0.1. Resolves { url, close(), serveFile(name, path) }. */
export function startStaticServer(root = HERE) {
  const extra = new Map();
  const server = createServer((req, res) => {
    try {
      const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
      if (extra.has(path)) { res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); createReadStream(extra.get(path)).pipe(res); return; }
      const file = normalize(join(root, path === "/" ? "page.html" : path));
      if (!file.startsWith(resolve(root)) || !existsSync(file) || !statSync(file).isFile()) { res.writeHead(404); res.end("not found"); return; }
      res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream", "cache-control": "no-store" });
      createReadStream(file).pipe(res);
    } catch { res.writeHead(500); res.end("error"); }
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok({
    url: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((done) => server.close(() => done())),
    serveFile: (name, path) => { extra.set(`/${name}`, path); return `http://127.0.0.1:${server.address().port}/${name}`; },
  })));
}

/** An FFmpeg process that takes PNG frames on stdin and writes an FFV1 (lossless, alpha) video. */
export function openSink(ffmpeg, out, fps) {
  const part = `${out}.part.mkv`;
  const args = ["-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "png", "-i", "-", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgra", part];
  const proc = spawn(ffmpeg, args, { stdio: ["pipe", "ignore", "pipe"] });
  let err = "";
  proc.stderr.on("data", (d) => { err += d; });
  const done = new Promise((ok, fail) => {
    proc.on("error", fail);
    proc.on("close", (code) => (code === 0 ? ok() : fail(new Error(`ffmpeg failed (${code}): ${err.slice(-400)}`))));
    proc.stdin.on("error", () => {});
  });
  return {
    write: (buf) => new Promise((ok) => { if (proc.stdin.write(buf)) ok(); else proc.stdin.once("drain", ok); }),
    async finish() { proc.stdin.end(); await done; renameSync(part, out); },
    abort() { try { proc.stdin.destroy(); proc.kill(); } catch { /* already gone */ } },
  };
}

/** Launch a Chromium: the one Playwright installed, else the Edge or Chrome on this PC. */
export async function launchBrowser(chromium) {
  const tries = [{}, { channel: "msedge" }, { channel: "chrome" }];
  let last;
  for (const t of tries) {
    try { return await chromium.launch({ headless: true, ...t }); } catch (e) { last = e; }
  }
  throw new Error(`No browser to draw the graphics with (${String(last && last.message).split("\n")[0]}). Install Microsoft Edge or run: npx playwright install chromium`);
}

/**
 * Render jobs. A job: { template, params, duration, fps, frames, quality, out, meta, stills }.
 *  - out: video path (frames 0..frames-1 at fps) - skipped when frames is 0
 *  - meta: sidecar json path with { w, h, pad, tileW, tileH, report, fps, frames, renderer }
 *  - stills: [{ t, out }] PNG files of single times (tests, previews)
 * onProgress({ done, total, job }); `signal` (AbortSignal) cancels between frames.
 */
export async function renderJobs(jobs, { ffmpeg = process.env.AUTOEDIT_FFMPEG || "ffmpeg", onProgress, signal, chromium } = {}) {
  if (!chromium) ({ chromium } = await import("playwright-core"));
  const server = await startStaticServer();
  const browser = await launchBrowser(chromium);
  const total = jobs.reduce((n, j) => n + (j.frames || 0) + (j.stills ? j.stills.length : 0), 0);
  let done = 0;
  let imageCount = 0;
  const results = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1400, height: 2300 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    page.on("pageerror", (e) => { throw e; });
    await page.goto(`${server.url}/page.html`);
    await page.waitForFunction("window.gfxReady === true", null, { timeout: 15000 });
    for (const job of jobs) {
      if (signal && signal.aborted) throw new Error("cancelled");
      // a picture on this PC is served by the local server (a page from http:// cannot open file://)
      const params = { ...(job.params || {}) };
      const serve = (file) => (/^(https?:|data:)/i.test(file) ? file : server.serveFile(`img-${imageCount++}${extname(file).toLowerCase()}`, file));
      if (params.image) params.image = serve(params.image);
      if (Array.isArray(params.images)) params.images = params.images.map(serve);
      const info = await page.evaluate((j) => window.gfx.prepare({ id: j.template, params: j.params, duration: j.duration, quality: j.quality }), { ...job, params });
      const clip = { x: 0, y: 0, width: info.tileW, height: info.tileH };
      const shot = async (t) => { await page.evaluate((x) => window.gfx.seek(x), t); return page.screenshot({ type: "png", omitBackground: true, clip }); };
      if (job.frames > 0 && job.out) {
        mkdirSync(dirname(job.out), { recursive: true });
        const sink = openSink(ffmpeg, job.out, job.fps);
        try {
          for (let i = 0; i < job.frames; i++) {
            if (signal && signal.aborted) throw new Error("cancelled");
            await sink.write(await shot(i / job.fps));
            done++;
            if (onProgress && (i % 5 === 0 || i === job.frames - 1)) onProgress({ done, total, job });
          }
          await sink.finish();
        } catch (e) { sink.abort(); throw e; }
      }
      for (const s of job.stills || []) {
        mkdirSync(dirname(s.out), { recursive: true });
        writeFileSync(s.out, await shot(s.t));
        done++;
      }
      const meta = { w: info.w, h: info.h, pad: info.pad, tileW: info.tileW, tileH: info.tileH, report: info.report, fps: job.fps || 0, frames: job.frames || 0, renderer: await page.evaluate(() => window.gfx.version) };
      if (job.meta) { mkdirSync(dirname(job.meta), { recursive: true }); writeFileSync(job.meta, JSON.stringify(meta)); }
      results.push({ ...meta, job });
      if (onProgress) onProgress({ done, total, job, finished: true });
    }
  } finally {
    await browser.close();
    await server.close();
  }
  return results;
}
