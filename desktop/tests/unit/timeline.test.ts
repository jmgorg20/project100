import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import data from "../../src/shared/engine-data.json";
import type { Clip, Project, Word } from "../../src/shared/types";
import {
  captionAt, captionPlacement, chunkWords, covers, displayText, popScale, segmentAt, segments, sourceTime, styleFor, zoomAt,
} from "../../src/renderer/lib/timeline";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");

const TEXT = "Grabe ang bilis ng internet sa Parañaque. 500 pesos lang *GitHub* ko kasi talagang mabilis siya promise";

function sampleWords(): Word[] {
  let t = 0;
  return TEXT.split(" ").map((token, i) => {
    const w = { text: token.replace(/\*/g, ""), start: t, end: t + 0.3, highlight: token.includes("*") || i === 7 };
    t += i === 9 ? 1.2 : 0.4; // a long pause after word 9 starts a new group
    return w;
  });
}

function project(clips: Clip[], extra: Project["tracks"] = []): Project {
  return {
    format: "autoedit-project", version: 1, settings: { width: 1080, height: 1920, fps: 30 }, media: [],
    tracks: [{ id: "main", kind: "video", clips }, ...extra],
  };
}

describe("captions match the engine", () => {
  // The engine's own grouping and timing for the same words, for every style.
  const script = `
import json, sys
from autoedit.captions import chunk_words, group_end_times, display_text
from autoedit.styles import STYLES
from autoedit.words import Word
words = [Word(w["text"], w["start"], w["end"], highlight=w["highlight"]) for w in json.loads(sys.argv[1])]
out = {}
for s in STYLES:
    groups = chunk_words(words, s)
    ends = group_end_times(groups, last_end=float(sys.argv[2]))
    out[s.name] = {"groups": [[[display_text(w, s) for w in line] for line in g] for g in groups],
                   "ends": ends, "starts": [g[0][0].start for g in groups]}
print(json.dumps(out))`;
  const words = sampleWords();
  const clipEnd = words[words.length - 1].end + 0.25;
  const engine = JSON.parse(
    execFileSync(python, ["-c", script, JSON.stringify(words), String(clipEnd)], { cwd: repo, encoding: "utf-8" }),
  );

  for (const style of data.styles) {
    it(`groups and times words like the engine: ${style.name}`, () => {
      const groups = chunkWords(words, style);
      expect(groups.map((g) => g.map((line) => line.map((w) => displayText(w, style))))).toEqual(engine[style.name].groups);
      // The caption shown at each moment matches the engine's group start/end times.
      const clip: Clip = { id: "c", type: "caption", start: 0, duration: clipEnd, style: style.name, words };
      const p = project([], [{ id: "cap", kind: "caption", clips: [clip] }]);
      const { starts, ends } = engine[style.name] as { starts: number[]; ends: number[] };
      for (let t = 0; t < clipEnd; t += 0.05) {
        const g = starts.findIndex((s, i) => t >= s && t < ends[i]);
        const frame = captionAt(p, t);
        if (g < 0) expect(frame, `t=${t.toFixed(2)}`).toBeNull();
        else {
          expect(frame?.lines.flat()[0].start, `t=${t.toFixed(2)}`).toBeCloseTo(starts[g], 6);
          const flat = frame!.lines.flat();
          expect(flat[frame!.active].start).toBeLessThanOrEqual(t + 1e-9);
          expect(flat[frame!.active + 1]?.start ?? Infinity).toBeGreaterThan(t);
        }
      }
    });
  }

  it("places captions where the subtitle file puts them", () => {
    const lower = captionPlacement(styleFor({ id: "c", type: "caption", start: 0, duration: 1, style: "classic" }), 2);
    expect(lower).toEqual({ x: 500, top: 1450 - 2 * 74, left: false, height: 148 });
    const top = captionPlacement(styleFor({ id: "c", type: "caption", start: 0, duration: 1, style: "top_banner" }), 1);
    expect(top.top).toBe(250);
    const big = styleFor({ id: "c", type: "caption", start: 0, duration: 1, style: "classic", overrides: { size: 100, zone: "center" } });
    expect(captionPlacement(big, 2).top).toBe(940 - 100);
    expect(captionPlacement(styleFor({ id: "c", type: "caption", start: 0, duration: 1, style: "typewriter" }), 1).left).toBe(true);
  });
});

describe("timeline", () => {
  const clips: Clip[] = [
    { id: "a", type: "video", media: "m", start: 0, duration: 1, in: 2, out: 3 },
    { id: "b", type: "video", media: "m", start: 1.5, duration: 1, in: 5, out: 6 },
  ];

  it("lists segments with gaps and maps to source time", () => {
    const p = project(clips, [{ id: "fx", kind: "effect", clips: [{ id: "z", type: "zoom", start: 0.5, duration: 0.5, amount: 1.3 }] }]);
    const segs = segments(p);
    expect(segs.map((s) => [s.start, s.end, s.clip?.id ?? null])).toEqual([[0, 1, "a"], [1, 1.5, null], [1.5, 2.5, "b"]]);
    expect(segmentAt(segs, 1.2)).toBe(1);
    expect(sourceTime(segs[2], 2)).toBeCloseTo(5.5);
    expect(zoomAt(p, 0.7)).toEqual({ amount: 1.3, anchorY: 0.4 });
    expect(zoomAt(p, 1.0).amount).toBe(1);
  });

  it("uses the renderer's frame rule", () => {
    const clip: Clip = { id: "o", type: "image", start: 0.5, duration: 0.5, x: 0, y: 0, width: 1, height: 1 };
    expect(covers(clip, 0.49, 30)).toBe(false);
    expect(covers(clip, 0.5, 30)).toBe(true);
    expect(covers(clip, 0.999, 30)).toBe(true);
    expect(covers(clip, 1.0, 30)).toBe(false);
  });

  it("pops photos in with the render's curve", () => {
    expect(popScale(0, 2)).toBeCloseTo(0.5);
    expect(popScale(0.15, 2)).toBeCloseTo(1.1);
    expect(popScale(1, 2)).toBe(1);
    expect(popScale(2, 2)).toBeCloseTo(0.8);
  });
});
