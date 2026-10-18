// The storyboard: the edit shown as scenes before rendering. Mirrors autoedit/storyboard.py (a
// test checks they agree). A scene is a view of the timeline, not a copy: locking a scene locks
// its clips, editing its words edits its captions, so everything stays normal timeline clips.
import { EditError, clone, r4 } from "./edit";
import type { Clip, Project, Track, Word } from "./types";

export const MIN_SCENE = 2.0;
export const MAX_SCENE = 6.0;
const EPS = 0.05;
const CTA_WORDS = ["follow", "i-follow", "subscribe", "comment", "like", "share", "link", "bio", "order",
  "bili", "bumili", "click", "i-click", "download", "sign up", "mag-sign", "dm", "message",
  "i-message", "check out", "tara"];

export type ScenePurpose = "hook" | "point" | "proof" | "question" | "cta" | "outro";
export const PURPOSES: Record<ScenePurpose, [string, string]> = {
  hook: ["Hook", "Pambungad"], point: ["Point", "Punto"], proof: ["Proof / numbers", "Patunay"],
  question: ["Question", "Tanong"], cta: ["Call to action", "Panawagan"], outro: ["Ending", "Pagtatapos"],
};

export interface Scene {
  id: string;
  index: number;
  start: number;
  end: number;
  duration: number;
  purpose: ScenePurpose;
  purpose_label: string;
  purpose_tl: string;
  text: string;
  sources: string[];
  broll: string[];
  graphics: { id: string; template: string; text: string }[];
  transition: string;
  music: string[];
  sfx: number;
  mood: string;
  locked: boolean;
  clips: string[];
}

const end = (c: Clip) => c.start + c.duration;
const captionText = (c: Clip) => (c.words ?? []).map((w) => w.text).join(" ").trim() || String(c.label ?? "");
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&");

export function timelineEnd(p: Project): number {
  return Math.max(0, ...p.tracks.flatMap((t) => t.clips.map(end)));
}

function frozenStarts(p: Project): number[] | null {
  const sb = (p.meta?.storyboard ?? null) as { starts?: unknown } | null;
  const s = sb?.starts;
  if (!Array.isArray(s) || !s.length || !s.every((x) => typeof x === "number")) return null;
  return [...new Set([0, ...(s as number[]).map(r4)])].sort((a, b) => a - b);
}

/** Scene start times worked out from the captions (or the main clips). */
export function detectBoundaries(p: Project): number[] {
  const caps = p.tracks.filter((t) => t.kind === "caption").flatMap((t) => t.clips).sort((a, b) => a.start - b.start);
  const starts = [0];
  let sceneStart = 0;
  if (caps.length) {
    for (let k = 0; k + 1 < caps.length; k++) {
      const next = caps[k + 1];
      const length = next.start - sceneStart;
      const sentenceEnd = /[.!?…]$/.test(captionText(caps[k]));
      if ((length >= MIN_SCENE && sentenceEnd) || length >= MAX_SCENE) {
        sceneStart = next.start;
        starts.push(r4(sceneStart));
      }
    }
  } else {
    for (const c of [...p.tracks[0].clips].sort((a, b) => a.start - b.start)) {
      if (c.start - sceneStart >= MIN_SCENE) {
        sceneStart = c.start;
        starts.push(r4(sceneStart));
      }
    }
  }
  return starts;
}

function purposeOf(index: number, count: number, text: string): ScenePurpose {
  const low = ` ${text.toLowerCase()} `;
  if (index === 0) return "hook";
  if (index === count - 1 && CTA_WORDS.some((w) => new RegExp(`\\b${escape(w)}\\b`).test(low))) return "cta";
  if (/\d|₱|\$|%|piso|peso/.test(low)) return "proof";
  if (text.includes("?")) return "question";
  if (index === count - 1) return "outro";
  return "point";
}

/** The clips that belong to a scene: they start in it and end by its end (not main clips). */
export function sceneClips(p: Project, s: { start: number; end: number }): [Track, Clip][] {
  const out: [Track, Clip][] = [];
  p.tracks.forEach((t, i) => {
    if (i === 0) return;
    for (const c of t.clips) if (s.start - EPS <= c.start && c.start < s.end - EPS && end(c) <= s.end + EPS) out.push([t, c]);
  });
  return out;
}

