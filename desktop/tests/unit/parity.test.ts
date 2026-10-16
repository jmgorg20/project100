// The preview's reframe (crop) maths against frames rendered by the real engine.
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { clipGain, clipSourceTime, cropBox } from "../../src/renderer/lib/timeline";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");

const CASES = [
  { w: 720, h: 1280, crop: undefined },
  { w: 720, h: 1280, crop: { zoom: 1.6, x: 0.3, y: 0.7 } },
  { w: 1920, h: 1080, crop: undefined },
  { w: 1920, h: 1080, crop: { zoom: 1, x: 0.6, y: 0.5 } },
  { w: 1920, h: 1080, crop: { zoom: 2.5, x: 0.55, y: 0.2 } },
];

describe("preview reframe matches the engine", () => {
  it("puts the edge between the two halves of the source where the engine does", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "parity-"));
    const out = execFileSync(python, ["-c", `
import json, subprocess, sys
from pathlib import Path
from autoedit.project import new_project, media_from_file
from autoedit.project_render import render_frame
d = Path(sys.argv[1]); cases = json.loads(sys.argv[2]); found = []
for i, c in enumerate(cases):
    w, h = c["w"], c["h"]
    src = d / f"halves{w}x{h}.mp4"
    if not src.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex",
            f"color=c=red:s={w}x{h}:r=30:d=1[l];color=c=blue:s={w//2}x{h}:r=30:d=1[r];[l][r]overlay=x={w//2}:y=0[v]",
            "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p", str(src)], check=True)
    p = new_project("parity")
    p["media"] = [media_from_file(src, "m")]
    clip = {"id": "c", "type": "video", "media": "m", "start": 0, "duration": 1, "in": 0, "out": 1}
    if c.get("crop"):
        clip["crop"] = c["crop"]
    p["tracks"][0]["clips"] = [clip]
    png = render_frame(p, 0.5, d / f"f{i}.png", work_dir=d / f"w{i}")
    row = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", "crop=1080:1:0:960",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    edge = next((x for x in range(1080) if row[3 * x + 2] > row[3 * x]), None)
    found.append(edge)
print(json.dumps(found))`, dir, JSON.stringify(CASES)], { cwd: repo, encoding: "utf-8" });
    const engineEdges: (number | null)[] = JSON.parse(out.trim().split("\n").pop()!);
    CASES.forEach((c, i) => {
      const box = cropBox(c.w, c.h, c.crop);
      const previewEdge = box.left + box.width / 2;
      const expected = previewEdge <= 0 ? 0 : previewEdge >= 1080 ? null : previewEdge;
      if (expected === null) expect(engineEdges[i]).toBeNull();
      else expect(Math.abs((engineEdges[i] ?? 0) - expected), `case ${i}`).toBeLessThanOrEqual(2);
    });
  }, 120_000);
});

describe("speed and fades", () => {
  it("maps timeline time to source time with the clip's speed", () => {
    const clip = { id: "c", type: "video" as const, start: 2, duration: 1, in: 5, out: 7, speed: 2 };
    expect(clipSourceTime(clip, 2)).toBe(5);
    expect(clipSourceTime(clip, 2.5)).toBe(6);
  });

  it("fades the sound in and out linearly, like FFmpeg's afade", () => {
    const clip = { id: "a", type: "audio" as const, start: 1, duration: 4, volume: 0.5, fade_in: 1, fade_out: 2 };
    expect(clipGain(clip, 1)).toBe(0);
    expect(clipGain(clip, 1.5)).toBeCloseTo(0.25);
    expect(clipGain(clip, 2.5)).toBeCloseTo(0.5);
    expect(clipGain(clip, 4)).toBeCloseTo(0.25);
  });
});
