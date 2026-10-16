import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  addCaption, addEmoji, cleanVocabulary, correctCaptions, correctWords, editWordText, setCaptionLook, setCaptionWords, toggleHighlight,
} from "../../src/shared/captionEdit";
import { EditError, findClip } from "../../src/shared/edit";
import { addFx, addGrade, addTransition, addZoom, nearestCut, setAudioSettings, speedRamp } from "../../src/shared/effectsEdit";
import type { Project, Word } from "../../src/shared/types";
import { sample } from "./edit.test";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const clip = (p: Project, id: string) => findClip(p, id)!.clip;
const w = (text: string, start: number, end: number): Word => ({ text, start, end });

describe("corrections", () => {
  it("give exactly what the engine's corrections give", () => {
    const fixes = [{ from: "g cash", to: "GCash" }, { from: "sho pee", to: "Shopee" }, { from: "g", to: "Gee" }];
    const words = [w("Bayad", 0, 0.4), w("sa", 0.5, 0.6), w("G", 0.7, 0.8), w("Cash,", 0.85, 1.2), w("tapos", 1.3, 1.6), w("SHO", 1.7, 1.8), w("pee!", 1.85, 2.1), w("ñ-g", 2.2, 2.3)];
    const ours = correctWords(words, fixes).map((x) => [x.text, x.start, x.end]);
    const engine = execFileSync(python, ["-c", `
import json, sys
from autoedit.vocabulary import apply_corrections
from autoedit.words import Word
d = json.load(sys.stdin)
out = apply_corrections([Word(x["text"], x["start"], x["end"]) for x in d["words"]], d["fixes"])
print(json.dumps([[x.text, x.start, x.end] for x in out]))`], { cwd: repo, input: JSON.stringify({ words, fixes }), encoding: "utf-8" });
    expect(ours).toEqual(JSON.parse(engine));
    expect(ours.map((x) => x[0])).toEqual(["Bayad", "sa", "GCash,", "tapos", "Shopee!", "ñ-g"]);
  });

  it("clean the vocabulary and fix every caption", () => {
    expect(cleanVocabulary({ words: ["GCash", " gcash ", ""], corrections: [{ from: "", to: "x" }, { from: "kayo", to: "Kayo" }] })).toEqual({
      words: ["GCash"],
      corrections: [{ from: "kayo", to: "Kayo" }],
    });
    const { project, changed } = correctCaptions(sample(), [{ from: "kayo", to: "kayong lahat" }]);
    expect(changed).toBe(1);
    expect(clip(project, "t1").words!.map((x) => x.text)).toEqual(["Kumusta", "kayong lahat"]);
  });
});

describe("caption editing", () => {
  it("edits text: one word, several words sharing its time, or none (removed)", () => {
    let p = editWordText(sample(), "t1", 0, "Hello");
    expect(clip(p, "t1").words![0]).toMatchObject({ text: "Hello", start: 0, end: 0.5 });
    p = editWordText(p, "t1", 0, "Hi there");
    expect(clip(p, "t1").words!.slice(0, 2)).toEqual([w("Hi", 0, 0.25), w("there", 0.25, 0.5)]);
    p = editWordText(p, "t1", 1, "");
    expect(clip(p, "t1").words!.map((x) => x.text)).toEqual(["Hi", "kayo"]);
    expect(() => setCaptionWords(sample(), "t2", [w("  ", 0, 1)])).toThrow(EditError);
    expect(() => setCaptionWords(sample(), "v1", [w("x", 0, 1)])).toThrow(/not a caption/);
  });

  it("keeps word times inside the caption and in order", () => {
    const p = setCaptionWords(sample(), "t1", [w("a", 0.5, 0.4), w("b", 0.2, 9), w("c", -1, 0.1)]);
    expect(clip(p, "t1").words).toEqual([w("a", 0.5, 0.5), w("b", 0.5, 1.2), w("c", 0.5, 0.5)]);
  });

  it("changes style, place, size and highlights; adds emoji and new captions", () => {
    let p = setCaptionLook(sample(), "all", { style: "bold_caps", zone: "top", size: 999 });
    expect(clip(p, "t2")).toMatchObject({ style: "bold_caps", overrides: { zone: "top", size: 300 } });
    p = setCaptionLook(p, ["t1"], { zone: "auto", size: null, highlight_keywords: false });
    expect(clip(p, "t1").overrides).toBeUndefined();
    expect(clip(p, "t1").highlight_keywords).toBe(false);
    p = toggleHighlight(p, "t1", 1);
    expect(clip(p, "t1").words![1].highlight).toBe(true);
    p = addEmoji(p, "t1", 1, "🔥");
    expect(clip(p, "t1").words![1].text).toBe("kayo 🔥");
    const added = addCaption(p, 5, "Salamat po sa inyo");
    expect(clip(added.project, added.clipId)).toMatchObject({ start: 5, duration: 2, style: "bold_caps" });
    expect(clip(added.project, added.clipId).words).toHaveLength(4);
  });
});

describe("effects", () => {
  it("adds moment effects, zooms and grades as clips", () => {
    let r = addFx(sample(), "flash", 1);
    expect(clip(r.project, r.clipId)).toMatchObject({ type: "fx", effect: "flash", start: 1, duration: 0.3, intensity: 0.6 });
    r = addZoom(sample(), "smooth", 0.5);
    expect(clip(r.project, r.clipId)).toMatchObject({ type: "zoom", start: 0.5, duration: 1.5, ease: 1 });
    r = addGrade(sample(), "warm", "v2", 0.5);
    expect(clip(r.project, r.clipId)).toMatchObject({ type: "grade", start: 2, duration: 1.5, intensity: 0.5 });
    expect(() => addGrade(sample(), "sepia")).toThrow(EditError);
  });

  it("puts a transition on the nearest cut", () => {
    expect(nearestCut(sample(), 0.3)).toBe(2);
    const r = addTransition(sample(), "whip", 0.3);
    expect(clip(r.project, r.clipId)).toMatchObject({ start: 1.85, duration: 0.3, effect: "whip" });
    const single = { ...sample(), tracks: sample().tracks.map((t) => (t.kind === "video" ? { ...t, clips: [t.clips[0]] } : t)) };
    expect(() => addTransition(single, "flash", 1)).toThrow(/no cut/);
  });

  it("makes a speed ramp out of normal clips", () => {
    const p = speedRamp(sample(), "v1", "bullet");
    const main = p.tracks.find((t) => t.kind === "video")!.clips.sort((a, b) => a.start - b.start);
    expect(main.map((c) => c.speed ?? 1)).toEqual([1, 0.4, 1, 1]);
    expect(main[1].out! - main[1].in!).toBeCloseTo(2 / 3, 3);
    expect(main[1].duration).toBeCloseTo(2 / 3 / 0.4, 3);
    expect(() => speedRamp(sample(), "t1", "bullet")).toThrow(EditError);
  });

  it("changes the project's sound settings within range", () => {
    const p = setAudioSettings(sample(), { normalize: true, loudness: -99, ducking: 2, denoise: 0 });
    expect(p.settings.audio).toEqual({ normalize: true, loudness: -70, ducking: 1 });
  });
});
