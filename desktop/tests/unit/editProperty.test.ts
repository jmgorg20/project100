// Random edit sequences, each result checked by the engine's own validator
// (autoedit/project.py), so the editor can never save a project the engine refuses.
import { execFileSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import {
  EditError, deleteClips, insertMedia, moveClip, moveMainClip, projectDuration, setClipProps, setSpeed, setTrackFlag, splitAt,
  splitClip, trimClip,
} from "../../src/shared/edit";
import type { Project } from "../../src/shared/types";
import { sample } from "./edit.test";
import { addCaption, addEmoji, correctCaptions, editWordText, setCaptionLook, toggleHighlight } from "../../src/shared/captionEdit";
import { addFx, addGrade, addTransition, addZoom, setAudioSettings, speedRamp } from "../../src/shared/effectsEdit";
import { addBroll, replaceBroll, setBrollRequest } from "../../src/shared/brollEdit";
import type { BrollMeta } from "../../src/shared/types";
import { addTrackFx } from "../../src/shared/trackEdit";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");

function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function randomEdit(p: Project, r: () => number): Project {
  const clips = p.tracks.flatMap((t) => t.clips.map((c) => ({ t, c })));
  if (!clips.length) return insertMedia(p, "m1", 0).project;
  const { t, c } = clips[Math.floor(r() * clips.length)];
  const at = r() * (projectDuration(p) + 1);
  const pick = Math.floor(r() * 25);
  if (pick >= 22) return trackEdit(p, r, t, c, at);
  if (pick >= 19) return brollEdit(p, r, t, c, at);
  if (pick >= 11) return phase2Edit(p, r, pick, t, c, at);
  switch (pick) {
    case 0:
      return splitClip(p, c.id, c.start + r() * c.duration).project;
    case 1:
      return splitAt(p, at);
    case 2:
      return deleteClips(p, [c.id]);
    case 3:
      return trimClip(p, c.id, r() < 0.5 ? "start" : "end", c.start + (r() * 2 - 0.5) * c.duration);
    case 4:
      return t.kind === "video" ? moveMainClip(p, c.id, Math.floor(r() * t.clips.length)) : moveClip(p, c.id, at).project;
    case 5:
      return setSpeed(p, c.id, 0.25 + r() * 3.75);
    case 6:
      return setClipProps(p, c.id, t.kind === "overlay" ? { opacity: r(), x: r() * 1080 } : t.kind === "effect" ? (c.type === "zoom" ? { amount: 1 + r() * 4 } : { grade: "warm" }) : t.kind === "caption" ? { label: "x" } : { volume: r() * 4, fade_in: r() * 2, fade_out: r() * 2, ...(t.kind === "video" ? { crop: { zoom: 1 + r() * 3, x: r(), y: r() } } : {}) });
    case 7:
      return insertMedia(p, ["m1", "m2", "m3"][Math.floor(r() * 3)], at).project;
    case 8:
      return insertMedia(p, r() < 0.5 ? "m2" : "m1", at, "photos").project;
    case 9:
      return setTrackFlag(p, t.id, ["muted", "hidden", "locked"][Math.floor(r() * 3)] as "muted", r() < 0.5);
    default:
      return moveClip(p, clips.find((x) => x.t.kind !== "video")?.c.id ?? c.id, at).project;
  }
}

function trackEdit(p: Project, r: () => number, _t: Project["tracks"][number], c: Project["tracks"][number]["clips"][number], at: number): Project {
  if (c.type === "trackfx" && r() < 0.6) {
    const effects = ["glow", "spark", "aura", "energy"] as const;
    const points = ["palm", "index_tip", "fingertips", "face", "body", "wrist"] as const;
    return setClipProps(p, c.id, r() < 0.5
      ? { effect: effects[Math.floor(r() * 4)], point: points[Math.floor(r() * 6)], hand: (["left", "right", "any"] as const)[Math.floor(r() * 3)] }
      : { size: r() * 5, smooth: r() * 1.4 - 0.2, intensity: r() * 1.3, color: r() < 0.5 ? "#33CCFF" : "", fade_in: r() * 2, fade_out: r() * 2 });
  }
  const effects = ["glow", "spark", "aura", "energy", "clip"] as const;
  const effect = effects[Math.floor(r() * 5)];
  return addTrackFx(p, effect, at, { media: effect === "clip" ? (r() < 0.5 ? "m2" : "m1") : undefined, seconds: 0.5 + r() * 3 }).project;
}

function brollEdit(p: Project, r: () => number, t: Project["tracks"][number], c: Project["tracks"][number]["clips"][number], at: number): Project {
  const media = r() < 0.5 ? p.media.find((m) => m.id === "m2")! : p.media.find((m) => m.id === "m1")!;
  const sources: BrollMeta["source"][] = ["library", "pexels", "pixabay", "ai", "file"];
  const meta: BrollMeta = {
    source: sources[Math.floor(r() * sources.length)], kind: media.kind === "video" ? "video" : "image", prompt: "a cup of coffee", search: "coffee cup",
    style: r() < 0.5 ? "realistic" : "cartoon", ai_generated: r() < 0.3, credit: r() < 0.3 ? "Photo by Ana on Pexels (https://www.pexels.com/photo/1/)" : undefined,
  };
  if (t.kind === "overlay" && r() < 0.6) return r() < 0.7 ? replaceBroll(p, c.id, media, meta) : setBrollRequest(p, c.id, { search: "jeepney", style: "anime" });
  return addBroll(p, media, meta, at, 0.5 + r() * 4, (["full", "top", "center"] as const)[Math.floor(r() * 3)]).project;
}

function phase2Edit(p: Project, r: () => number, pick: number, t: Project["tracks"][number], c: Project["tracks"][number]["clips"][number], at: number): Project {
  const fx = (["shake", "flash", "dip", "glitch", "whip"] as const)[Math.floor(r() * 5)];
  const caps = p.tracks.filter((x) => x.kind === "caption").flatMap((x) => x.clips);
  const cap = caps[Math.floor(r() * caps.length)];
  switch (pick) {
    case 11:
      return addFx(p, fx, at, r()).project;
    case 12:
      return addTransition(p, fx, at, r()).project;
    case 13:
      return r() < 0.5 ? addZoom(p, r() < 0.5 ? "punch" : "smooth", at).project : addGrade(p, "orange_teal", t.kind === "video" ? c.id : undefined, r()).project;
    case 14:
      return t.kind === "video" ? speedRamp(p, c.id, (["speed_up", "slow_down", "bullet", "montage"] as const)[Math.floor(r() * 4)]) : setAudioSettings(p, { ducking: r(), denoise: r(), normalize: r() < 0.5 });
    case 15:
      if (!cap) return addCaption(p, at, "Kumusta mga kaibigan").project;
      return editWordText(p, cap.id, Math.floor(r() * cap.words!.length), r() < 0.2 ? "" : r() < 0.5 ? "GCash na" : "salamat");
    case 16:
      return cap ? setCaptionLook(p, r() < 0.5 ? "all" : [cap.id], { style: r() < 0.5 ? "bold_caps" : "one_word", zone: (["auto", "lower", "center", "top"] as const)[Math.floor(r() * 4)], size: r() < 0.3 ? null : 40 + r() * 200 }) : p;
    case 17:
      return cap ? (r() < 0.5 ? toggleHighlight(p, cap.id, 0) : addEmoji(p, cap.id, Math.floor(r() * 9), "🔥")) : p;
    default:
      return r() < 0.5 ? correctCaptions(p, [{ from: "kumusta", to: "Hello" }, { from: "kayo", to: "kayong lahat" }]).project : addCaption(p, at, "Bagong caption dito").project;
  }
}

describe("random edits always give a project the engine accepts", () => {
  it("300 sequences of 12 edits", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "edits-"));
    const r = rng(20261016);
    const files: string[] = [];
    let applied = 0;
    let refused = 0;
    for (let n = 0; n < 300; n++) {
      let p = sample();
      for (let k = 0; k < 12; k++) {
        try {
          p = randomEdit(p, r);
          applied++;
        } catch (e) {
          if (!(e instanceof EditError)) throw e; // only friendly "not allowed" errors are expected
          refused++;
        }
      }
      const file = path.join(dir, `p${n}.json`);
      fs.writeFileSync(file, JSON.stringify(p));
      files.push(file);
    }
    const out = execFileSync(python, ["-c", `
import json, sys
from autoedit.project import validate_project
bad = {}
for f in sys.argv[1:]:
    problems = validate_project(json.load(open(f, encoding="utf-8")))
    if problems:
        bad[f] = problems[:3]
print(json.dumps(bad))`, ...files], { cwd: repo, encoding: "utf-8", maxBuffer: 1 << 24 });
    expect(JSON.parse(out)).toEqual({});
    expect(applied).toBeGreaterThan(2500);
    expect(refused).toBeLessThan(1100);
  }, 120_000);
});