export function scenes(p: Project): Scene[] {
  const media = new Map(p.media.map((m) => [m.id, m]));
  const name = (id?: string) => {
    const m = id ? media.get(id) : undefined;
    return m?.name || String(m?.path ?? id).replace(/\\/g, "/").split("/").pop()!;
  };
  const last = timelineEnd(p);
  let starts = (frozenStarts(p) ?? detectBoundaries(p)).filter((s) => s < last - EPS);
  if (!starts.length) starts = [0];
  return starts.map((a, k) => {
    const b = k + 1 < starts.length ? starts[k + 1] : last;
    const range = { start: r4(a), end: r4(b) };
    const own = sceneClips(p, range);
    const caps = own.filter(([t]) => t.kind === "caption").map(([, c]) => c).sort((x, y) => x.start - y.start);
    const text = caps.map(captionText).join(" ").trim();
    const sources: string[] = [];
    for (const c of p.tracks[0].clips) {
      if (!(c.start < b - EPS && end(c) > a + EPS)) continue;
      const n = c.media ? name(c.media) : c.type;
      if (!sources.includes(n)) sources.push(n);
    }
    const broll: string[] = [];
    for (const [t, c] of own) if (t.kind === "overlay" && c.media && !broll.includes(name(c.media))) broll.push(name(c.media));
    const graphics = own.filter(([, c]) => c.type === "graphic").map(([, c]) => ({ id: c.id, template: c.template ?? "", text: String(c.params?.text ?? "") }));
    let transition = k === 0 ? "start" : "cut";
    for (const [, c] of [...own].sort((x, y) => x[1].start - y[1].start)) {
      if (c.start > a + 0.4) continue;
      if (c.type === "wipe") { transition = "wipe"; break; }
      if (c.attach?.kind) { transition = c.attach.kind; break; }
      if (c.type === "fx" && ["flash", "whip", "shake", "glitch"].includes(String(c.effect))) { transition = String(c.effect); break; }
    }
    const mid = (a + b) / 2;
    const music: string[] = [];
    let sfx = 0;
    for (const t of p.tracks) {
      if (t.kind !== "audio") continue;
      for (const c of t.clips) {
        if (t.role === "music" && c.start < b - EPS && end(c) > a + EPS && !music.includes(name(c.media))) music.push(name(c.media));
        if (t.role === "sfx" && a - EPS <= c.start && c.start < b - EPS) sfx += 1;
      }
    }
    let mood = "none";
    for (const t of p.tracks) for (const c of t.clips) if (c.type === "grade" && c.start <= mid && mid < end(c)) mood = String(c.grade);
    const lockable = own.map(([, c]) => c);
    const purpose = purposeOf(k, starts.length, text);
    return {
      id: `s${k + 1}`, index: k + 1, start: range.start, end: range.end, duration: r4(b - a),
      purpose, purpose_label: PURPOSES[purpose][0], purpose_tl: PURPOSES[purpose][1],
      text, sources, broll, graphics, transition, music, sfx, mood,
      locked: lockable.length > 0 && lockable.every((c) => c.locked), clips: lockable.map((c) => c.id),
    };
  });
}

export function findScene(p: Project, id: string): Scene {
  const all = scenes(p);
  const s = all.find((x) => x.id === id || String(x.index) === String(id));
  if (!s) throw new EditError(`There is no scene '${id}' (the storyboard has ${all.length}).`);
  return s;
}

/** Keep the current scenes as they are (editing words then does not regroup them). */
export function freeze(p: Project): Project {
  const starts = scenes(p).map((s) => s.start);
  const q = clone(p);
  const sb = (q.meta?.storyboard ?? {}) as Record<string, unknown>;
  return { ...q, meta: { ...(q.meta ?? {}), storyboard: { ...sb, starts } } };
}

/** Lock (or unlock) every clip of a scene. */
export function setSceneLocked(p: Project, id: string, locked: boolean): Project {
  const q = freeze(p);
  const ids = new Set(findScene(q, id).clips);
  return {
    ...q,
    tracks: q.tracks.map((t) => ({
      ...t,
      clips: t.clips.map((c) => {
        if (!ids.has(c.id)) return c;
        const n = { ...c };
        if (locked) n.locked = true;
        else delete n.locked;
        return n;
      }),
    })),
  };
}

/** Split `total` words over captions that had `counts` words (largest remainder, >= 1 each). */
export function spread(counts: number[], total: number): number[] {
  const n = counts.length;
  if (total <= n) return counts.map((_, i) => (i < total ? 1 : 0));
  const weight = counts.reduce((a, b) => a + b, 0) || n;
  const exact = counts.map((c) => (total * c) / weight);
  const out = exact.map((x) => Math.max(1, Math.floor(x)));
  const sum = () => out.reduce((a, b) => a + b, 0);
  while (sum() > total) {
    let i = 0;
    for (let j = 0; j < n; j++) if (out[j] - exact[j] > out[i] - exact[i] || (out[j] - exact[j] === out[i] - exact[i] && j > i)) i = j;
    out[i] -= 1;
  }
  const order = [...Array(n).keys()].sort((x, y) => -(exact[x] - out[x]) + (exact[y] - out[y]) || x - y);
  for (let k = 0; sum() < total; k++) out[order[k % n]] += 1;
  return out;
}

/** Replace a scene's caption words (evenly timed inside each caption). */
export function setSceneText(p: Project, id: string, text: string): Project {
  const q = freeze(p);
  const ids = new Set(findScene(q, id).clips);
  const caps = q.tracks.filter((t) => t.kind === "caption").flatMap((t) => t.clips).filter((c) => ids.has(c.id)).sort((a, b) => a.start - b.start);
  if (!caps.length) throw new EditError("This scene has no captions to change.");
  if (caps.some((c) => c.locked)) throw new EditError("This scene is locked. Unlock it first.");
  const words = text.split(/\s+/).filter(Boolean);
  if (!words.length) throw new EditError("Type the words for this scene (to remove its captions, delete them on the timeline).");
  const counts = spread(caps.map((c) => (c.words ?? []).length), words.length);
  const next = new Map<string, Word[] | null>();
  let at = 0;
  caps.forEach((c, i) => {
    const n = counts[i];
    if (!n) return void next.set(c.id, null);
    const step = c.duration / n;
    next.set(c.id, words.slice(at, at + n).map((w, j) => ({ text: w, start: r4(j * step), end: r4((j + 1) * step) })));
    at += n;
  });
  return {
    ...q,
    tracks: q.tracks.map((t) => ({
      ...t,
      clips: t.clips.filter((c) => next.get(c.id) !== null).map((c) => (next.has(c.id) ? { ...c, words: next.get(c.id)! } : c)),
    })),
  };
}
