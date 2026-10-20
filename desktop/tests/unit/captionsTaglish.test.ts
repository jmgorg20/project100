// Captions without punctuation (the same rule as the engine), fixing the words before the edit,
// and the job arguments.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { jobArgs } from "../../src/main/jobArgs";
import { cleanSettings, defaultSettings } from "../../src/main/settings";
import { retimeLine, setCaptionPunctuation, transcriptLines } from "../../src/shared/captionEdit";
import { applyEvent, finishJob, newJob } from "../../src/shared/jobs";
import type { Job, Project } from "../../src/shared/types";
import { captionAt, displayText, stripPunctuation, styleFor } from "../../src/renderer/lib/timeline";

const repo = path.resolve(__dirname, "..", "..", "..");
const python = process.platform === "win32" ? "python" : "python3";
const CASES = ["lang!", "DISIPLINA.", "isa!", "ko:", "Una;", '"Hello,"', "“Oo”", "i-check,", "mag-post", "3,600", "1.5.",
  "₱1,299!", "it's", "Ma’am,", "*ako!*", "follower...", "ngayon?!", "—", "(ito)", "ñaño!", "'quoted'"];

describe("caption punctuation", () => {
  it("removes it exactly like the engine", () => {
    const code = `import json,sys; from autoedit.captions import strip_punctuation as s; print(json.dumps([s(t) for t in json.loads(sys.argv[1])]))`;
    const engine = JSON.parse(execFileSync(python, ["-c", code, JSON.stringify(CASES)], { cwd: repo, encoding: "utf-8" }));
    expect(CASES.map(stripPunctuation)).toEqual(engine);
  });

  it("the preview follows the project setting (default remove)", () => {
    const project = {
      settings: { width: 1080, height: 1920, fps: 30 },
      media: [],
      tracks: [{ id: "captions", kind: "caption", name: "Captions", clips: [{ id: "c1", type: "caption", start: 0, duration: 2, style: "classic", words: [{ text: "Teka", start: 0, end: 0.4 }, { text: "lang!", start: 0.5, end: 0.9 }] }] }],
    } as unknown as Project;
    const shown = (p: Project) => {
      const f = captionAt(p, 0.6)!;
      return f.lines.flat().map((w) => displayText(w, f.style)).join(" ");
    };
    expect(shown(project)).toBe("Teka lang");
    const kept = setCaptionPunctuation(project, "keep");
    expect(shown(kept)).toBe("Teka lang!");
    expect(styleFor(kept.tracks[0].clips[0], kept)).toMatchObject({ punctuation: "keep" });
    expect(project.tracks[0].clips[0].words![1].text).toBe("lang!"); // the words are not changed
  });
});

describe("fix the words before the edit", () => {
  const words = [
    { text: "Teka", start: 0.3, end: 0.6 }, { text: "lang!", start: 0.7, end: 1.0 },
    { text: "Tatyo", start: 1.9, end: 2.2 }, { text: "sikreto.", start: 2.3, end: 2.7 },
  ];
  it("shows lines and keeps the times when the word count is the same", () => {
    const lines = transcriptLines(words);
    expect(lines.map((l) => l.map((w) => w.text).join(" "))).toEqual(["Teka lang!", "Tatyo sikreto."]);
    expect(retimeLine(lines[1], "Tatlo sikreto.")).toEqual([{ text: "Tatlo", start: 1.9, end: 2.2 }, { text: "sikreto.", start: 2.3, end: 2.7 }]);
  });
  it("spreads new words over the line, and an empty line removes it", () => {
    const out = retimeLine(transcriptLines(words)[1], "Tatlong mga sikreto");
    expect(out.map((w) => w.text)).toEqual(["Tatlong", "mga", "sikreto"]);
    expect(out[0].start).toBe(1.9);
    expect(out[2].end).toBeLessThanOrEqual(2.7);
    expect(retimeLine(transcriptLines(words)[0], "  ")).toEqual([]);
  });
});

