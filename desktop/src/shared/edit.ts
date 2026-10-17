// Timeline editing operations. Pure functions: each takes a Project and returns a new one
// (the input is never changed), so undo/redo is simply a list of projects.
//
// The rules mirror the engine (autoedit/project.py), so every result renders:
//  - clips on one track never overlap; when a move would overlap, the clip goes to another
//    track of the same kind (a new one if needed);
//  - a clip that plays part of a file keeps out - in = duration x speed;
//  - every clip is at least one frame long.
//
// The main video track is "magnetic" (like CapCut): deleting, trimming or changing the speed
// of a main clip moves everything after it, so no gaps appear. Clips on the other tracks
// follow the main video ("linked"): captions, effects, photos and sounds inside a main clip
// move with it when it is reordered, are cut when that part of the video is cut, and are
// squeezed/stretched with its speed. Locked tracks never change.
import type { Clip, Media, Project, Track, Word } from "./types";

export class EditError extends Error {}

export const MIN_SPEED = 0.25;
export const MAX_SPEED = 4;
export const PROJECT_VERSION = 2;
const EPS = 1e-6;
/** Clips closer than this (seconds) are touching, not overlapping: the same slack as the engine's validator (TIME_TOLERANCE in autoedit/project.py). */
export const TOUCH = 0.002;

/** Times are kept to 0.1 ms, so repeated edits do not pile up rounding noise. */
export const r4 = (x: number): number => Math.round(x * 1e4) / 1e4;

export const clipEnd = (c: Clip): number => c.start + c.duration;
export const speedOf = (c: Clip): number => c.speed ?? 1;
export const hasSource = (c: Clip): boolean => c.in !== undefined && c.out !== undefined;
export const minDuration = (p: Project): number => 1 / p.settings.fps;
export const isMain = (t: Track): boolean => t.kind === "video";

export interface Found {
  track: Track;
  clip: Clip;
  ti: number;
  ci: number;
}

export function findClip(p: Project, id: string): Found | null {
  for (let ti = 0; ti < p.tracks.length; ti++) {
    const ci = p.tracks[ti].clips.findIndex((c) => c.id === id);
    if (ci >= 0) return { track: p.tracks[ti], clip: p.tracks[ti].clips[ci], ti, ci };
  }
  return null;
}

export function mustFind(p: Project, id: string): Found {
  const f = findClip(p, id);
  if (!f) throw new EditError("That clip is no longer on the timeline.");
  if (f.track.locked) throw new EditError(`The ${f.track.name ?? f.track.id} track is locked. Unlock it first.`);
  if (f.clip.locked) throw new EditError("This clip is locked. Unlock it first.");
  return f;
}

export function mainTrack(p: Project): Track | undefined {
  return p.tracks.find(isMain);
}

export function projectDuration(p: Project): number {
  let end = 0;
  for (const t of p.tracks) for (const c of t.clips) end = Math.max(end, clipEnd(c));
  return end;
}

function mediaOf(p: Project, c: Clip): Media | undefined {
  return c.media ? p.media.find((m) => m.id === c.media) : undefined;
}

/** How far the clip's source lets it reach (seconds of timeline), or Infinity for stills. */
function sourceRoom(p: Project, c: Clip): { before: number; after: number } {
  const m = mediaOf(p, c);
  if (!hasSource(c) || !m || m.kind === "image" || !(m.duration > 0)) return { before: Infinity, after: Infinity };
  const sp = speedOf(c);
  return { before: (c.in ?? 0) / sp, after: Math.max(0, m.duration - (c.out ?? 0)) / sp };
}

export function allIds(p: Project): Set<string> {
  const ids = new Set<string>();
  for (const t of p.tracks) {
    ids.add(t.id);
    for (const c of t.clips) ids.add(c.id);
  }
  for (const m of p.media) ids.add(m.id);
  return ids;
}

export function newId(p: Project, prefix: string, taken: Set<string> = allIds(p)): string {
  let n = 1;
  while (taken.has(`${prefix}${n}`)) n++;
  const id = `${prefix}${n}`;
  taken.add(id);
  return id;
}

export function clone(p: Project): Project {
  return { ...structuredClone(p), version: Math.max(p.version, PROJECT_VERSION) };
}

// ---------------------------------------------------------------- caption words

function mid(w: Word): number {
  return (w.start + w.end) / 2;
}

