// Effects, transitions, colour grades, speed ramps and the project's sound settings.
// All of them become normal clips (or settings) the engine renders; nothing is baked in.
import { EditError, allIds, clipEnd, clone, isMain, mainTrack, mustFind, newId, placeClip, projectDuration, r4, setSpeed, splitClip, speedOf } from "./edit";
import type { Clip, FxEffect, Project } from "./types";

export const FX_INFO: Record<FxEffect, { label: string; tl: string; seconds: number }> = {
  shake: { label: "Shake", tl: "Yanig", seconds: 0.6 },
  flash: { label: "Flash", tl: "Kislap", seconds: 0.3 },
  dip: { label: "Dip to black", tl: "Dilim", seconds: 0.5 },
  glitch: { label: "Glitch", tl: "Glitch", seconds: 0.4 },
  whip: { label: "Whip blur", tl: "Mabilis na lipat", seconds: 0.3 },
};

export const GRADES = ["natural_clean", "warm", "orange_teal", "high_contrast", "black_and_white", "none"];

const effectTrack = (p: Project) => () => ({ id: newId(p, "effects"), kind: "effect" as const, name: "Effects", clips: [] });

function place(p: Project, clip: Clip) {
  return placeClip(p, clip, "effect", effectTrack(p));
}

/** A moment effect (shake, flash...) starting at `at`. */
export function addFx(p: Project, effect: FxEffect, at: number, intensity = 0.6): { project: Project; clipId: string } {
  const id = newId(p, "fx", allIds(p));
  const end = projectDuration(p);
  const start = r4(Math.max(0, Math.min(at, Math.max(0, end - FX_INFO[effect].seconds))));
  const r = place(p, { id, type: "fx", effect, start, duration: FX_INFO[effect].seconds, intensity });
  return { project: r.project, clipId: id };
}

/** The cut between two main clips nearest to t (null if the main video has no cuts). */
export function nearestCut(p: Project, t: number): number | null {
  const clips = [...(mainTrack(p)?.clips ?? [])].sort((a, b) => a.start - b.start);
  let best: number | null = null;
  for (let i = 1; i < clips.length; i++) {
    const cut = clips[i].start;
    if (Math.abs(clipEnd(clips[i - 1]) - cut) > 1e-3) continue; // a gap, not a cut
    if (best === null || Math.abs(cut - t) < Math.abs(best - t)) best = cut;
  }
  return best;
}

/** A transition: an effect centred on the cut nearest to `at`. */
export function addTransition(p: Project, effect: FxEffect, at: number, intensity = 0.7): { project: Project; clipId: string; cut: number } {
  const cut = nearestCut(p, at);
  if (cut === null) throw new EditError("There is no cut in the main video yet. Split it first (S), then add a transition.");
  const d = FX_INFO[effect].seconds;
  const id = newId(p, "tr", allIds(p));
  const r = place(p, { id, type: "fx", effect, start: r4(Math.max(0, cut - d / 2)), duration: d, intensity, label: `${FX_INFO[effect].label} transition` });
  return { project: r.project, clipId: id, cut };
}

/** A zoom: "punch" jumps in, "smooth" grows over a second. On the clip under the playhead. */
export function addZoom(p: Project, kind: "punch" | "smooth", at: number): { project: Project; clipId: string } {
  const host = mainTrack(p)?.clips.find((c) => at >= c.start && at < clipEnd(c));
  const start = host ? Math.max(host.start, at) : at;
  const duration = r4(Math.max(0.2, Math.min(kind === "punch" ? 1.5 : 2.5, host ? clipEnd(host) - start : 2)));
  const id = newId(p, "z", allIds(p));
  const clip: Clip = { id, type: "zoom", start: r4(start), duration, amount: kind === "punch" ? 1.25 : 1.35, anchor_y: 0.4 };
  if (kind === "smooth") clip.ease = Math.min(1, duration);
  const r = place(p, clip);
  return { project: r.project, clipId: id };
}

/** A colour grade over one main clip (or the whole video when `clipId` is undefined). */
export function addGrade(p: Project, grade: string, clipId?: string, intensity = 1): { project: Project; clipId: string } {
  if (!GRADES.includes(grade)) throw new EditError(`Unknown colour look '${grade}'.`);
  let start = 0;
  let duration = projectDuration(p);
  if (clipId) {
    const { clip } = mustFind(p, clipId);
    start = clip.start;
    duration = clip.duration;
  }
  if (duration <= 0) throw new EditError("Add a video first.");
  const id = newId(p, "g", allIds(p));
  const clip: Clip = { id, type: "grade", grade, start: r4(start), duration: r4(duration) };
  if (intensity < 1) clip.intensity = intensity;
  const r = place(p, clip);
  return { project: r.project, clipId: id };
}

export const RAMPS: Record<string, { label: string; speeds: number[] }> = {
  speed_up: { label: "Speed up (1x → 2.5x)", speeds: [1, 1.6, 2.5] },
  slow_down: { label: "Slow down (2.5x → 1x)", speeds: [2.5, 1.6, 1] },
  bullet: { label: "Bullet time (1x → 0.4x → 1x)", speeds: [1, 0.4, 1] },
  montage: { label: "Montage (2x → 1x → 2x)", speeds: [2, 1, 2] },
};

/**
 * A speed ramp on a main clip: the clip is split into equal parts of its source, each with
 * its own speed (each part is a normal clip you can change later).
 */
export function speedRamp(p: Project, id: string, ramp: keyof typeof RAMPS): Project {
  const { track, clip } = mustFind(p, id);
  if (!isMain(track) || clip.type !== "video") throw new EditError("Speed ramps are for clips of the main video.");
  const speeds = RAMPS[ramp].speeds;
  const length = (clip.out ?? 0) - (clip.in ?? 0);
  if (length / speeds.length < 0.2) throw new EditError("This clip is too short for a speed ramp.");
  let q = p;
  let current = id;
  const ids = [id];
  for (let k = 1; k < speeds.length; k++) {
    const c = mustFind(q, current).clip;
    const at = c.start + (length / speeds.length) / speedOf(c);
    const r = splitClip(q, current, at);
    q = r.project;
    current = r.rightId;
    ids.push(current);
  }
  ids.forEach((cid, k) => (q = setSpeed(q, cid, speeds[k])));
  return q;
}

export interface AudioSettings {
  normalize?: boolean;
  loudness?: number;
  ducking?: number;
  denoise?: number;
}

/** The project's sound settings (loudness, music ducking, noise reduction). */
export function setAudioSettings(p: Project, patch: AudioSettings): Project {
  const q = clone(p);
  const a = { ...(q.settings.audio ?? {}) };
  if (patch.normalize !== undefined) a.normalize = patch.normalize;
  if (patch.loudness !== undefined) a.loudness = Math.min(-5, Math.max(-70, patch.loudness));
  for (const k of ["ducking", "denoise"] as const) {
    if (patch[k] === undefined) continue;
    const v = r4(Math.min(1, Math.max(0, patch[k]!)));
    if (v > 0) a[k] = v;
    else delete a[k];
  }
  return { ...q, settings: { ...q.settings, audio: a } };
}
