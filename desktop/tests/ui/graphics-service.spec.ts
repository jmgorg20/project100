// The app's graphics service (src/main/graphics.ts) end to end: the real engine asks it to draw
// over HTTP, it draws page by page and pipes the frames to FFmpeg. Electron's hidden window
// cannot run here, so a Playwright Chromium page stands in for it (the same Capturer interface).
import { expect, test, type Browser } from "@playwright/test";
import { execFile, execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { promisify } from "node:util";
import { startGraphicsService, type Capturer } from "../../src/main/graphics";

const repo = path.resolve(__dirname, "..", "..", "..");
const python = process.platform === "win32" ? "python" : "python3";

function capturerOn(browser: Browser, opened: { n: number }) {
  return async (): Promise<Capturer> => {
    const page = await (await browser.newContext({ viewport: { width: 1400, height: 2300 } })).newPage();
    opened.n++;
    return {
      async open(url) {
        await page.goto(url);
        await page.waitForFunction("window.gfxReady === true");
      },
      eval: (js) => page.evaluate(js),
      png: (w, h) => page.screenshot({ type: "png", omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } }),
      close: () => void page.context().close(),
    };
  };
}

test("the graphics service draws a project's graphics for the engine", async ({ browser }) => {
  test.setTimeout(120_000);
  const opened = { n: 0 };
  const service = await startGraphicsService(capturerOn(browser, opened));
  try {
    // only with the token, and only its own folder
    expect((await fetch(`${service.url}/draw`, { method: "POST", body: "{}" })).status).toBe(403);
    expect((await fetch(`${service.url}/page.html`)).status).toBe(200);
    expect((await fetch(`${service.url}/..%2F..%2Fpackage.json`)).status).toBe(404);

    const cache = fs.mkdtempSync(path.join(os.tmpdir(), "gfx-service-"));
    const script = `
import json
from autoedit import graphics
from autoedit.project import new_project
p = new_project("s")
p["media"] = [{"id": "m1", "kind": "video", "path": "x.mp4", "duration": 3, "width": 1080, "height": 1920}]
p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": 3, "in": 0, "out": 3}]
p["tracks"].append({"id": "graphics", "kind": "graphics", "clips": [
  {"id": "g1", "type": "graphic", "template": "stamp", "start": 0, "duration": 0.5, "x": 0.5, "y": 0.5, "params": {"text": "Served"}}]})
left = graphics.ensure_assets(p, ".")
jobs = graphics.project_jobs(p, ".")
print(json.dumps({"left": left, "drawn": [graphics.is_drawn(j) for j in jobs], "meta": graphics.read_meta(jobs[0])}))
`;
    // asynchronously: the service runs in this same process
    const { stdout } = await promisify(execFile)(python, ["-c", script], {
      cwd: repo,
      env: { ...process.env, AUTOEDIT_GRAPHICS_URL: service.url, AUTOEDIT_GRAPHICS_TOKEN: service.token, AUTOEDIT_GRAPHICS_CACHE: cache },
    });
    const r = JSON.parse(stdout.trim().split("\n").pop()!);
    expect(r.left).toEqual([]);
    expect(r.drawn).toEqual([true]);
    expect(r.meta.frames).toBe(15);
    expect(r.meta.tileW).toBe(r.meta.w + 2 * r.meta.pad);
    expect(opened.n).toBe(1);
    const video = fs.readdirSync(cache).map((f) => path.join(cache, f)).find((f) => f.endsWith(".mkv"))!;
    const probe = JSON.parse(execFileSync("ffprobe", ["-v", "error", "-count_frames", "-show_entries", "stream=pix_fmt,nb_read_frames,codec_name", "-of", "json", video], { encoding: "utf-8" }));
    expect(probe.streams[0]).toMatchObject({ codec_name: "ffv1", pix_fmt: "bgra", nb_read_frames: "15" });
  } finally {
    await service.close();
  }
});