function tidyWords(words: Word[], length: number): Word[] {
  let last = 0;
  return words.map((w) => {
    const start = r4(Math.min(Math.max(w.start, last), length));
    const end = r4(Math.min(Math.max(w.end, start), length));
    last = start;
    return { ...w, start, end };
  });
}

/** Words (clip-local times) whose middle is in [a, b), moved to start at 0. */
export function wordsBetween(words: Word[], a: number, b: number): Word[] {
  return tidyWords(
    words.filter((w) => mid(w) >= a - EPS && mid(w) < b - EPS).map((w) => ({ ...w, start: w.start - a, end: w.end - a })),
    b - a,
  );
}

/** Words with [a, b) taken out of the middle (later words move back by b - a). */
function wordsWithout(words: Word[], a: number, b: number, length: number): Word[] {
  const d = b - a;
  return tidyWords(
    words
      .filter((w) => mid(w) < a - EPS || mid(w) >= b - EPS)
      .map((w) => (mid(w) >= b - EPS ? { ...w, start: w.start - d, end: w.end - d } : w)),
    length,
  );
}

function wordsScaled(words: Word[], f: number, length: number): Word[] {
  return tidyWords(words.map((w) => ({ ...w, start: w.start * f, end: w.end * f })), length);
}

// ---------------------------------------------------------------- clip pieces

/** Keep fades inside the clip (they may not add up to more than its length). */
function fitFades(c: Clip): Clip {
  const fi = c.fade_in ?? 0;
  const fo = c.fade_out ?? 0;
  if (fi + fo <= c.duration + EPS) return c;
  const k = c.duration / (fi + fo);
  const out = { ...c };
  if (c.fade_in !== undefined) out.fade_in = r4(fi * k * 0.999);
  if (c.fade_out !== undefined) out.fade_out = r4(fo * k * 0.999);
  return out;
}

/** The part of `c` from timeline time a to b (a < b, both inside the clip), placed at `at`. */
function piece(c: Clip, a: number, b: number, at: number, id: string): Clip {
  const out: Clip = { ...c, id, start: r4(at), duration: r4(b - a) };
  if (hasSource(c)) {
    const sp = speedOf(c);
    out.in = r4((c.in ?? 0) + (a - c.start) * sp);
    out.out = r4(out.in + out.duration * sp);
  }
  if (c.words) out.words = wordsBetween(c.words, a - c.start, b - c.start);
  if (a > c.start + EPS) delete out.fade_in;
  if (b < clipEnd(c) - EPS) delete out.fade_out;
  return fitFades(out);
}

/**
 * Take the timeline range [a, b) out of a (non-main) clip; clips after it move back.
 * Returns the remaining clip(s): none, one, or two pieces (a media clip that spans the range
 * keeps its content in sync, so it becomes two clips).
 */
function cutFromClip(c: Clip, a: number, b: number, taken: Set<string>, p: Project): Clip[] {
  const s = c.start;
  const e = clipEnd(c);
  const d = b - a;
  if (e <= a + EPS) return [c];
  if (s >= b - EPS) return [{ ...c, start: r4(s - d) }];
  if (s >= a - EPS && e <= b + EPS) return [];
  if (s < a && e > b) {
    if (hasSource(c)) return [piece(c, s, a, s, c.id), piece(c, b, e, a, newId(p, `${c.id}_`, taken))];
    const out: Clip = { ...c, duration: r4(c.duration - d) };
    if (c.words) out.words = wordsWithout(c.words, a - s, b - s, out.duration);
    return [fitFades(out)];
  }
  if (s < a) return [piece(c, s, a, s, c.id)]; // the range cuts off the end
  return [piece(c, b, e, a, c.id)]; // the range cuts off the start
}

function cutRange(track: Track, a: number, b: number, taken: Set<string>, p: Project): Track {
  if (track.locked || isMain(track) || b - a <= EPS) return track;
  return { ...track, clips: track.clips.flatMap((c) => (c.locked ? [c] : cutFromClip(c, a, b, taken, p))) };
}

function openSpace(track: Track, at: number, d: number): Track {
  if (track.locked || isMain(track) || Math.abs(d) <= EPS) return track;
  return { ...track, clips: track.clips.map((c) => (c.start >= at - EPS && !c.locked ? { ...c, start: r4(c.start + d) } : c)) };
}

/**
 * Remove what cannot be shown: captions cut down to no words, and slivers shorter than a
 * millisecond (left over when a cut lands a hair from a clip's edge; far less than a frame).
 */
