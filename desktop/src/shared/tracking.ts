// Following a tracked point: bridging short gaps, smoothing, and fading out instead of jumping
// when the point is lost. A line-for-line port of autoedit/tracking.py (the engine draws the
// export from the same rules; a test compares both on the same synthetic tracks).
import type { Clip, TrackData, TrackPoint } from "./types";

export const HANDS = ["left", "right"] as const;
export const FINGERTIPS = ["thumb_tip", "index_tip", "middle_tip", "ring_tip", "pinky_tip"];

export const DEFAULTS = {
  min_confidence: 0.35,
  gap: 0.25,
  attack: 0.12,
  release: 0.4,
  settle: 0.2,
};
export type TrackParams = typeof DEFAULTS;

/** Python's round(): halves go to the even number (so 7.5 -> 8, 6.5 -> 6), like the engine. */
export function pyRound(x: number): number {
  const f = Math.floor(x);
  const d = x - f;
  if (d < 0.5) return f;
  if (d > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

const smoothstep = (x: number) => {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
};

/** smooth 0 (follow the raw points) .. 1 (very steady): the filter's cutoff in Hz. */
export function minCutoffFor(smooth: number): number {
  const s = Math.min(1, Math.max(0, Number(smooth)));
  return 15 * Math.pow(0.6 / 15, s);
}

/** The One Euro filter over evenly spaced samples. */
export function oneEuro(values: number[], dt: number, minCutoff: number, beta = 5, dcutoff = 1): number[] {
  const alpha = (cutoff: number) => {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  };
  const out: number[] = [];
  let prev: number | null = null;
  let dprev = 0;
  for (const v of values) {
    if (prev === null) {
      out.push(v);
      prev = v;
      continue;
    }
    const d = (v - prev) / dt;
    const dhat: number = dprev + alpha(dcutoff) * (d - dprev);
    const cutoff = minCutoff + beta * Math.abs(dhat);
    const hat: number = prev + alpha(cutoff) * (v - prev);
    out.push(hat);
    prev = hat;
    dprev = dhat;
  }
  return out;
}

export interface Sample {
  found: boolean;
  x: number;
  y: number;
  size: number;
}

/** A point with its short gaps filled and each found stretch smoothed. */
export class Prepared {
  readonly n: number;
  private xs: number[];
  private ys: number[];
  private ss: number[];
  private present: boolean[];
  readonly p: TrackParams;

  constructor(point: TrackPoint, readonly fps: number, readonly start: number, smooth = 0.5, params: Partial<TrackParams> = {}) {
    this.p = { ...DEFAULTS, ...params };
    const n = (this.n = point.x.length);
    const dt = 1 / fps;
    const present = point.c.map((c) => c >= this.p.min_confidence);
    const xs = [...point.x];
    const ys = [...point.y];
    const ss = point.s ? [...point.s] : new Array(n).fill(0);
    const gap = Math.max(1, pyRound(this.p.gap * fps));
    let i = 0;
    while (i < n) {
      if (present[i]) {
        i++;
        continue;
      }
      let j = i;
      while (j < n && !present[j]) j++;
      if (i > 0 && j < n && j - i <= gap) {
        for (let k = i; k < j; k++) {
          const f = (k - i + 1) / (j - i + 1);
          xs[k] = xs[i - 1] + (xs[j] - xs[i - 1]) * f;
          ys[k] = ys[i - 1] + (ys[j] - ys[i - 1]) * f;
          ss[k] = ss[i - 1] + (ss[j] - ss[i - 1]) * f;
          present[k] = true;
        }
      }
      i = j;
    }
    const cutoff = minCutoffFor(smooth);
    i = 0;
    while (i < n) {
      if (!present[i]) {
        i++;
        continue;
      }
      let j = i;
      while (j < n && present[j]) j++;
      const fx = oneEuro(xs.slice(i, j), dt, cutoff);
      const fy = oneEuro(ys.slice(i, j), dt, cutoff);
      for (let k = i; k < j; k++) {
        xs[k] = fx[k - i];
        ys[k] = fy[k - i];
      }
      if (point.s) {
        const fs = oneEuro(ss.slice(i, j), dt, cutoff);
        for (let k = i; k < j; k++) ss[k] = fs[k - i];
      }
      i = j;
    }
    this.xs = xs;
    this.ys = ys;
    this.ss = ss;
    this.present = present;
  }

  /** The point at source time t (found only where samples exist). */
  at(t: number): Sample {
    const n = this.n;
    const u = (t - this.start) * this.fps;
    const none = { found: false, x: 0, y: 0, size: 0 };
    if (!n || u < -0.5 || u > n - 0.5) return none;
    const i0 = Math.min(n - 1, Math.max(0, Math.floor(u)));
    const i1 = Math.min(n - 1, i0 + 1);
    const f = Math.min(1, Math.max(0, u - i0));
    if (this.present[i0] && this.present[i1]) {
      return {
        found: true,
        x: this.xs[i0] + (this.xs[i1] - this.xs[i0]) * f,
        y: this.ys[i0] + (this.ys[i1] - this.ys[i0]) * f,
        size: this.ss[i0] + (this.ss[i1] - this.ss[i0]) * f,
      };
    }
    const k = f < 0.5 ? i0 : i1;
    return this.present[k] ? { found: true, x: this.xs[k], y: this.ys[k], size: this.ss[k] } : none;
  }
}

export interface Resolved {
  x: number[];
  y: number[];
  alpha: number[];
  size: number[];
}

/**
 * Follow a point over consecutive output frames: one [prepared | null, source time] per frame.
 * Lost: the position is held and alpha fades to 0 over `release` seconds; found: it fades in
 * over `attack`; found again while still fading: it glides to the new place over `settle`.
 */
export function resolveSequence(items: [Prepared | null, number][], dt: number, params: Partial<TrackParams> = {}): Resolved {
  const p = { ...DEFAULTS, ...params };
  const out: Resolved = { x: [], y: [], alpha: [], size: [] };
  let vis = 0;
  let held: [number, number, number] | null = null;
  let was = false;
  let settleFrom: [number, number, number] | null = null;
  let settleT = 0;
  items.forEach(([prep, t], k) => {
    const s = prep ? prep.at(t) : { found: false, x: 0, y: 0, size: 0 };
    const now = k * dt;
    if (s.found) {
      let fresh = false;
      if (!was) {
        if (vis > 0.02 && held !== null) {
          settleFrom = held;
          settleT = now;
        } else {
          held = null;
          settleFrom = null;
          vis = 0;
          fresh = true;
        }
      }
      if (!fresh) vis = Math.min(1, vis + dt / p.attack);
      let px = s.x;
      let py = s.y;
      if (settleFrom) {
        const f = smoothstep((now - settleT) / p.settle);
        px = settleFrom[0] + (s.x - settleFrom[0]) * f;
        py = settleFrom[1] + (s.y - settleFrom[1]) * f;
        if (f >= 1) settleFrom = null;
      }
      held = [px, py, s.size];
    } else {
      vis = Math.max(0, vis - dt / p.release);
    }
    was = s.found;
    if (held === null) {
      out.x.push(0.5);
      out.y.push(0.5);
      out.size.push(0);
      out.alpha.push(0);
    } else {
      out.x.push(held[0]);
      out.y.push(held[1]);
      out.size.push(held[2]);
      out.alpha.push(smoothstep(vis));
    }
  });
  return out;
}

// ---------------------------------------------------------------- which points

/** Every stored point name a tracked-effect clip could follow (both hands for "any"). */
export function pointNamesFor(clip: Pick<Clip, "point" | "hand">): string[] {
  const point = clip.point ?? "palm";
  if (point === "face" || point === "body") return [point];
  const parts = point === "fingertips" ? FINGERTIPS : [point];
  const hands = (clip.hand ?? "any") === "any" ? [...HANDS] : [clip.hand as string];
  return hands.flatMap((h) => parts.map((part) => `${h}_${part}`));
}

/** The point name for "left", "right" or "any" hand ("any": the one found most between t0 and t1). */
export function pickHand(track: TrackData, hand: string, part: string, t0: number, t1: number, minConfidence = DEFAULTS.min_confidence): string {
  const name = (h: string) => `${h}_${part}`;
  if (hand === "left" || hand === "right") return name(hand);
  let best = name("right");
  let bestScore = -1;
  for (const h of HANDS) {
    const pt = track.points[name(h)];
    if (!pt) continue;
    const start = track.start ?? 0;
    const a = Math.max(0, Math.floor((t0 - start) * track.fps));
    const b = Math.min(pt.c.length, Math.ceil((t1 - start) * track.fps) + 1);
    let score = 0;
    for (const c of pt.c.slice(a, b)) if (c >= minConfidence) score += c;
    if (score > bestScore) {
      best = name(h);
      bestScore = score;
    }
  }
  return best;
}

/** The share (0-1) of source seconds t0..t1 in which the best of these points was found. */
export function coverage(track: TrackData, names: string[], t0: number, t1: number, minConfidence = DEFAULTS.min_confidence): number {
  let best = 0;
  for (const name of names) {
    const pt = track.points[name];
    if (!pt) continue;
    const start = track.start ?? 0;
    const a = Math.max(0, Math.floor((t0 - start) * track.fps));
    const b = Math.min(pt.c.length, Math.ceil((t1 - start) * track.fps));
    if (b > a) {
      let n = 0;
      for (const c of pt.c.slice(a, b)) if (c >= minConfidence) n++;
      best = Math.max(best, n / (b - a));
    }
  }
  return best;
}
