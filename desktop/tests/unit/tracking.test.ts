// The TypeScript follow-the-point rules give exactly what the engine's give (autoedit/tracking.py)
// on the same synthetic tracks; choosing points and coverage match too.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { FINGERTIPS, Prepared, coverage, minCutoffFor, oneEuro, pickHand, pointNamesFor, pyRound, resolveSequence } from "../../src/shared/tracking";
import type { TrackData, TrackPoint } from "../../src/shared/types";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const FPS = 30;

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

/** A hand-like path with noise, a short hole, a long loss and a re-find far away. */
function track(seed: number, n = 240): TrackPoint {
  const r = rng(seed);
  const x: number[] = [];
  const y: number[] = [];
  const c: number[] = [];
  for (let i = 0; i < n; i++) {
    x.push(0.2 + 0.5 * Math.sin(i / 40) ** 2 + (r() - 0.5) * 0.02);
    y.push(0.5 + 0.2 * Math.cos(i / 25) + (r() - 0.5) * 0.02);
    c.push(0.7 + 0.3 * r());
  }
  for (let i = 50; i < 56; i++) c[i] = 0; // a short hole (bridged)
  for (let i = 100; i < 118; i++) c[i] = 0.1; // lost 0.6 s
  for (let i = 150; i < 160; i++) c[i] = 0; // lost 0.33 s: fading when found again
  for (let i = 160; i < 200; i++) x[i] = 0.9 - x[i] * 0.2;
  return { x, y, c, s: x.map((v) => 0.1 + 0.2 * v) };
}

function enginePath(point: TrackPoint, items: [number | null, number][], dt: number, smooth: number): { x: number[]; y: number[]; alpha: number[]; size: number[] } {
  const out = execFileSync(python, ["-c", `
import json, sys
from autoedit.tracking import Point, Prepared, resolve_sequence
d = json.load(sys.stdin)
pt = Point(d["x"], d["y"], d["c"], d["s"])
prep = Prepared(pt, d["fps"], d["start"], d["smooth"])
items = [(prep if k is not None else None, t) for k, t in d["items"]]
r = resolve_sequence(items, d["dt"])
print(json.dumps({"x": r.x, "y": r.y, "alpha": r.alpha, "size": r.size}))`], {
    cwd: repo,
    input: JSON.stringify({ ...point, fps: FPS, start: 0.25, smooth, items, dt }),
    encoding: "utf-8",
    maxBuffer: 1 << 26,
  });
  return JSON.parse(out);
}