function dropEmptyCaptions(p: Project): Project {
  return {
    ...p,
    tracks: p.tracks.map((t) => ({
      ...t,
      clips: t.clips.filter((c) => c.duration >= 0.001 && (t.kind !== "caption" || (c.words?.length ?? 0) > 0)),
    })),
  };
}

/** Move clips that now overlap onto extra tracks of the same kind (first fit). */
export function resolveOverlaps(p: Project): Project {
  p = dropEmptyCaptions(p);
  const tracks: Track[] = [];
  const taken = allIds(p);
  for (const track of p.tracks) {
    if (isMain(track)) {
      tracks.push(track);
      continue;
    }
    const lanes: Clip[][] = [];
    for (const c of [...track.clips].sort((x, y) => x.start - y.start)) {
      const lane = lanes.find((l) => c.start >= clipEnd(l[l.length - 1]) - TOUCH);
      if (lane) lane.push(c);
      else lanes.push([c]);
    }
    tracks.push({ ...track, clips: lanes[0] ?? [] });
    for (const extra of lanes.slice(1)) {
      tracks.push({ ...newTrackLike(track, taken), clips: extra });
    }
  }
  return { ...p, tracks };
}

function newTrackLike(track: Track, taken: Set<string>): Track {
  const id = (() => {
    let n = 2;
    while (taken.has(`${track.id}_${n}`)) n++;
    taken.add(`${track.id}_${n}`);
    return `${track.id}_${n}`;
  })();
  const t: Track = { id, kind: track.kind, name: `${track.name ?? track.id} ${id.split("_").pop()}`, clips: [] };
  if (track.role) t.role = track.role;
  return t;
}

// ---------------------------------------------------------------- main track helpers

function withMain(p: Project, fn: (clips: Clip[]) => Clip[]): Project {
  return { ...p, tracks: p.tracks.map((t) => (isMain(t) ? { ...t, clips: fn(t.clips) } : t)) };
}

function shiftMainAfter(clips: Clip[], at: number, d: number, except?: string): Clip[] {
  return clips.map((c) => (c.id !== except && c.start >= at - EPS ? { ...c, start: r4(c.start + d) } : c));
}

function linked(p: Project, fn: (t: Track) => Track): Project {
  return { ...p, tracks: p.tracks.map((t) => (isMain(t) ? t : fn(t))) };
}

// ---------------------------------------------------------------- operations

/** Split one clip at timeline time t. Returns the new project and the id of the right part. */
export function splitClip(p: Project, id: string, t: number): { project: Project; rightId: string } {
  const { clip, ti, ci } = mustFind(p, id);
  const min = minDuration(p);
  if (t < clip.start + min - EPS || t > clipEnd(clip) - min + EPS) {
    throw new EditError("Move the playhead inside the clip (at least one frame from its edges) to split it.");
  }
  const q = clone(p);
  const taken = allIds(q);
  const rightId = newId(q, `${clip.id}_`, taken);
  const left = piece(clip, clip.start, t, clip.start, clip.id);
  const right = piece(clip, t, clipEnd(clip), t, rightId);
  if (clip.words && (!left.words?.length || !right.words?.length)) {
    throw new EditError("There are no words on one side of the split. Split between two words.");
  }
  q.tracks[ti].clips.splice(ci, 1, left, right);
  return { project: q, rightId };
}

/** Split every unlocked clip under the playhead (or only `ids`). */
export function splitAt(p: Project, t: number, ids?: string[]): Project {
  let q = p;
  const min = minDuration(p);
  for (const track of p.tracks) {
    if (track.locked) continue;
    for (const c of track.clips) {
      if (c.locked || (ids && !ids.includes(c.id))) continue;
      if (t < c.start + min - EPS || t > clipEnd(c) - min + EPS) continue;
      try {
        q = splitClip(q, c.id, t).project;
      } catch (e) {
        if (!(e instanceof EditError)) throw e; // e.g. a caption with no word on one side
      }
    }
  }
  if (q === p) throw new EditError("There is no clip under the playhead to split.");
  return q;
}

