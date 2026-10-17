// Tracked effects as timeline clips: adding, settings, what has nothing to follow; every
// result is checked by the engine's validator. The preview's mapping from a tracked point to the
// picture gives what the engine's does.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { EditError, findClip, setClipProps, splitClip, trimClip, moveClip, deleteClips } from "../../src/shared/edit";
import { TRACK_FX, addTrackFx, trackState, trackfxLabel, untrackedEffects } from "../../src/shared/trackEdit";
import type { Project, TrackData } from "../../src/shared/types";
import { followedNames, toCanvas, trackfxAt, trackfxPaths } from "../../src/renderer/lib/trackfxPreview";
import { sample } from "./edit.test";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const problems = (p: Project): string[] =>
  JSON.parse(execFileSync(python, ["-c", "import json,sys; from autoedit.project import validate_project; print(json.dumps(validate_project(json.load(sys.stdin))))"], { cwd: repo, input: JSON.stringify(p), encoding: "utf-8" }));

const track = (n = 300, c = 0.9): TrackData => ({
  fps: 30,
  start: 0,
  points: {
    right_index_tip: { x: Array.from({ length: n }, (_, i) => 0.2 + (0.5 * i) / n), y: new Array(n).fill(0.5), c: new Array(n).fill(c) },
    face: { x: new Array(n).fill(0.5), y: new Array(n).fill(0.3), c: new Array(n).fill(0.9), s: new Array(n).fill(0.3) },
  },
});

const tracked = (): Project => ({ ...sample(), tracking: { m1: track() } });

describe("adding tracked effects", () => {
  it("places each kind on an effect track and the engine accepts it", () => {
    let p = tracked();
    for (const effect of ["glow", "spark", "aura", "energy"] as const) {
      const r = addTrackFx(p, effect, 0.5);
      p = r.project;
      const clip = findClip(p, r.clipId)!.clip;
      expect(clip).toMatchObject({ type: "trackfx", effect, point: TRACK_FX[effect].point, hand: "any", start: 0.5, duration: Math.min(TRACK_FX[effect].seconds, 3.5 - 0.5) });
      expect(findClip(p, r.clipId)!.track.kind).toBe("effect");
    }
    expect(problems(p)).toEqual([]);
    expect(p.tracks.filter((t) => t.kind === "effect").length).toBeGreaterThan(1); // overlapping ones got their own tracks
  });

  it("your own clip needs a video or picture, and is a valid clip", () => {
    expect(() => addTrackFx(sample(), "clip", 0)).toThrow(EditError);
    expect(() => addTrackFx(sample(), "clip", 0, { media: "m3" })).toThrow(/video or picture/); // m3 is sound
    const r = addTrackFx(sample(), "clip", 1, { media: "m2" });
    expect(findClip(r.project, r.clipId)!.clip).toMatchObject({ effect: "clip", media: "m2", blend: "screen" });
    expect(problems(r.project)).toEqual([]);
  });

  it("changing settings stays inside the allowed ranges and in the engine's format", () => {
    const { project, clipId } = addTrackFx(tracked(), "glow", 0.2);
    let p = setClipProps(project, clipId, { size: 9, smooth: -1, intensity: 5, color: "#FF00AA", hand: "left", point: "palm", fade_in: 0.3, fade_out: 0.4 });
    expect(findClip(p, clipId)!.clip).toMatchObject({ size: 4, smooth: 0, intensity: 1, color: "#ff00aa", hand: "left", point: "palm", fade_in: 0.3, fade_out: 0.4 });
    p = setClipProps(p, clipId, { color: "" });
    expect("color" in findClip(p, clipId)!.clip).toBe(false);
    expect(() => setClipProps(p, clipId, { effect: "clip" })).toThrow(/video or picture/);
    p = setClipProps(p, clipId, { effect: "clip", media: "m2", blend: "alpha" });
    expect(findClip(p, clipId)!.clip).toMatchObject({ effect: "clip", media: "m2", blend: "alpha" });
    expect(problems(p)).toEqual([]);
    p = setClipProps(p, clipId, { effect: "aura" }); // not a clip any more: no file, no blend left over
    expect(findClip(p, clipId)!.clip).not.toHaveProperty("media");
    expect(problems(p)).toEqual([]);
    expect(() => setClipProps(sample(), "z1", { size: 1 })).toThrow(EditError); // not for other clips
  });

  it("splits, trims, moves and deletes like other effect clips", () => {
    const { project, clipId } = addTrackFx(tracked(), "glow", 0.5, { seconds: 2 });
    const split = splitClip(project, clipId, 1.5);
    expect(findClip(split.project, clipId)!.clip.duration).toBeCloseTo(1, 4);
    expect(findClip(split.project, split.rightId)!.clip).toMatchObject({ type: "trackfx", effect: "glow", start: 1.5 });
    expect(problems(split.project)).toEqual([]);
    expect(problems(trimClip(project, clipId, "end", 2))).toEqual([]);
    expect(problems(moveClip(project, clipId, 1).project)).toEqual([]);
    expect(findClip(deleteClips(project, [clipId]), clipId)).toBeNull();
  });
});

