// B-roll on the timeline: the same results as the engine's add_clip / replace_clip_media, and
// projects the engine accepts.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { addBroll, brollCredits, brollExclusions, brollLabel, describeSource, replaceBroll, setBrollRequest } from "../../src/shared/brollEdit";
import { EditError, findClip, setTrackFlag } from "../../src/shared/edit";
import type { BrollMeta, Media, Project } from "../../src/shared/types";
import { sample } from "./edit.test";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const clip = (p: Project, id: string) => findClip(p, id)!.clip;

const picture: Media = { id: "x", kind: "image", path: "C:/B-roll/coffee cup.png", name: "coffee cup.png", duration: 0, width: 720, height: 1280 };
const video: Media = { id: "x", kind: "video", path: "C:/B-roll/jeepney.mp4", name: "jeepney.mp4", duration: 1.5, width: 720, height: 1280, has_audio: false };
const lib: BrollMeta = { source: "library", kind: "image", prompt: "a cup of coffee", search: "coffee cup", style: "realistic", ai_generated: false };
const stock: BrollMeta = {
  source: "pexels", kind: "video", search: "jeepney street", stock_id: "pexels-11", author: "Ana", page: "https://www.pexels.com/video/11/",
  license: "Pexels License", license_url: "https://www.pexels.com/license/", credit: "Video by Ana on Pexels (https://www.pexels.com/video/11/)",
};
const ai: BrollMeta = { source: "ai", kind: "image", prompt: "a robot waving", style: "cartoon", ai_generated: true, tier: "Mid" };

function engine(code: string, input: unknown): unknown {
  const out = execFileSync(python, ["-c", code], { cwd: repo, input: JSON.stringify(input), encoding: "utf-8" });
  return JSON.parse(out);
}

describe("B-roll clips", () => {
  it("adds a found item where the engine would, and the engine accepts the project", () => {
    const { project, clipId } = addBroll(sample(), picture, lib, 0.5, 2, "top");
    const c = clip(project, clipId);
    expect(c).toMatchObject({ type: "image", start: 0.5, duration: 2, x: 500, y: 520, width: 820, height: 560, animation: "pop", label: "Library: coffee cup" });
    expect(c.broll).toEqual({ ...lib, position: "top" });
    const py = engine(`
import json, sys
from autoedit import broll
from autoedit.project import validate_project
d = json.load(sys.stdin)
p = d["before"]
m = dict(d["media"], id="mx")
c = broll.add_clip(p, m, d["meta"], 0.5, 2.0, "top")
print(json.dumps({"clip": {k: c[k] for k in ("type", "start", "duration", "x", "y", "width", "height", "animation", "label")},
                  "problems": validate_project(d["after"])}))`, { before: sample(), media: picture, meta: lib, after: project }) as { clip: unknown; problems: string[] };
    expect(py.problems).toEqual([]);
    const { id: _id, media: _m, broll: _b, opacity: _o, ...ours } = c;
    expect(py.clip).toEqual(ours);
  });

  it("goes on another B-roll track when the first one is busy there", () => {
    const first = addBroll(sample(), picture, lib, 2.4, 1, "full");
    const overlays = first.project.tracks.filter((t) => t.kind === "overlay");
    expect(overlays.length).toBe(2); // o1 is at 2.5-3.5
    expect(overlays[1].clips.map((c) => c.id)).toEqual([first.clipId]);
  });

  it("replaces a clip's file: a short video shortens the clip; position and timing stay", () => {
    const { project, clipId } = addBroll(sample(), picture, lib, 1, 3, "full");
    const p = replaceBroll(project, clipId, video, stock);
    const c = clip(p, clipId);
    expect(c).toMatchObject({ type: "video", start: 1, duration: 1.5, in: 0, out: 1.5, x: 540, width: 1080, label: "Pexels: jeepney street" });
    expect(c.broll).toMatchObject({ source: "pexels", credit: stock.credit, position: "full" });
    expect(p.media.filter((m) => m.path === video.path)).toHaveLength(1);
    // Back to a picture: no source times left over.
    const q = replaceBroll(p, clipId, picture, ai);
    expect(clip(q, clipId)).not.toHaveProperty("in");
    expect(clip(q, clipId).duration).toBe(1.5);
    const problems = engine(`
import json, sys
from autoedit.project import validate_project
print(json.dumps([validate_project(p) for p in json.load(sys.stdin)]))`, [p, q]);
    expect(problems).toEqual([[], []]);
    // The engine's replace gives the same clip.
    const py = engine(`
import json, sys
from autoedit import broll
d = json.load(sys.stdin)
c = broll.replace_clip_media(d["p"], d["id"], dict(d["media"], id="mx"), d["meta"])
print(json.dumps({k: c.get(k) for k in ("type", "start", "duration", "in", "out", "label")}))`, { p: project, id: clipId, media: video, meta: stock });
    expect(py).toEqual({ type: "video", start: 1, duration: 1.5, in: 0, out: 1.5, label: "Pexels: jeepney street" });
  });

  it("refuses what cannot be B-roll", () => {
    const sound: Media = { id: "s", kind: "audio", path: "C:/a.mp3", duration: 3 };
    expect(() => addBroll(sample(), sound, lib, 0, 2)).toThrow(EditError);
    expect(() => replaceBroll(sample(), "v1", picture, lib)).toThrow(/Only B-roll/);
    const locked = setTrackFlag(sample(), "photos", "locked", true);
    expect(() => replaceBroll(locked, "o1", picture, lib)).toThrow(/locked/);
    expect(() => addBroll(sample(), picture, lib, 0, 0)).toThrow(EditError);
  });

  it("keeps the description for the next search, and lists credits and AI clips", () => {
    let p = addBroll(sample(), picture, lib, 0, 1).project;
    const v = addBroll(p, video, stock, 4, 1);
    p = v.project;
    const a = addBroll(p, picture, ai, 6, 1);
    p = setBrollRequest(a.project, a.clipId, { prompt: "a robot dancing", style: "anime" });
    expect(clip(p, a.clipId).broll).toMatchObject({ prompt: "a robot dancing", style: "anime", source: "ai" });
    expect(brollCredits(p)).toEqual({ credits: [stock.credit], aiClips: 1 });
    expect(brollExclusions(p, v.clipId)).toEqual(expect.arrayContaining([video.path, "pexels-11", picture.path]));
    expect(brollExclusions(sample(), "o1")).toEqual(["C:/Videos/photo.png"]);
    // A hidden track is not in the export, so not in the credits.
    const hidden = setTrackFlag(p, findClip(p, v.clipId)!.track.id, "hidden", true);
    expect(brollCredits(hidden).credits).toEqual([]);
  });

  it("labels and describes like the engine", () => {
    expect(brollLabel(lib)).toBe("Library: coffee cup");
    expect(brollLabel({ source: "ai", prompt: "x".repeat(80) })).toBe(`AI: ${"x".repeat(60)}`);
    expect(describeSource(lib, "coffee cup.png")).toBe("From your B-roll library (coffee cup.png)");
    expect(describeSource(ai, "")).toBe("Made with AI (Mid tier)");
    expect(describeSource(stock, "")).toBe(stock.credit);
    const py = engine(`
import json, sys
from autoedit.broll import broll_label
print(json.dumps([broll_label(m) for m in json.load(sys.stdin)]))`, [lib, stock, ai, { source: "ai", prompt: "x".repeat(80) }]);
    expect(py).toEqual([lib, stock, ai, { source: "ai", prompt: "x".repeat(80) }].map((m) => brollLabel(m as BrollMeta)));
  });
});