/** Delete clips. Main-track clips close their gap (ripple) and take linked clips with them. */
export function deleteClips(p: Project, ids: string[], ripple = true): Project {
  if (!ids.length) return p;
  const found = ids.map((id) => mustFind(p, id));
  let q = clone(p);
  const taken = allIds(q);
  const others = new Set(found.filter((f) => !isMain(f.track)).map((f) => f.clip.id));
  q = { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.filter((c) => !others.has(c.id)) })) };
  const mains = found.filter((f) => isMain(f.track)).map((f) => f.clip).sort((a, b) => b.start - a.start);
  for (const c of mains) {
    const a = c.start;
    const b = clipEnd(c);
    q = withMain(q, (clips) => {
      const rest = clips.filter((x) => x.id !== c.id);
      return ripple ? shiftMainAfter(rest, b, -(b - a)) : rest;
    });
    if (ripple) q = linked(q, (t) => cutRange(t, a, b, taken, q));
  }
  return resolveOverlaps(q);
}

/**
 * Trim a clip's start or end to timeline time t (clamped to what is allowed).
 * Main clips ripple: the clip keeps its start, later clips move.
 */
export function trimClip(p: Project, id: string, edge: "start" | "end", t: number): Project {
  const { track, clip } = mustFind(p, id);
  const min = minDuration(p);
  const room = sourceRoom(p, clip);
  const sp = speedOf(clip);
  const s = clip.start;
  const e = clipEnd(clip);
  let q = clone(p);
  const taken = allIds(q);
  const replace = (next: Clip) => {
    q = { ...q, tracks: q.tracks.map((tr) => ({ ...tr, clips: tr.clips.map((c) => (c.id === id ? fitFades(next) : c)) })) };
  };

  if (!isMain(track)) {
    const siblings = track.clips.filter((c) => c.id !== id);
    if (edge === "start") {
      const prevEnd = Math.max(0, ...siblings.filter((c) => clipEnd(c) <= s + TOUCH).map(clipEnd));
      const t2 = r4(Math.min(Math.max(t, prevEnd, s - room.before), e - min));
      if (Math.abs(t2 - s) <= EPS) return p;
      const next: Clip = { ...clip, start: t2, duration: r4(e - t2) };
      if (hasSource(clip)) next.in = r4((clip.in ?? 0) + (t2 - s) * sp);
      if (clip.words) next.words = tidyWords(clip.words.map((w) => ({ ...w, start: w.start - (t2 - s), end: w.end - (t2 - s) })).filter((w) => mid(w) >= 0), next.duration);
      replace(next);
    } else {
      const nextStart = Math.min(Infinity, ...siblings.filter((c) => c.start >= e - TOUCH).map((c) => c.start));
      const t2 = r4(Math.max(Math.min(t, nextStart, e + room.after), s + min));
      if (Math.abs(t2 - e) <= EPS) return p;
      const next: Clip = { ...clip, duration: r4(t2 - s) };
      if (hasSource(clip)) next.out = r4((clip.in ?? 0) + next.duration * sp);
      if (clip.words) next.words = tidyWords(clip.words.filter((w) => mid(w) < next.duration), next.duration);
      replace(next);
    }
    return resolveOverlaps(q);
  }

  // Main track: ripple.
  if (edge === "start") {
    const d = r4(Math.min(Math.max(t - s, -room.before), clip.duration - min)); // > 0 shortens
    if (Math.abs(d) <= EPS) return p;
    const next: Clip = { ...clip, duration: r4(clip.duration - d) };
    if (hasSource(clip)) next.in = r4((clip.in ?? 0) + d * sp);
    replace(next);
    q = withMain(q, (clips) => shiftMainAfter(clips, e, -d, id));
    q = linked(q, (tr) => (d > 0 ? cutRange(tr, s, s + d, taken, q) : openSpace(tr, s, -d)));
  } else {
    const t2 = r4(Math.max(Math.min(t, e + room.after), s + min));
    const d = r4(t2 - e); // > 0 lengthens
    if (Math.abs(d) <= EPS) return p;
    const next: Clip = { ...clip, duration: r4(clip.duration + d) };
    if (hasSource(clip)) next.out = r4((clip.in ?? 0) + next.duration * sp);
    replace(next);
    q = withMain(q, (clips) => shiftMainAfter(clips, e, d, id));
    q = linked(q, (tr) => (d < 0 ? cutRange(tr, t2, e, taken, q) : openSpace(tr, e, d)));
  }
  return resolveOverlaps(q);
}

/**
 * Move a clip (not on the main track) to a new start, optionally onto another track of the
 * same kind. If it would overlap, it goes to another track of that kind (a new one if needed).
 */