describe("what a tracked effect has to follow", () => {
  it("says when the video was not followed, and how well the point was found", () => {
    const { project, clipId } = addTrackFx(sample(), "glow", 0.2, { hand: "right", point: "index_tip" });
    expect(trackState(project, findClip(project, clipId)!.clip)).toMatchObject({ tracked: false, mediaId: "m1" });
    expect(untrackedEffects(project).map((c) => c.id)).toEqual([clipId]);
    const withTrack = { ...project, tracking: { m1: track() } };
    const s = trackState(withTrack, findClip(withTrack, clipId)!.clip);
    expect(s).toMatchObject({ tracked: true, names: ["right_index_tip"] });
    expect(s.found).toBe(1);
    expect(untrackedEffects(withTrack)).toEqual([]);
    // Found in none of it, and a point that was never saved.
    const poor = { ...project, tracking: { m1: track(300, 0.1) } };
    expect(trackState(poor, findClip(poor, clipId)!.clip).found).toBe(0);
    const left = setClipProps(withTrack, clipId, { hand: "left" });
    expect(trackState(left, findClip(left, clipId)!.clip).names).toEqual([]);
    // Python's coverage agrees (same numbers).
    const py = JSON.parse(
      execFileSync(python, ["-c", `
import json, sys
from autoedit.tracking import Track, coverage
t = Track.from_json(json.load(sys.stdin))
# the effect (timeline 0.2-2.2) sits on main clip v1 (source 1-3 = 0.2 -> 1.2 + 1.0 .. ) : source 1.2 .. 2.2... for v1 in=1
print(json.dumps(coverage(t, ["right_index_tip"], 1.2, 3.0)))`], { cwd: repo, input: JSON.stringify(track()), encoding: "utf-8" }),
    );
    expect(py).toBe(1);
    expect(trackfxLabel(findClip(project, clipId)!.clip)).toBe("Glow · right index fingertip");
  });
});

describe("the preview places the point like the engine", () => {
  it("maps a source position to the canvas (fill, reframe, blur) with the engine's numbers", () => {
    const cases: [number, number, string, { zoom?: number; x?: number; y?: number } | undefined, number, number, number][] = [
      [720, 1280, "fill", undefined, 0.3, 0.6, 0.05],
      [720, 1280, "fill", { zoom: 2, x: 0.2, y: 0.7 }, 0.45, 0.5, 0.1],
      [1280, 720, "fill", { zoom: 1.4, x: 0.8, y: 0.3 }, 0.55, 0.4, 0.2],
      [1280, 720, "blur", undefined, 0.6, 0.4, 0.3],
      [1000, 1000, "blur", undefined, 0.1, 0.9, 0.1],
    ];
    const py = JSON.parse(
      execFileSync(python, ["-c", `
import json, sys
from autoedit.trackfx import FrameMap, FrameInfo
out = []
for w, h, fit, crop, u, v, s in json.load(sys.stdin):
    z = crop or {}
    info = FrameInfo({"width": w, "height": h}, 0.0, fit, (z.get("zoom", 1.0), z.get("x", 0.5), z.get("y", 0.5)))
    out.append(FrameMap.to_frame(info, u, v, s))
print(json.dumps(out))`], { cwd: repo, input: JSON.stringify(cases), encoding: "utf-8" }),
    );
    cases.forEach(([w, h, fit, crop, u, v, s], i) => {
      const ours = toCanvas({ width: w, height: h }, fit, crop, u, v, s);
      ours.forEach((value, k) => expect(value).toBeCloseTo(py[i][k], 6));
    });
  });

  it("follows the main clip's source time through a cut and a speed change", () => {
    const p = tracked();
    p.media[0] = { ...p.media[0], width: 720, height: 1280 };
    const r = addTrackFx(p, "glow", 0, { hand: "right", point: "index_tip", seconds: 3 });
    const clip = findClip(r.project, r.clipId)!.clip;
    expect(trackfxAt(r.project, 1.0)[0].clip.id).toBe(r.clipId);
    expect(trackfxAt(r.project, 3.4)).toEqual([]);
    const paths = trackfxPaths(r.project, { ...clip, smooth: 0 });
    // Frame 45 (1.5 s): the sample at source time in + 0.5 -- main clip v1 starts at source 1 s (index 45 -> t 1.5 -> source 2.5).
    const f = 45;
    const expectedX = (0.2 + (0.5 * Math.round(2.5 * 30)) / 300) * 1080;
    expect(Math.abs(paths[0][f].x - expectedX)).toBeLessThan(2); // (smooth 0 still filters a hair)
    expect(paths[0][f].alpha).toBe(1);
    expect(followedNames(r.project.tracking!.m1, clip, 1, 3)).toEqual(["right_index_tip"]);
  });
});