describe("sound effects setting", () => {
  it("is auto by default; off and a volume reach the engine", () => {
    const d = defaultSettings("win32", "C:/engine");
    expect(d.soundEffects).toBe("auto");
    expect(cleanSettings({ soundEffects: "loud", soundEffectsVolume: 7 }, d)).toMatchObject({ soundEffects: "auto", soundEffectsVolume: 0.35 });
    const job = newJob("j3", { video: "C:/v.mp4", photos: [], instruction: "", provider: "groq", auto: true, mode: "new" });
    expect(jobArgs(job as Job, d, { instructionFile: "i.txt", output: "o.mp4" })).not.toContain("--sfx");
    const args = jobArgs(job as Job, { ...d, soundEffects: "off", soundEffectsVolume: 0.6 }, { instructionFile: "i.txt", output: "o.mp4" }).join(" ");
    expect(args).toContain("--sfx off");
    expect(args).toContain("--sfx-volume 0.6");
  });
});

describe("a stuck engine", () => {
  it("exit code 3 says it got stuck and where its logs are", () => {
    const job = newJob("j5", { video: "C:/v.mp4", photos: [], instruction: "", provider: "groq", auto: true, mode: "new" });
    const ended = finishJob({ ...job, status: "running" } as Job, 3, false);
    expect(ended.status).toBe("failed");
    expect(ended.error).toContain("got stuck");
    expect(ended.error).toContain("edit.log");
    expect(ended.error).toContain("engine-stack.log");
  });
});

describe("face finder setting", () => {
  it("is auto by default; off reaches the engine", () => {
    const d = defaultSettings("win32", "C:/engine");
    expect(d.faceFinder).toBe("auto");
    expect(cleanSettings({ faceFinder: "maybe" } as never, d).faceFinder).toBe("auto");
    const job = newJob("j4", { video: "C:/v.mp4", photos: [], instruction: "", provider: "groq", auto: true, mode: "new" });
    expect(jobArgs(job as Job, d, { instructionFile: "i.txt", output: "o.mp4" })).not.toContain("--face-finder");
    expect(jobArgs(job as Job, { ...d, faceFinder: "off" }, { instructionFile: "i.txt", output: "o.mp4" }).join(" ")).toContain("--face-finder off");
  });
});

describe("caption style setting", () => {
  it("is the preset's by default and is passed to the engine when you pick one", () => {
    const d = defaultSettings("win32", "C:/engine");
    expect(d.captionStyle).toBe("preset");
    expect(cleanSettings({ captionStyle: "x; rm -rf" }, d).captionStyle).toBe("preset");
    const job = newJob("j2", { video: "C:/v.mp4", photos: [], instruction: "", provider: "groq", auto: true, mode: "new" });
    expect(jobArgs(job as Job, d, { instructionFile: "i.txt", output: "o.mp4" })).not.toContain("--caption-style");
    const args = jobArgs(job as Job, { ...d, captionStyle: "editorial_card" }, { instructionFile: "i.txt", output: "o.mp4" });
    expect(args.join(" ")).toContain("--caption-style editorial_card");
  });
});

describe("settings and job arguments", () => {
  it("defaults to remove, and passes the setting and a fixed transcript to the engine", () => {
    const d = defaultSettings("win32", "C:/engine");
    expect(d.captionPunctuation).toBe("remove");
    expect(d.fixCaptionsFirst).toBe(false);
    expect(cleanSettings({ captionPunctuation: "sometimes" }, d).captionPunctuation).toBe("remove");
    const job = newJob("j1", { video: "C:/v.mp4", photos: [], instruction: "", provider: "groq", auto: true, mode: "new", transcriptFile: "C:/t.json" });
    const args = jobArgs(job as Job, { ...d, captionPunctuation: "keep" }, { instructionFile: "i.txt", output: "o.mp4" });
    expect(args.join(" ")).toContain("--caption-punctuation keep");
    expect(args.join(" ")).toContain("--transcript C:/t.json");
  });

  it("a warning from the engine is kept with the job", () => {
    const job = newJob("j1", { video: "v", photos: [], instruction: "", provider: "groq", auto: true, mode: "new" });
    const next = applyEvent(job, { type: "warning", message: "Graphic g2 was left out: EPERM C:\\cache\\a.mkv" });
    expect(next.warnings).toEqual(["Graphic g2 was left out: EPERM C:\\cache\\a.mkv"]);
  });
});