export function moveClip(p: Project, id: string, newStart: number, targetTrackId?: string): { project: Project; trackId: string } {
  const { track, clip } = mustFind(p, id);
  if (isMain(track)) throw new EditError("Use moveMainClip to reorder the main video.");
  const target = targetTrackId ? p.tracks.find((t) => t.id === targetTrackId) : track;
  if (!target || target.kind !== track.kind || isMain(target)) {
    throw new EditError("A clip can only move to a track of the same kind.");
  }
  if (target.locked) throw new EditError(`The ${target.name ?? target.id} track is locked.`);
  const start = r4(Math.max(0, newStart));
  const moved: Clip = { ...clip, start };
  let q = clone(p);
  q = { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.filter((c) => c.id !== id) })) };
  const fits = (t: Track) => !t.locked && t.clips.every((c) => clipEnd(c) <= start + TOUCH || c.start >= clipEnd(moved) - TOUCH);
  const sameKind = q.tracks.filter((t) => t.kind === track.kind && !isMain(t));
  let dest = q.tracks.find((t) => t.id === target.id)!;
  if (!fits(dest)) {
    const other = sameKind.find((t) => t.id !== dest.id && fits(t) && (track.kind !== "audio" || t.role === dest.role));
    if (other) dest = other;
    else {
      const fresh = newTrackLike(dest, allIds(q));
      const at = q.tracks.findIndex((t) => t.id === dest.id);
      q = { ...q, tracks: [...q.tracks.slice(0, at + 1), fresh, ...q.tracks.slice(at + 1)] };
      dest = fresh;
    }
  }
  const destId = dest.id;
  q = { ...q, tracks: q.tracks.map((t) => (t.id === destId ? { ...t, clips: [...t.clips, moved].sort((a, b) => a.start - b.start) } : t)) };
  return { project: q, trackId: destId };
}

/**
 * Reorder the main video: put clip `id` at position `toIndex` (0 = first). The main track is
 * packed with no gaps; clips on other tracks that sat inside a main clip move with it.
 */
export function moveMainClip(p: Project, id: string, toIndex: number): Project {
  const { track } = mustFind(p, id);
  if (!isMain(track)) throw new EditError("Only main video clips can be reordered.");
  const order = [...track.clips].sort((a, b) => a.start - b.start);
  const from = order.findIndex((c) => c.id === id);
  const to = Math.max(0, Math.min(order.length - 1, toIndex));
  if (from === to) return p;
  const next = [...order];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  let cursor = order[0].start;
  const delta = new Map<string, number>();
  const packed = next.map((c) => {
    const placed = { ...c, start: r4(cursor) };
    delta.set(c.id, placed.start - c.start);
    cursor += c.duration;
    return placed;
  });
  let q = clone(p);
  q = withMain(q, () => packed);
  q = linked(q, (t) =>
    t.locked
      ? t
      : {
          ...t,
          clips: t.clips.map((c) => {
            const host = order.find((m) => c.start >= m.start - EPS && clipEnd(c) <= clipEnd(m) + EPS);
            const d = host ? delta.get(host.id) ?? 0 : 0;
            return Math.abs(d) > EPS ? { ...c, start: r4(c.start + d) } : c;
          }),
        },
  );
  return resolveOverlaps(q);
}

/** Change a clip's speed (0.25-4). Main clips ripple and squeeze/stretch their linked clips. */
export function setSpeed(p: Project, id: string, speed: number): Project {
  const { track, clip } = mustFind(p, id);
  if (!hasSource(clip)) throw new EditError("Only video and sound clips have a speed.");
  const sp = r4(Math.min(MAX_SPEED, Math.max(MIN_SPEED, speed)));
  const length = (clip.out ?? 0) - (clip.in ?? 0);
  const duration = r4(length / sp);
  if (duration < minDuration(p) - EPS) throw new EditError("At that speed the clip would be shorter than one frame.");
  const s = clip.start;
  const e = clipEnd(clip);
  const changed: Clip = fitFades({ ...clip, speed: sp, duration, out: r4((clip.in ?? 0) + duration * sp) });
  if (sp === 1) delete changed.speed;
  if (!isMain(track)) {
    const blocked = track.clips.some((c) => c.id !== id && c.start >= e - TOUCH && c.start < s + duration - TOUCH);
    if (blocked) throw new EditError("Not enough room on this track at that speed: move the next clip first.");
    const q = clone(p);
    return { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? changed : c)) })) };
  }
  const f = duration / clip.duration;
  const d = duration - clip.duration;
  let q = clone(p);
  q = withMain(q, (clips) => shiftMainAfter(clips.map((c) => (c.id === id ? changed : c)), e, d, id));
  q = linked(q, (t) =>
    t.locked
      ? t
      : {
          ...t,
          clips: t.clips.map((c) => {
            if (c.start >= e - EPS) return { ...c, start: r4(c.start + d) };
            if (c.start < s - EPS || clipEnd(c) > e + EPS) return c;
            // Inside the main clip: keep its place in the content.
            const start = r4(s + (c.start - s) * f);
            if (hasSource(c)) {
              const room = r4(s + duration - start);
              if (c.duration <= room + EPS) return { ...c, start };
              const cut = { ...c, start, duration: room };
              cut.out = r4((c.in ?? 0) + room * speedOf(c));
              return fitFades(cut);
            }
            const scaled: Clip = { ...c, start, duration: r4(Math.max(c.duration * f, minDuration(p))) };
            if (c.words) scaled.words = wordsScaled(c.words, f, scaled.duration);
            return fitFades(scaled);
          }),
        },
  );
  return resolveOverlaps(q);
}

