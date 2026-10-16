// B-roll on the timeline: add a found/made item as a clip, put another file on a B-roll clip,
// and the credits / AI label the export needs. Mirrors autoedit/broll.py (add_clip,
// replace_clip_media), and the engine's validator checks the results in the tests.
import { EditError, addMedia, clone, mustFind, newId, placeClip, speedOf } from "./edit";
import type { BrollMeta, BrollStyle, Clip, Media, Project, Track } from "./types";

export const BROLL_STYLES: { id: BrollStyle; label: string; tl: string }[] = [
  { id: "realistic", label: "Realistic", tl: "Totoong kuha" },
  { id: "cartoon", label: "Cartoon", tl: "Cartoon" },
  { id: "drawing", label: "Drawing / sketch", tl: "Guhit" },
  { id: "low_poly", label: "Low-poly / boxy 3D", tl: "Parang kahon" },
  { id: "stylized_3d", label: "Stylized 3D / robot", tl: "3D na parang laruan" },
  { id: "anime", label: "Anime", tl: "Anime" },
];

/** Where a B-roll item goes on the 1080x1920 frame: max width, max height, centre x, centre y. */
export const BROLL_POSITIONS: Record<"full" | "top" | "center", [number, number, number, number]> = {
  top: [820, 560, 500, 520],
  center: [820, 560, 500, 900],
  full: [1080, 1920, 540, 960],
};

export const SOURCE_NAMES: Record<BrollMeta["source"], string> = {
  library: "Library",
  pexels: "Pexels",
  pixabay: "Pixabay",
  ai: "AI",
  file: "B-roll",
};

/** Short clip name on the timeline, e.g. "AI: coffee cup" (same as the engine). */
export function brollLabel(meta: BrollMeta): string {
  const what = (meta.search || meta.prompt || "B-roll").trim().slice(0, 60);
  return `${SOURCE_NAMES[meta.source] ?? "B-roll"}: ${what}`;
}

/** One line saying where a B-roll clip came from. */
export function describeSource(meta: BrollMeta, fileName: string): string {
  if (meta.source === "library") return `From your B-roll library (${fileName})`;
  if (meta.source === "pexels" || meta.source === "pixabay") return meta.credit ?? `Free stock from ${SOURCE_NAMES[meta.source]}`;
  if (meta.source === "ai") return `Made with AI${meta.tier ? ` (${meta.tier} tier)` : ""}`;
  return `Your file (${fileName})`;
}

const r4 = (x: number) => Math.round(x * 1e4) / 1e4;

/** Make an overlay clip show `media`: keeps its place, size and timing where it can. */
function fit(clip: Clip, media: Media): Clip {
  const n: Clip = { ...clip, media: media.id, type: media.kind === "image" ? "image" : "video" };
  if (n.type === "video") {
    const speed = speedOf(clip);
    const length = media.duration > 0 ? media.duration / speed : clip.duration;
    n.duration = r4(Math.min(clip.duration, length));
    n.in = 0;
    n.out = r4(n.duration * speed);
  } else {
    delete n.in;
    delete n.out;
    delete n.speed;
  }
  return n;
}

/** Put another file on a B-roll clip (find another, regenerate, replace with a file). */
export function replaceBroll(p: Project, clipId: string, media: Media, meta: BrollMeta): Project {
  const { track } = mustFind(p, clipId);
  if (track.kind !== "overlay") throw new EditError("Only B-roll / photo clips can be replaced.");
  if (media.kind === "audio") throw new EditError("A sound file cannot be B-roll.");
  if (track.locked) throw new EditError(`The ${track.name ?? track.id} track is locked.`);
  const added = addMedia(p, [media]);
  const q = added.project;
  const m = q.media.find((x) => x.id === added.ids[0])!;
  return {
    ...q,
    tracks: q.tracks.map((t) => ({
      ...t,
      clips: t.clips.map((c) => {
        if (c.id !== clipId) return c;
        const position = c.broll?.position ?? meta.position ?? "full";
        return { ...fit(c, m), broll: { ...meta, position }, label: brollLabel(meta) };
      }),
    })),
  };
}

/** A new B-roll clip at `at` (timeline seconds), on a free overlay track. */
export function addBroll(
  p: Project,
  media: Media,
  meta: BrollMeta,
  at: number,
  duration: number,
  position: "full" | "top" | "center" = "full",
): { project: Project; clipId: string } {
  if (media.kind === "audio") throw new EditError("A sound file cannot be B-roll.");
  if (!(duration > 0)) throw new EditError("The B-roll needs a length.");
  const added = addMedia(p, [media]);
  const q = added.project;
  const m = q.media.find((x) => x.id === added.ids[0])!;
  const [w, h, x, y] = BROLL_POSITIONS[position];
  const clipId = newId(q, "b");
  const clip = fit(
    {
      id: clipId, type: "image", media: m.id, start: r4(Math.max(0, at)), duration: r4(duration), x, y, width: w, height: h,
      opacity: 1, animation: position === "full" ? "none" : "pop",
    },
    m,
  );
  clip.broll = { ...meta, position };
  clip.label = brollLabel(meta);
  const n = q.tracks.filter((t) => t.kind === "overlay").length;
  const newTrack = (): Track => ({ id: newId(q, "broll"), kind: "overlay", name: `B-roll ${n + 1}`, clips: [] });
  const placed = placeClip(q, clip, "overlay", newTrack);
  return { project: placed.project, clipId };
}

/** Change what a B-roll clip should show (used by the next find/regenerate). */
export function setBrollRequest(p: Project, clipId: string, patch: Pick<BrollMeta, "prompt" | "search" | "style">): Project {
  const { track, clip } = mustFind(p, clipId);
  if (track.kind !== "overlay") throw new EditError("Only B-roll clips have a description.");
  const q = clone(p);
  const meta: BrollMeta = { ...(clip.broll ?? { source: "file", kind: clip.type === "video" ? "video" : "image" }), ...patch };
  for (const k of ["prompt", "search"] as const) if (meta[k] !== undefined) meta[k] = String(meta[k]).slice(0, k === "prompt" ? 500 : 120);
  return { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === clipId ? { ...c, broll: meta } : c)) })) };
}

/** Credits for the stock items in a project, and whether anything on it was made with AI. */
export function brollCredits(p: Project): { credits: string[]; aiClips: number } {
  const credits: string[] = [];
  let aiClips = 0;
  for (const t of p.tracks) {
    if (t.hidden) continue;
    for (const c of t.clips) {
      if (!c.broll) continue;
      if (c.broll.ai_generated) aiClips++;
      if (c.broll.credit && !credits.includes(c.broll.credit)) credits.push(c.broll.credit);
    }
  }
  return { credits, aiClips };
}

/** Files and stock ids a "find another" should skip: the clip's own, and every other B-roll's. */
export function brollExclusions(p: Project, clipId?: string): string[] {
  const out = new Set<string>();
  for (const t of p.tracks) {
    if (t.kind !== "overlay") continue;
    for (const c of t.clips) {
      if (!c.broll && c.id !== clipId) continue;
      const m = p.media.find((x) => x.id === c.media);
      if (m) out.add(m.path);
      if (c.broll?.stock_id) out.add(c.broll.stock_id);
    }
  }
  return [...out];
}
