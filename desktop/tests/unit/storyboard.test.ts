// The app's storyboard is the engine's: same scenes, same lock and word edits (checked against
// autoedit/storyboard.py), and every result is a project the engine accepts.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { EditError, deleteClips, moveClip } from "../../src/shared/edit";
import { scenes, setSceneLocked, setSceneText, spread } from "../../src/shared/storyboard";
import type { Clip, Project } from "../../src/shared/types";
import { sample } from "./edit.test";

const repo = path.resolve(__dirname, "..", "..", "..");
const python = process.platform === "win32" ? "python" : "python3";

function engine(code: string, input: unknown): unknown {
  const out = execFileSync(python, ["-c", `import json,sys\nfrom autoedit import storyboard\nfrom autoedit.project import validate_project\nd=json.load(sys.stdin)\n${code}`], { cwd: repo, input: JSON.stringify(input), encoding: "utf-8" });
  return JSON.parse(out);
}

const SCRIPT = "Alam niyo ba kung paano ako nakaipon? Simple lang. Una, nag-budget ako ng 500 piso kada linggo. Pangalawa, iniwasan ko ang milk tea. Tapos nag-invest ako sa index fund. Ang resulta, 50,000 sa isang taon! I-follow niyo ako para sa part two!".split(" ");

/** A talking video with captions every few words, a graphic, music, a sound and a grade. */
export function talk(): Project {
  const p = { ...sample(), version: 2 };
  const per = 0.42;
  const total = Math.round((SCRIPT.length * per + 1) * 100) / 100;
  p.media[0].duration = total + 2;
  p.tracks[0].clips = [{ id: "v1", type: "video", media: "m1", start: 0, duration: total, in: 0, out: total }];
  p.tracks[1].clips = [{ id: "o1", type: "image", media: "m2", start: 4.2, duration: 1.5, x: 540, y: 960, width: 600, height: 400 }];
  const caps: Clip[] = [];
  let group: string[] = [];
  let start = 0.3;
  SCRIPT.forEach((w, i) => {
    group.push(w);
    if (group.length >= 4 || /[.!?]$/.test(w) || i === SCRIPT.length - 1) {
      const d = group.length * per;
      caps.push({ id: `t${caps.length + 1}`, type: "caption", start: Math.round(start * 1e4) / 1e4, duration: Math.round(d * 1e4) / 1e4, style: "yellow_pop",
        words: group.map((text, k) => ({ text, start: Math.round(k * per * 1e4) / 1e4, end: Math.round((k + 0.8) * per * 1e4) / 1e4 })) });
      start += d + 0.05;
      group = [];
    }
  });
  p.tracks[3].clips = caps;
  p.tracks[2].clips = [{ id: "gr", type: "grade", start: 0, duration: 5, grade: "warm" }];
  p.tracks.splice(3, 0, { id: "graphics", kind: "graphics", name: "Graphics", clips: [
    { id: "g1", type: "graphic", template: "stamp", start: 6.4, duration: 1.0, params: { text: "SIMPLE" }, x: 0.5, y: 0.3, attach: { kind: "whip" } },
  ] });
  p.media.push({ id: "pop", kind: "audio", path: "C:/sfx/pop.wav", duration: 0.3 });
  p.tracks.push({ id: "sfx", kind: "audio", role: "sfx", name: "Sound effects", clips: [{ id: "x1", type: "audio", media: "pop", start: 6.4, duration: 0.3, in: 0, out: 0.3 }] });
  const music = p.tracks.find((t) => t.role === "music")!;
  music.clips = [{ id: "a1", type: "audio", media: "m3", start: 0, duration: total, in: 0, out: total, volume: 0.2 }];
  return p;
}

describe("storyboard", () => {
  it("has the same scenes as the engine (several projects)", () => {
    for (const p of [sample(), talk(), deleteClips(talk(), ["t3"]), moveClip(talk(), "g1", 1.0).project]) {
      const ours = scenes(p);
      expect(ours).toEqual(engine("print(json.dumps(storyboard.scenes(d)))", p));
      expect(ours[0].start).toBe(0);
    }
    const q = talk();
    const at = scenes(q)[2].start + 0.1;
    for (const t of q.tracks) for (const c of t.clips) if (c.id === "g1" || c.id === "x1") c.start = at;
    const s = scenes(q);
    expect(s).toEqual(engine("print(json.dumps(storyboard.scenes(d)))", q));
    expect(s.length).toBeGreaterThanOrEqual(4);
    expect(s[0].purpose).toBe("hook");
    expect(s[s.length - 1].purpose).toBe("cta");
    expect(s.some((x) => x.transition === "whip" && x.sfx === 1 && x.graphics[0]?.text === "SIMPLE")).toBe(true);
    expect(s[0].mood).toBe("warm");
  });

  it("locks and edits words like the engine, and the engine accepts the result", () => {
    const p = talk();
    const id = scenes(p)[1].id;
    const locked = setSceneLocked(p, id, true);
    expect(scenes(locked)[1].locked).toBe(true);
    expect(locked).toEqual(engine(`print(json.dumps(storyboard.set_locked(d, "${id}", True)))`, p));
    expect(() => setSceneText(locked, id, "bago")).toThrow(EditError);
    expect(() => moveClip(locked, scenes(locked)[1].clips[0], 0.5)).toThrow(EditError);   // the editors respect the lock
    const edited = setSceneText(p, "3", "Una, mag-budget ng *500* kada linggo");
    expect(edited).toEqual(engine(`print(json.dumps(storyboard.set_text(d, "3", "Una, mag-budget ng *500* kada linggo")))`, p));
    expect(scenes(edited)[2].text).toBe("Una, mag-budget ng *500* kada linggo");
    expect(scenes(edited).map((x) => x.start)).toEqual(scenes(p).map((x) => x.start));
    for (const q of [locked, edited, setSceneText(p, "2", "Isa")]) expect(engine("print(json.dumps(validate_project(d)))", q)).toEqual([]);
    expect(p).toEqual(talk());
  });

  it("spreads words like the engine", () => {
    const cases: [number[], number][] = [[[5, 5], 4], [[2, 6], 4], [[3, 3, 3], 2], [[1, 7, 2], 13], [[4, 4, 1], 20], [[0, 0], 5]];
    for (const [counts, total] of cases) {
      expect(spread(counts, total)).toEqual(engine(`print(json.dumps(storyboard._spread(${JSON.stringify(counts)}, ${total})))`, null));
    }
  });
});