export type ClipPatch = Partial<
  Pick<Clip, "volume" | "fade_in" | "fade_out" | "opacity" | "crop" | "fit" | "x" | "y" | "width" | "height" | "animation" | "amount" | "anchor_y" | "grade" | "label" | "ease" | "intensity" | "effect" | "point" | "hand" | "size" | "smooth" | "color" | "blend" | "media">
>;

const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

/** Which settings each kind of clip has (the engine's schema refuses others). */
export function allowedProps(track: Track, clip: Clip): Set<keyof ClipPatch> {
  const a = new Set<keyof ClipPatch>(["label"]);
  const add = (...k: (keyof ClipPatch)[]) => k.forEach((x) => a.add(x));
  if (track.kind === "video") {
    add("fit", "crop");
    if (clip.type === "video") add("volume", "fade_in", "fade_out");
  } else if (track.kind === "overlay") add("x", "y", "width", "height", "opacity", "animation");
  else if (track.kind === "audio") add("volume", "fade_in", "fade_out");
  else if (clip.type === "zoom") add("amount", "anchor_y", "ease");
  else if (clip.type === "grade") add("grade", "intensity");
  else if (clip.type === "fx") add("effect", "intensity");
  else if (clip.type === "trackfx") add("effect", "point", "hand", "size", "smooth", "color", "blend", "media", "intensity", "fade_in", "fade_out");
  return a;
}

/** Change clip settings, kept inside the allowed ranges. */
export function setClipProps(p: Project, id: string, patch: ClipPatch): Project {
  const { track, clip } = mustFind(p, id);
  const allowed = allowedProps(track, clip);
  const bad = (Object.keys(patch) as (keyof ClipPatch)[]).filter((k) => !allowed.has(k));
  if (bad.length) throw new EditError(`This clip has no ${bad.join(", ")} setting.`);
  const q = clone(p);
  const fix = (c: Clip): Clip => {
    const n: Clip = { ...c, ...patch };
    if (patch.volume !== undefined) n.volume = r4(clamp(patch.volume, 0, 4));
    if (patch.opacity !== undefined) n.opacity = r4(clamp(patch.opacity, 0, 1));
    if (patch.amount !== undefined) n.amount = r4(clamp(patch.amount, 1, 5));
    if (patch.anchor_y !== undefined) n.anchor_y = r4(clamp(patch.anchor_y, 0, 1));
    if (patch.intensity !== undefined) n.intensity = r4(clamp(patch.intensity, 0, 1));
    if (patch.ease !== undefined) {
      const e = r4(clamp(patch.ease, 0, 3));
      if (e > 0) n.ease = e;
      else delete n.ease;
    }
    if (patch.width !== undefined) n.width = Math.max(1, r4(patch.width));
    if (patch.height !== undefined) n.height = Math.max(1, r4(patch.height));
    for (const k of ["fade_in", "fade_out"] as const) {
      if (patch[k] !== undefined) {
        const other = k === "fade_in" ? n.fade_out ?? 0 : n.fade_in ?? 0;
        const v = r4(clamp(patch[k] ?? 0, 0, Math.max(0, c.duration - other)));
        if (v > 0) n[k] = v;
        else delete n[k];
      }
    }
    if (c.type === "trackfx") {
      if (patch.size !== undefined) n.size = r4(clamp(patch.size, 0.1, 4));
      if (patch.smooth !== undefined) n.smooth = r4(clamp(patch.smooth, 0, 1));
      if (patch.color !== undefined) {
        if (/^#[0-9a-fA-F]{6}$/.test(patch.color)) n.color = patch.color.toLowerCase();
        else delete n.color; // "" or anything else: the effect's own colour
      }
      if (patch.effect !== undefined || patch.media !== undefined) {
        if (n.effect === "clip") {
          const m = p.media.find((x) => x.id === n.media);
          if (!m || m.kind === "audio") throw new EditError("Choose a video or picture file for your own effect clip.");
        } else {
          delete n.media;
          delete n.blend;
        }
      }
    }
    if (patch.crop !== undefined) {
      const zoom = r4(clamp(patch.crop.zoom ?? 1, 1, 4));
      const x = r4(clamp(patch.crop.x ?? 0.5, 0, 1));
      const y = r4(clamp(patch.crop.y ?? 0.5, 0, 1));
      if (zoom === 1 && x === 0.5 && y === 0.5) delete n.crop;
      else n.crop = { zoom, x, y };
    }
    return n;
  };
  return { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? fix(c) : c)) })) };
}

