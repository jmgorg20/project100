import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { EditError, deleteClips, moveClip, splitAt, trimClip } from "../../src/shared/edit";
import {
  CATALOG, GRAPHIC_STYLES, addGraphic, addWipe, alternatives, anotherLook, attachClips, cleanParams, graphicsAt, searchTemplates, setClipLocked,
  setGraphic, setWipe, templateMeta, wipeAt,
} from "../../src/shared/graphicsEdit";
import type { Project } from "../../src/shared/types";
import { sample } from "./edit.test";

const repo = path.resolve(__dirname, "..", "..", "..");
const python = process.platform === "win32" ? "python" : "python3";
const gfx = (p: Project) => p.tracks.filter((t) => t.kind === "graphics").flatMap((t) => t.clips).sort((a, b) => a.start - b.start);

describe("graphics catalog", () => {
  it("the app's copy of the catalog is the engine's", () => {
    const engine = JSON.parse(fs.readFileSync(path.join(repo, "autoedit", "graphics_catalog.json"), "utf-8"));
    expect(CATALOG).toEqual(engine);
    expect(CATALOG.templates.length).toBeGreaterThanOrEqual(30);
  });

  it("the style list matches the engine's Director styles", () => {
    const out = execFileSync(python, ["-c", "import json; from autoedit.director_styles import STYLES; print(json.dumps(list(STYLES)))"], { cwd: repo, encoding: "utf-8" });
    expect(GRAPHIC_STYLES.map((s) => s.id).filter((s) => s !== "auto" && s !== "off")).toEqual(JSON.parse(out));
  });

  it("searches by name, Taglish name, category and mood", () => {
    expect(searchTemplates("counter", "").map((t) => t.id)).toEqual(["counter-number"]);
    expect(searchTemplates("tatak", "").map((t) => t.id)).toEqual(["stamp"]);
    expect(searchTemplates("", "money").every((t) => t.moods.includes("money"))).toBe(true);
    expect(searchTemplates("", "", new Set(["stamp", "emoji-pop"])).length).toBe(2);
  });
});

describe("graphic clips", () => {
  it("adds a template at the playhead with its sample words, on a Graphics track", () => {
    const r = addGraphic(sample(), "pop-heavy", 2);
    const [g] = gfx(r.project);
    expect(g.id).toBe(r.clipId);
    expect(g.start).toBe(2);
    expect(g.params?.text).toBe(templateMeta("pop-heavy")!.sample.text);
    expect(g.x).toBe(0.5);
    // a second one at the same time goes on another lane
    const r2 = addGraphic(r.project, "stamp", 2.2);
    expect(r2.project.tracks.filter((t) => t.kind === "graphics").length).toBe(2);
  });

  it("keeps params valid: clamps, drops unknown fonts and bad colours, ignores fields the template lacks", () => {
    const meta = templateMeta("counter-number")!;
    const out = cleanParams(meta, { number: 12, size: 9, intensity: -1, font: "nope", color: "red", accent: "#ABCDEF", emoji: "🔥", text: "x" });
    expect(out).toEqual({ number: 12, size: 2.5, intensity: 0, accent: "#abcdef", text: "x" });
  });

  it("changing the template keeps the words and drops settings the new one does not have", () => {
    let p = addGraphic(sample(), "price-tag", 1, { number: 499, prefix: "₱" }).project;
    const id = gfx(p)[0].id;
    p = setGraphic(p, id, { template: "counter-number" });
    expect(gfx(p)[0].params).toMatchObject({ number: 499, prefix: "₱" });
    p = setGraphic(p, id, { params: { prefix: "" } });
    expect(gfx(p)[0].params?.prefix).toBeUndefined();
  });

  it("a locked graphic cannot be moved, trimmed, split, changed or deleted, and ripples leave it in place", () => {
    let p = addGraphic(sample(), "stamp", 1).project;
    const id = gfx(p)[0].id;
    p = setClipLocked(p, id, true);
    expect(() => moveClip(p, id, 2)).toThrow(EditError);
    expect(() => trimClip(p, id, "end", 1.5)).toThrow(/locked/);
    expect(() => deleteClips(p, [id])).toThrow(/locked/);
    expect(() => setGraphic(p, id, { params: { text: "y" } })).toThrow(/locked/);
    expect(() => anotherLook(p, id)).toThrow(/locked/);
    expect(() => splitAt(p, 1.5, [id])).toThrow(EditError);
    // deleting a main clip before it moves other clips, not the locked one
    const main = p.tracks.find((t) => t.kind === "video")!.clips[0];
    const after = deleteClips(p, [main.id]);
    expect(gfx(after).find((c) => c.id === id)!.start).toBe(1);
    p = setClipLocked(p, id, false);
    expect(moveClip(p, id, 2).project).toBeTruthy();
  });

  it("another look: same kind, never a neighbour's template, words kept", () => {
    let p = sample();
    for (const [t, at] of [["pop-heavy", 0], ["stamp", 1.5], ["glow-blur-in", 3]] as const) p = addGraphic(p, t, at).project;
    const id = gfx(p)[1].id;
    for (let i = 0; i < 8; i++) {
      p = anotherLook(p, id);
      const g = gfx(p);
      expect(g[1].template).not.toBe(g[0].template);
      expect(g[1].template).not.toBe(g[2].template);
      expect(templateMeta(g[1].template)!.category).toBe("text");
    }
  });

  it("alternatives respect number ranges (a big number is never a star rating)", () => {
    const p = addGraphic(sample(), "counter-number", 0, { number: 250000 }).project;
    const ids = alternatives(p, gfx(p)[0].id).map((m) => m.id);
    expect(ids).toContain("price-tag");
    expect(ids).not.toContain("rating-stars");
    expect(ids).not.toContain("stat-bar");
  });

  it("graphics on screen follow the frame grid like the engine", () => {
    const p = addGraphic(sample(), "stamp", 1).project;
    const fps = p.settings.fps;
    const g = gfx(p)[0];
    expect(graphicsAt(p, 1 - 1 / fps)).toHaveLength(0);
    expect(graphicsAt(p, 1)).toHaveLength(1);
    expect(graphicsAt(p, g.start + g.duration)).toHaveLength(0);
  });
});

