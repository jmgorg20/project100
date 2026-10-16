// Where each tracked effect is on the picture at a time, for the live preview. The point is
// followed with the same rules as the engine (shared/tracking.ts), read at the source time of
// each frame of the main video, and placed on the 1080x1920 canvas through the main clip's fit
// and reframe. Zoom effects are applied by the preview's own zoom (the effect layer sits inside
// the zoomed picture, so it follows the zoom like the render does).
import { FINGERTIPS, Prepared, pickHand, resolveSequence } from "../../shared/tracking";
import type { Clip, Media, Project, TrackData } from "../../shared/types";
import { CANVAS, cropBox, frameIndex, mainClips } from "./timeline";

export interface PreviewPoint {
  /** Canvas pixels (1080x1920), size too. alpha 0-1 (0 = lost / not shown). */
  x: number;
  y: number;
  alpha: number;
  size: number;
}

export interface PreviewFx {
  clip: Clip;
  /** Frame inside the clip, and the clip's length in frames. */
  k: number;
  n: number;
  /** One list per followed point (several for "fingertips"): a point per clip frame. */
  paths: PreviewPoint[][];
}

/** The followed point names, chosen like the engine (trackfx.point_names). */
export function followedNames(track: TrackData, clip: Clip, t0: number, t1: number): string[] {
  const point = clip.point ?? "palm";
  if (point === "face" || point === "body") return [point];
  const hand = pickHand(track, clip.hand ?? "any", point === "fingertips" ? "index_tip" : point, t0, t1);
  return point === "fingertips" ? FINGERTIPS.map((f) => `${hand.split("_")[0]}_${f}`) : [hand];
}

interface Frame {
  media: Media;
  source: number;
  fit: string;
  crop?: Clip["crop"];
}

/** Where a source position lands on the canvas (the engine's FrameMap.to_frame). */
export function toCanvas(m: { width: number; height: number }, fit: string, crop: Clip["crop"] | undefined, u: number, v: number, s: number): [number, number, number] {
  if (fit === "blur") {
    const k = Math.min(CANVAS.width / m.width, CANVAS.height / m.height);
    const sw = m.width * k;
    const sh = m.height * k;
    return [u * sw + (CANVAS.width - sw) / 2, v * sh + (CANVAS.height - sh) / 2, s * sw];
  }
  const box = cropBox(m.width, m.height, crop);
  return [box.left + u * box.width, box.top + v * box.height, s * box.width];
}

const cache = new WeakMap<Clip, { deps: unknown[]; paths: PreviewPoint[][] }>();

/** Every frame's point(s) of one tracked effect (memoised until the project parts it reads change). */
export function trackfxPaths(project: Project, clip: Clip): PreviewPoint[][] {
  const main = mainClips(project);
  const deps = [project.tracking, project.media, main, clip];
  const hit = cache.get(clip);
  if (hit && hit.deps.every((d, i) => d === deps[i])) return hit.paths;
  const fps = project.settings.fps;
  const f0 = frameIndex(clip.start, fps);
  const f1 = frameIndex(clip.start + clip.duration, fps);
  const n = Math.max(0, f1 - f0);
  const frames: (Frame | null)[] = [];
  for (let f = f0; f < f1; f++) {
    const host = main.find((c) => c.type === "video" && !c.layout && frameIndex(c.start, fps) <= f && f < frameIndex(c.start + c.duration, fps));
    const media = host && project.media.find((m) => m.id === host.media);
    if (!host || !media?.width || !media.height) {
      frames.push(null);
      continue;
    }
    const sp = host.speed ?? 1;
    frames.push({ media, source: (host.in ?? 0) + ((f - frameIndex(host.start, fps)) / fps) * sp, fit: host.fit ?? "fill", crop: host.crop });
  }
  const first = frames.find((x): x is Frame => x !== null);
  const track = first && project.tracking?.[first.media.id];
  const paths: PreviewPoint[][] = [];
  if (first && track) {
    const times = frames.filter((x): x is Frame => x !== null).map((x) => x.source);
    for (const name of followedNames(track, clip, Math.min(...times), Math.max(...times))) {
      const preps = new Map<string, Prepared | null>();
      const items: [Prepared | null, number][] = frames.map((fr) => {
        if (!fr) return [null, 0];
        const tr = project.tracking?.[fr.media.id];
        const pt = tr?.points[name];
        if (!tr || !pt) return [null, fr.source];
        const key = fr.media.id;
        if (!preps.has(key)) preps.set(key, new Prepared(pt, tr.fps, tr.start ?? 0, clip.smooth ?? 0.5));
        return [preps.get(key) ?? null, fr.source];
      });
      const res = resolveSequence(items, 1 / fps);
      paths.push(
        res.x.map((_, i) => {
          const fr = frames[i];
          if (!fr) return { x: 0, y: 0, alpha: 0, size: 0 };
          const [x, y, size] = toCanvas(fr.media as { width: number; height: number }, fr.fit, fr.crop, res.x[i], res.y[i], res.size[i]);
          return { x, y, alpha: res.alpha[i], size };
        }),
      );
    }
  }
  const out = paths.length ? paths : [new Array(n).fill({ x: 0, y: 0, alpha: 0, size: 0 })];
  cache.set(clip, { deps, paths: out });
  return out;
}

/** The tracked effects on screen at time t. */
export function trackfxAt(project: Project, t: number): PreviewFx[] {
  const fps = project.settings.fps;
  const frame = Math.floor(t * fps + 1e-6);
  const out: PreviewFx[] = [];
  for (const track of project.tracks) {
    if (track.kind !== "effect" || track.hidden) continue;
    for (const clip of track.clips) {
      if (clip.type !== "trackfx") continue;
      const f0 = frameIndex(clip.start, fps);
      const f1 = frameIndex(clip.start + clip.duration, fps);
      if (frame < f0 || frame >= f1) continue;
      out.push({ clip, k: frame - f0, n: f1 - f0, paths: trackfxPaths(project, clip) });
    }
  }
  return out;
}