export function setTrackFlag(p: Project, trackId: string, flag: "muted" | "hidden" | "locked", value: boolean): Project {
  const q = clone(p);
  return {
    ...q,
    tracks: q.tracks.map((t) => {
      if (t.id !== trackId) return t;
      const n = { ...t };
      if (value) n[flag] = true;
      else delete n[flag];
      return n;
    }),
  };
}

/**
 * Put a new clip on the first unlocked track of `kind` (creating one if there is none). If it
 * would overlap a clip there, it goes on another track of that kind (a new one if needed).
 */
export function placeClip(p: Project, clip: Clip, kind: Track["kind"], newTrack: () => Track): { project: Project; trackId: string } {
  let q = clone(p);
  let track = q.tracks.find((t) => t.kind === kind && !t.locked);
  if (!track) {
    if (q.tracks.some((t) => t.kind === kind)) throw new EditError(`Every ${kind} track is locked. Unlock one first.`);
    track = newTrack();
    const after = Math.max(-1, ...q.tracks.map((t, i) => (t.kind === kind ? i : -1)));
    q.tracks = after >= 0 ? [...q.tracks.slice(0, after + 1), track, ...q.tracks.slice(after + 1)] : [...q.tracks, track];
  }
  const id = track.id;
  q = { ...q, tracks: q.tracks.map((t) => (t.id === id ? { ...t, clips: [...t.clips, clip] } : t)) };
  return moveClip(q, clip.id, clip.start, id);
}

// ---------------------------------------------------------------- adding media

function samePath(a: string, b: string): boolean {
  const norm = (x: string) => x.replace(/\\/g, "/").toLowerCase();
  return norm(a) === norm(b);
}

/** Add media entries (from the engine's media-info). Files already in the project are reused. */
export function addMedia(p: Project, entries: Media[]): { project: Project; ids: string[] } {
  const q = clone(p);
  const taken = allIds(q);
  const ids = entries.map((m) => {
    const existing = q.media.find((x) => samePath(x.path, m.path));
    if (existing) return existing.id;
    const id = newId(q, "m", taken);
    q.media.push({ ...m, id });
    return id;
  });
  return { project: q, ids };
}

export const STILL_SECONDS = 3;

/** The main-clip boundary nearest to t (where a new main clip is inserted). */
export function mainBoundary(p: Project, t: number): number {
  const clips = [...(mainTrack(p)?.clips ?? [])].sort((a, b) => a.start - b.start);
  let best = clips.length ? clipEnd(clips[clips.length - 1]) : 0;
  for (const c of clips) {
    for (const edge of [c.start, clipEnd(c)]) if (Math.abs(edge - t) < Math.abs(best - t)) best = edge;
  }
  return best;
}

/**
 * Put a media file on the timeline at time `at`.
 * - video or picture on the main track: inserted at the nearest clip boundary (ripple);
 * - on an overlay track: full frame at `at`;
 * - sound: on the given audio track (music if none) at `at`.
 */