describe("attachments and wipes", () => {
  it("the preview's flash / whip / punch-in clips are the engine's", () => {
    let p = sample();
    for (const [t, at, kind] of [["stamp", 0.5, "flash"], ["pop-heavy", 2, "whip"], ["glow-blur-in", 3.5, "punch"]] as const) {
      const r = addGraphic(p, t, at);
      p = setGraphic(r.project, r.clipId, { attach: { kind, intensity: 0.8 } });
    }
    const out = execFileSync(python, ["-c", "import json,sys; from autoedit.graphics import attach_clips; print(json.dumps(attach_clips(json.load(sys.stdin))))"], { cwd: repo, input: JSON.stringify(p), encoding: "utf-8" });
    const engine = JSON.parse(out);
    const ours = attachClips(p);
    expect(ours.length).toBe(3);
    for (const [a, b] of ours.map((c, i) => [c, engine[i]])) {
      expect(a.type).toBe(b.type);
      expect(a.start).toBeCloseTo(b.start, 6);
      expect(a.duration).toBeCloseTo(b.duration, 6);
      if (a.type === "zoom") expect(a.amount).toBeCloseTo(b.amount, 6);
      else expect(a.effect).toBe(b.effect);
    }
  });

  it("the wipe's divider moves like the engine's expression and stays at its stop", () => {
    let p = addWipe(sample(), 1, "warm", 3).project;
    const id = p.tracks.flatMap((t) => t.clips).find((c) => c.type === "wipe")!.id;
    p = setWipe(p, id, { sweep: 1, stop: 0.6 });
    expect(wipeAt(p, 0.9)).toBeNull();
    expect(wipeAt(p, 1)!.pos).toBeCloseTo(0, 6);
    expect(wipeAt(p, 1.5)!.pos).toBeCloseTo(0.6 * (1 - Math.pow(0.5, 3)), 6);
    const w = p.tracks.flatMap((t) => t.clips).find((c) => c.type === "wipe")!;
    expect(w.duration).toBeGreaterThan(1.2);
    expect(wipeAt(p, w.start + w.duration - 0.01)!.pos).toBeCloseTo(0.6 * (1 - Math.pow(Math.max(0, 1 - (w.duration - 0.01)), 3)), 6);
    expect(() => setWipe(p, gfx(addGraphic(p, "stamp", 0).project)[0]?.id ?? "x", {})).toThrow();
  });
});
