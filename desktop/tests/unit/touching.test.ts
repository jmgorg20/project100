// Clips that touch (the end of one is the start of the next, give or take rounding) are not
// "overlapping": the same tolerance as the engine's validator (TIME_TOLERANCE, 0.002 s).
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { TOUCH, moveClip, resolveOverlaps, trimClip } from "../../src/shared/edit";
import type { Project } from "../../src/shared/types";
import { sample } from "./edit.test";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const engineProblems = (p: Project): string[] =>
  JSON.parse(execFileSync(python, ["-c", "import json,sys; from autoedit.project import validate_project; print(json.dumps(validate_project(json.load(sys.stdin))))"], { cwd: repo, input: JSON.stringify(p), encoding: "utf-8" }));

describe("touching clips", () => {
  it("uses the engine's tolerance", () => {
    const src = execFileSync(python, ["-c", "from autoedit.project import TIME_TOLERANCE; print(TIME_TOLERANCE)"], { cwd: repo, encoding: "utf-8" });
    expect(TOUCH).toBe(Number(src));
  });

  it("keeps clips a tenth of a millisecond apart on one track (no spurious extra track)", () => {
    const p = sample();
    const caps = p.tracks.find((t) => t.id === "captions")!;
    caps.clips = [
      { id: "t1", type: "caption", start: 0, duration: 1.2, style: "classic", words: [{ text: "a", start: 0, end: 0.5 }] },
      { id: "t2", type: "caption", start: 1.1999, duration: 1, style: "classic", words: [{ text: "b", start: 0, end: 0.5 }] }, // 0.1 ms early
      { id: "t3", type: "caption", start: 2.2, duration: 1, style: "classic", words: [{ text: "c", start: 0, end: 0.5 }] },
    ];
    const q = resolveOverlaps(p);
    expect(q.tracks.filter((t) => t.kind === "caption")).toHaveLength(1);
    expect(engineProblems(q)).toEqual([]);
    // A real overlap (one frame at 30 fps) still goes to another track.
    caps.clips[1].start = 1.2 - 1 / 30;
    expect(resolveOverlaps(p).tracks.filter((t) => t.kind === "caption")).toHaveLength(2);
  });

  it("moves and trims clips next to a touching neighbour without extra tracks or errors", () => {
    const p = sample();
    const photos = p.tracks.find((t) => t.id === "photos")!;
    photos.clips.push({ id: "o2", type: "image", media: "m2", start: 3.5002, duration: 1, x: 540, y: 960, width: 600, height: 400 }); // 0.2 ms after o1's end
    expect(engineProblems(resolveOverlaps(p))).toEqual([]);
    expect(resolveOverlaps(p).tracks.filter((t) => t.kind === "overlay")).toHaveLength(1);
    const moved = moveClip(p, "o2", 3.5, "photos");
    expect(moved.project.tracks.filter((t) => t.kind === "overlay")).toHaveLength(1);
    expect(trimClip(p, "o2", "start", 3.4).tracks.find((t) => t.id === "photos")!.clips.find((c) => c.id === "o2")!.start).toBeGreaterThanOrEqual(3.5);
  });
});
