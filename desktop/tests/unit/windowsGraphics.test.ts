// The Windows graphics bug: the app's hidden drawing window gave empty pictures, FFmpeg got no
// frame and failed ("Output file does not contain any stream", exit 4294967274 = -22). Frames are
// now cropped for display scaling, an empty picture is a clear error for that one graphic, and
// finished files are moved into place with retries while Windows keeps them busy.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { drawJobs, exitText, frameToPng, replaceFile, type Capturer, type FrameImage } from "../../src/main/graphics";
import { applyEvent, newJob } from "../../src/shared/jobs";

/** A fake painted picture: its size, and what was cropped / resized from it. */
function picture(width: number, height: number, log: string[] = []): FrameImage {
  return {
    isEmpty: () => width === 0 || height === 0,
    getSize: () => ({ width, height }),
    crop: (r) => (log.push(`crop ${r.width}x${r.height}`), picture(r.width, r.height, log)),
    resize: (s) => (log.push(`resize ${s.width}x${s.height}`), picture(s.width, s.height, log)),
    toPNG: () => Buffer.alloc(width && height ? 8 : 0, 1),
  };
}

describe("frames from the drawing window", () => {
  it("at 100% the picture is cropped as is", () => {
    const log: string[] = [];
    expect(frameToPng(picture(1400, 2300, log), 600, 300).length).toBe(8);
    expect(log).toEqual(["crop 600x300"]);
  });
  it("at 125% / 150% display scaling the crop is scaled and the frame resized back", () => {
    const log: string[] = [];
    frameToPng(picture(1750, 2875, log), 600, 300);
    expect(log).toEqual(["crop 750x375", "resize 600x300"]);
    const log2: string[] = [];
    frameToPng(picture(2100, 3450, log2), 600, 300);
    expect(log2).toEqual(["crop 900x450", "resize 600x300"]);
  });
  it("an empty picture is an error, never an empty frame", () => {
    expect(() => frameToPng(picture(0, 0), 600, 300)).toThrow("the drawing window gave an empty picture for a 600x300 graphic");
  });
  it("a window that Windows made shorter than the graphic is an error that says so", () => {
    expect(() => frameToPng(picture(1400, 1040), 760, 1100)).toThrow("the drawing window is 1400x1040 pixels, too small for a 760x1100 graphic");
  });
});

describe("FFmpeg exit codes", () => {
  it("Windows' 4294967274 reads as -22: invalid argument", () => {
    expect(exitText(4294967274)).toBe("exit code -22: invalid argument");
    expect(exitText(1)).toBe("exit code 1");
    expect(exitText(null)).toBe("it was stopped");
  });
});

describe("one graphic that cannot be drawn", () => {
  it("is reported (key and reason) and the others are still drawn", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "draw-"));
    let frame = 0;
    const capturer: Capturer = {
      open: async () => undefined,
      eval: async <T,>(js: string) => (js.startsWith("window.gfx.prepare") ? ({ w: 10, h: 10, pad: 0, tileW: 10, tileH: 10, report: {} } as T) : (undefined as T)),
      png: async () => {
        frame++;
        if (frame === 1) throw new Error("the drawing window gave an empty picture for a 10x10 graphic");
        return Buffer.alloc(0); // a picture that came back empty

      },
      close: () => undefined,
    };
    const said: Record<string, unknown>[] = [];
    const job = (key: string) => ({ key, template: "stamp", params: {}, duration: 0.1, fps: 10, frames: 1, out: path.join(dir, `${key}.mkv`), meta: path.join(dir, `${key}.json`) });
    await drawJobs([job("a"), job("b")], capturer, "http://x", "ffmpeg", (e) => said.push(e), (f) => f, () => false);
    const errors = said.filter((e) => e.type === "job_error");
    expect(errors.map((e) => e.key)).toEqual(["a", "b"]);
    expect(String(errors[0].message)).toContain("empty picture");
    expect(String(errors[1].message)).toContain(`an empty frame for ${path.join(dir, "b.mkv")}`);
  });

  it("shows up as a warning with the job, the edit goes on", () => {
    const job = newJob("j1", { video: "v", photos: [], instruction: "", provider: "groq", auto: true, mode: "new" });
    const next = applyEvent(job, { type: "warning", message: "Graphic g2 (stamp) was left out: C:\\cache\\a.mkv: exit code -22" });
    expect(next.warnings).toEqual(["Graphic g2 (stamp) was left out: C:\\cache\\a.mkv: exit code -22"]);
    expect(next.log.at(-1)).toContain("WARNING");
  });
});

describe("files on Windows", () => {
  it("waits for a busy file and then replaces it", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "rep-"));
    const part = path.join(dir, "a.part.mkv");
    const out = path.join(dir, "a.mkv");
    fs.writeFileSync(part, "new");
    fs.writeFileSync(out, "old");
    let calls = 0;
    const busyTwice = (a: fs.PathLike, b: fs.PathLike) => {
      calls++;
      if (calls <= 2) throw Object.assign(new Error("operation not permitted"), { code: "EPERM" });
      fs.renameSync(a, b);
    };
    await replaceFile(part, out, 20, busyTwice);
    expect(calls).toBe(3);
    expect(fs.readFileSync(out, "utf-8")).toBe("new");
  });
  it("names the file when it cannot be written", async () => {
    const never = () => {
      throw Object.assign(new Error("no space"), { code: "ENOSPC" });
    };
    await expect(replaceFile("x.part", "C:\\cache\\x.mkv", 3, never)).rejects.toThrow("could not write C:\\cache\\x.mkv: ENOSPC");
  });
});
