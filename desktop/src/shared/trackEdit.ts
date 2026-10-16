// Tracked effects on the timeline: adding one, what to follow, and whether the video has been
// tracked yet. Every result is a valid project (the engine's validator checks them in tests).
import { EditError, allIds, clipEnd, mainTrack, newId, placeClip, projectDuration, r4 } from "./edit";
import { FINGERTIPS, coverage, pickHand } from "./tracking";
import type { Clip, Project, TrackEffect, TrackHand, TrackPointKind } from "./types";

export const TRACK_FX: Record<TrackEffect, { label: string; tl: string; point: TrackPointKind; color: string; seconds: number }> = {
  glow: { label: "Glow", tl: "Liwanag", point: "index_tip", color: "#ffe08a", seconds: 2 },
  spark: { label: "Sparks", tl: "Kislap-kislap", point: "palm", color: "#ffb347", seconds: 2 },
  aura: { label: "Aura", tl: "Aura", point: "body", color: "#58c8ff", seconds: 3 },
  energy: { label: "Energy rings", tl: "Enerhiya", point: "palm", color: "#7aa8ff", seconds: 2 },
  clip: { label: "Your own clip", tl: "Sarili mong clip", point: "palm", color: "#ffffff", seconds: 2 },
};

export const POINTS: { id: TrackPointKind; label: string; tl: string; hand: boolean }[] = [
  { id: "palm", label: "Palm", tl: "Palad", hand: true },
  { id: "index_tip", label: "Index fingertip", tl: "Dulo ng hintuturo", hand: true },
  { id: "thumb_tip", label: "Thumb tip", tl: "Dulo ng hinlalaki", hand: true },
  { id: "middle_tip", label: "Middle fingertip", tl: "Dulo ng gitnang daliri", hand: true },
  { id: "ring_tip", label: "Ring fingertip", tl: "Dulo ng palasingsingan", hand: true },
  { id: "pinky_tip", label: "Little fingertip", tl: "Dulo ng kalingkingan", hand: true },
  { id: "fingertips", label: "All five fingertips", tl: "Lahat ng dulo ng daliri", hand: true },
  { id: "wrist", label: "Wrist", tl: "Pulso", hand: true },
  { id: "face", label: "Face", tl: "Mukha", hand: false },
  { id: "body", label: "Body", tl: "Katawan", hand: false },
];

export const HAND_LABELS: Record<TrackHand, string> = { any: "Whichever is found", left: "Left hand", right: "Right hand" };

/** A tracked effect starting at `at`. `media`: the file for "Your own clip". */
export function addTrackFx(
  p: Project,
  effect: TrackEffect,
  at: number,
  opts: { media?: string; point?: TrackPointKind; hand?: TrackHand; seconds?: number } = {},
): { project: Project; clipId: string } {
  if (effect === "clip") {
    const m = p.media.find((x) => x.id === opts.media);
    if (!m || m.kind === "audio") throw new EditError("Choose a video or picture file for your own effect clip.");
  }
  const info = TRACK_FX[effect];
  const total = projectDuration(p);
  const seconds = Math.max(0.5, opts.seconds ?? info.seconds);
  const start = r4(Math.max(0, Math.min(at, Math.max(0, total - 0.5))));
  const duration = r4(Math.max(0.5, Math.min(seconds, Math.max(0.5, total - start))));
  const id = newId(p, "k", allIds(p));
  const clip: Clip = {
    id, type: "trackfx", start, duration, effect, point: opts.point ?? info.point, hand: opts.hand ?? "any", intensity: 0.8, smooth: 0.5,
  };
  if (effect === "clip") {
    clip.media = opts.media;
    clip.blend = "screen";
  }
  const n = p.tracks.filter((t) => t.kind === "effect").length;
  const placed = placeClip(p, clip, "effect", () => ({ id: newId(p, "tracked"), kind: "effect", name: n ? `Tracked ${n + 1}` : "Tracked", clips: [] }));
  return { project: placed.project, clipId: id };
}

export interface TrackState {
  /** The main video under the effect has tracked points saved in the project. */
  tracked: boolean;
  /** The media id the points belong to (the main video under the start of the effect). */
  mediaId: string | null;
  /** 0-1: how much of the effect's moment the followed point was found (null if not tracked). */
  found: number | null;
  /** The stored point names the effect follows that exist in the track. */
  names: string[];
}

/** Whether a tracked effect has something to follow, and how well the point was found there. */
export function trackState(p: Project, clip: Clip): TrackState {
  const none: TrackState = { tracked: false, mediaId: null, found: null, names: [] };
  const hosts = (mainTrack(p)?.clips ?? []).filter((c) => c.type === "video" && c.media && c.start < clipEnd(clip) && clipEnd(c) > clip.start);
  const host = hosts[0];
  if (!host?.media) return none;
  const track = p.tracking?.[host.media];
  if (!track) return { ...none, mediaId: host.media };
  let t0 = Infinity;
  let t1 = -Infinity;
  for (const c of hosts.filter((h) => h.media === host.media)) {
    const a = Math.max(clip.start, c.start);
    const b = Math.min(clipEnd(clip), clipEnd(c));
    if (b <= a) continue;
    const sp = c.speed ?? 1;
    t0 = Math.min(t0, (c.in ?? 0) + (a - c.start) * sp);
    t1 = Math.max(t1, (c.in ?? 0) + (b - c.start) * sp);
  }
  if (!(t1 > t0)) return { tracked: true, mediaId: host.media, found: null, names: [] };
  const point = clip.point ?? "palm";
  const hand = clip.hand ?? "any";
  // The same choice as the engine (autoedit/trackfx.py point_names): one hand, picked by who is found most.
  let names: string[];
  if (point === "face" || point === "body") names = [point];
  else {
    const picked = pickHand(track, hand, point === "fingertips" ? "index_tip" : point, t0, t1);
    names = point === "fingertips" ? FINGERTIPS.map((f) => `${picked.split("_")[0]}_${f}`) : [picked];
  }
  const stored = names.filter((n) => track.points[n]);
  return { tracked: true, mediaId: host.media, found: coverage(track, stored, t0, t1), names: stored };
}

/** Tracked effects that have nothing to follow yet (no points saved for their video). */
export function untrackedEffects(p: Project): Clip[] {
  const out: Clip[] = [];
  for (const t of p.tracks) {
    if (t.kind !== "effect" || t.hidden) continue;
    for (const c of t.clips) if (c.type === "trackfx" && !trackState(p, c).tracked) out.push(c);
  }
  return out;
}

export function trackfxLabel(clip: Clip): string {
  const info = TRACK_FX[(clip.effect as TrackEffect) ?? "glow"];
  const point = POINTS.find((x) => x.id === (clip.point ?? "palm"));
  const where = point ? (point.hand && clip.hand && clip.hand !== "any" ? `${clip.hand} ${point.label.toLowerCase()}` : point.label.toLowerCase()) : "";
  return `${info?.label ?? "Effect"} · ${where}`;
}
