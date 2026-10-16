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
  switch (Math.floor(r() * 11)) {
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