export function insertMedia(p: Project, mediaId: string, at: number, targetTrackId?: string): { project: Project; clipId: string } {
  const m = p.media.find((x) => x.id === mediaId);
  if (!m) throw new EditError("That file is not in the project.");
  let q = clone(p);
  const taken = allIds(q);
  let target = targetTrackId ? q.tracks.find((t) => t.id === targetTrackId) : undefined;
  if (!target) {
    if (m.kind === "audio") target = q.tracks.find((t) => t.kind === "audio" && t.role === "music") ?? q.tracks.find((t) => t.kind === "audio");
    else target = mainTrack(q);
  }
  if (!target) {
    target = m.kind === "audio" ? { id: newId(q, "music", taken), kind: "audio", role: "music", name: "Music", clips: [] } : { id: "main", kind: "video", name: "Video", clips: [] };
    q.tracks = isMain(target) ? [target, ...q.tracks] : [...q.tracks, target];
  }
  if (target.locked) throw new EditError(`The ${target.name ?? target.id} track is locked.`);
  const okKind =
    (m.kind === "audio" && target.kind === "audio") ||
    (m.kind === "video" && (target.kind === "video" || target.kind === "overlay" || target.kind === "audio")) ||
    (m.kind === "image" && (target.kind === "video" || target.kind === "overlay"));
  if (!okKind) throw new EditError(`A ${m.kind} file cannot go on the ${target.name ?? target.kind} track.`);
  if (target.kind === "audio" && m.kind === "video" && m.has_audio === false) throw new EditError("That video has no sound.");
  const clipId = newId(q, "c", taken);
  const length = m.kind === "image" ? STILL_SECONDS : m.duration;
  if (!(length > 0)) throw new EditError("That file has no length.");

  let clip: Clip;
  if (target.kind === "video") {
    clip = m.kind === "image" ? { id: clipId, type: "image", media: m.id, start: 0, duration: STILL_SECONDS } : { id: clipId, type: "video", media: m.id, start: 0, duration: r4(length), in: 0, out: r4(length) };
    const at2 = mainBoundary(q, at);
    clip.start = r4(at2);
    const targetId = target.id;
    q = { ...q, tracks: q.tracks.map((t) => (t.id === targetId ? { ...t, clips: [...shiftMainAfter(t.clips, at2, clip.duration), clip] } : t)) };
    q = linked(q, (t) => openSpace(t, at2, clip.duration));
    return { project: resolveOverlaps(q), clipId };
  }
  const start = r4(Math.max(0, at));
  if (target.kind === "overlay") {
    clip = { id: clipId, type: m.kind === "image" ? "image" : "video", media: m.id, start, duration: r4(length), x: 540, y: 960, width: 1080, height: 1920, opacity: 1, animation: "none" };
    if (m.kind === "video") Object.assign(clip, { in: 0, out: r4(length) });
  } else {
    clip = { id: clipId, type: "audio", media: m.id, start, duration: r4(length), in: 0, out: r4(length), volume: 1 };
  }
  const targetId = target.id;
  q = { ...q, tracks: q.tracks.map((t) => (t.id === targetId ? { ...t, clips: [...t.clips, clip] } : t)) };
  const placed = moveClip(q, clipId, start, targetId);
  return { project: placed.project, clipId };
}

// ---------------------------------------------------------------- snapping

/** Times a dragged edge can snap to: 0, the playhead and every clip edge (except `skip`). */
export function snapPoints(p: Project, playhead: number, skip: string[] = []): number[] {
  const points = new Set<number>([0, r4(playhead)]);
  for (const t of p.tracks) {
    for (const c of t.clips) {
      if (skip.includes(c.id)) continue;
      points.add(r4(c.start));
      points.add(r4(clipEnd(c)));
    }
  }
  return [...points];
}

/** The nearest snap point within `threshold` seconds, else t itself. */
export function snap(t: number, points: number[], threshold: number): { t: number; snapped: number | null } {
  let best: number | null = null;
  for (const x of points) if (Math.abs(x - t) <= threshold && (best === null || Math.abs(x - t) < Math.abs(best - t))) best = x;
  return best === null ? { t, snapped: null } : { t: best, snapped: best };
}

/** The clip's start/end checked for every point; returns how far to move so one edge snaps. */
export function snapMove(start: number, duration: number, points: number[], threshold: number): { start: number; snapped: number | null } {
  const a = snap(start, points, threshold);
  const b = snap(start + duration, points, threshold);
  const da = a.snapped === null ? Infinity : Math.abs(a.t - start);
  const db = b.snapped === null ? Infinity : Math.abs(b.t - (start + duration));
  if (da === Infinity && db === Infinity) return { start, snapped: null };
  return da <= db ? { start: a.t, snapped: a.snapped } : { start: b.t - duration, snapped: b.snapped };
}