describe("following a point", () => {
  it("rounds like Python (halves go to the even number)", () => {
    expect([0.5, 1.5, 2.5, 7.5, 6.5, 3.2, 3.7].map(pyRound)).toEqual([0, 2, 2, 8, 6, 3, 4]);
  });

  it("gives the same path, fading and size as the engine, for several tracks and settings", () => {
    for (const [seed, smooth] of [[1, 0], [2, 0.5], [3, 0.9], [4, 0.3]] as const) {
      const pt = track(seed);
      const prep = new Prepared(pt, FPS, 0.25, smooth);
      // 300 output frames; source time jumps (a cut) and a stretch with no track at all.
      const items: [number | null, number][] = [];
      for (let f = 0; f < 300; f++) {
        if (f >= 230 && f < 250) items.push([null, 0]);
        else if (f >= 120 && f < 160) items.push([0, 6 + (f - 120) / FPS]); // after a cut
        else items.push([0, 0.1 + f / FPS]);
      }
      const ours = resolveSequence(items.map(([k, t]) => [k === null ? null : prep, t]), 1 / FPS);
      const theirs = enginePath(pt, items, 1 / FPS, smooth);
      for (const key of ["x", "y", "alpha", "size"] as const) {
        expect(ours[key].length).toBe(theirs[key].length);
        const worst = Math.max(...ours[key].map((v, i) => Math.abs(v - theirs[key][i])));
        expect(worst, `${key} seed ${seed} smooth ${smooth}`).toBeLessThan(1e-9);
      }
    }
  });

  it("filters like the engine", () => {
    const values = [0, 1, 1, 1, 0.5, 0.5, 2];
    const theirs = JSON.parse(
      execFileSync(python, ["-c", "import json,sys; from autoedit.tracking import one_euro, min_cutoff_for; print(json.dumps([one_euro(json.load(sys.stdin), 1/30, min_cutoff_for(0.7)), min_cutoff_for(0.2)]))"], { cwd: repo, input: JSON.stringify(values), encoding: "utf-8" }),
    );
    oneEuro(values, 1 / 30, minCutoffFor(0.7)).forEach((v, i) => expect(v).toBeCloseTo(theirs[0][i], 12));
    expect(minCutoffFor(0.2)).toBeCloseTo(theirs[1], 12);
  });

  it("never jumps while visible, and fades out when lost", () => {
    const pt = track(9);
    const prep = new Prepared(pt, FPS, 0, 0.3);
    const r = resolveSequence(Array.from({ length: 240 }, (_, i) => [prep, i / FPS] as [Prepared, number]), 1 / FPS);
    expect(r.alpha[0]).toBe(0);
    expect(Math.max(...r.alpha.slice(110, 118))).toBeLessThan(0.7); // long loss: faded
    expect(r.alpha[116]).toBeLessThan(0.3);
    for (let i = 1; i < 240; i++) if (Math.min(r.alpha[i], r.alpha[i - 1]) > 0.05) expect(Math.hypot(r.x[i] - r.x[i - 1], r.y[i] - r.y[i - 1])).toBeLessThan(0.2);
  });
});

describe("choosing points", () => {
  const left = { x: new Array(90).fill(0.3), y: new Array(90).fill(0.5), c: new Array(90).fill(0.9) };
  const right = { x: new Array(90).fill(0.7), y: new Array(90).fill(0.5), c: [...new Array(40).fill(0.9), ...new Array(50).fill(0)] };
  const data: TrackData = { fps: FPS, start: 0, points: { left_palm: left, right_palm: right, face: left } };

  it("the same names, hand and coverage as the engine", () => {
    expect(pointNamesFor({ point: "face" })).toEqual(["face"]);
    expect(pointNamesFor({ point: "fingertips", hand: "left" })).toEqual(FINGERTIPS.map((f) => `left_${f}`));
    expect(pointNamesFor({ point: "palm" })).toEqual(["left_palm", "right_palm"]);
    expect(pickHand(data, "any", "palm", 0, 3)).toBe("left_palm");
    expect(pickHand(data, "right", "palm", 0, 3)).toBe("right_palm");
    const py = JSON.parse(
      execFileSync(python, ["-c", `
import json, sys
from autoedit.tracking import Track, pick_hand, coverage, point_names_for
t = Track.from_json(json.load(sys.stdin))
print(json.dumps([pick_hand(t, "any", "palm", 0, 3), pick_hand(t, "any", "palm", 0, 1), coverage(t, ["right_palm"], 0, 3), coverage(t, ["right_palm", "face"], 0, 1),
                  point_names_for({"point": "palm"}), point_names_for({"point": "fingertips", "hand": "right"})]))`], { cwd: repo, input: JSON.stringify(data), encoding: "utf-8" }),
    );
    expect(py[0]).toBe(pickHand(data, "any", "palm", 0, 3));
    expect(py[1]).toBe(pickHand(data, "any", "palm", 0, 1));
    expect(coverage(data, ["right_palm"], 0, 3)).toBeCloseTo(py[2], 12);
    expect(coverage(data, ["right_palm", "face"], 0, 1)).toBeCloseTo(py[3], 12);
    expect(pointNamesFor({ point: "palm" })).toEqual(py[4]);
    expect(pointNamesFor({ point: "fingertips", hand: "right" })).toEqual(py[5]);
  });
});
