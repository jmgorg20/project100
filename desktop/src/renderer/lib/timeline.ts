// What the preview shows at a timeline time. Pure functions, mirroring the engine:
// clips cover frames round(start*fps) .. round(end*fps); captions follow
// autoedit/captions.py (line breaking, group timing, active word).
import data from "../../shared/engine-data.json";
import type { Clip, Project, Word } from "../../shared/types";

export type CaptionStyle = (typeof data.styles)[number];

export const CANVAS = data.canvas;
const SAFE_WIDTH = data.canvas.width - data.safe.left - data.safe.right;
const NEW_GROUP_PAUSE = 0.7;

export function frameIndex(seconds: number, fps: number): number {
  return Math.floor(seconds * fps + 0.5 + 1e-9);
}

/** True if the clip is on screen at time t (the same frame rule as the renderer). */
export function covers(clip: Clip, t: number, fps: number): boolean {
  const frame = Math.floor(t * fps + 1e-6);
  return frameIndex(clip.start, fps) <= frame && frame < frameIndex(clip.start + clip.duration, fps);
}

export function duration(project: Project): number {
  let end = 0;
  for (const track of project.tracks) for (const c of track.clips) end = Math.max(end, c.start + c.duration);
  return end;
}

export function mainClips(project: Project): Clip[] {
  const track = project.tracks.find((t) => t.kind === "video");
  return track && !track.hidden ? [...track.clips].sort((a, b) => a.start - b.start) : [];
}

export interface Segment {
  start: number;
  end: number;
  clip: Clip | null; // null = empty (black)
}

/** The main track as back-to-back segments, gaps included, covering the whole video. */
export function segments(project: Project): Segment[] {
  const out: Segment[] = [];
  let cursor = 0;
  for (const clip of mainClips(project)) {
    if (clip.start > cursor + 1e-6) out.push({ start: cursor, end: clip.start, clip: null });
    out.push({ start: clip.start, end: clip.start + clip.duration, clip });
    cursor = clip.start + clip.duration;
  }
  const total = duration(project);
  if (total > cursor + 1e-6) out.push({ start: cursor, end: total, clip: null });
  return out;
}

export function segmentAt(segs: Segment[], t: number): number {
  for (let i = 0; i < segs.length; i++) if (t < segs[i].end - 1e-6) return i;
  return segs.length - 1;
}

/** Source-file time for a timeline time inside a video segment (speed included). */
export function sourceTime(seg: Segment, t: number): number {
  return clipSourceTime(seg.clip, Math.max(seg.start, t));
}

/** Source-file time of a clip at timeline time t: in + (t - start) x speed. */
export function clipSourceTime(clip: Clip | null, t: number): number {
  if (!clip) return 0;
  return (clip.in ?? 0) + Math.max(0, t - clip.start) * (clip.speed ?? 1);
}

/** Timeline time when a clip's source is at `source` seconds (inverse of clipSourceTime). */
export function timelineTimeOf(clip: Clip, source: number): number {
  return clip.start + (source - (clip.in ?? 0)) / (clip.speed ?? 1);
}

/**
 * Sound level of a clip at timeline time t: its volume with linear fades (as FFmpeg's afade).
 * The preview can only play up to 100%; louder settings are capped there (the export is not).
 */
export function clipGain(clip: Clip, t: number): number {
  const local = t - clip.start;
  let g = clip.volume ?? 1;
  if (clip.fade_in && local < clip.fade_in) g *= Math.max(0, local / clip.fade_in);
  const left = clip.duration - local;
  if (clip.fade_out && left < clip.fade_out) g *= Math.max(0, left / clip.fade_out);
  return g;
}

/**
 * Where the source picture goes on the 1080x1920 canvas for "fill" with a reframe: the same
 * maths as the engine (scale to cover 1080*zoom x 1920*zoom, then keep a 1080x1920 window
 * at (x, y) of the spare room). Returns the picture's box in canvas pixels.
 */
export function cropBox(sourceW: number, sourceH: number, crop?: { zoom?: number; x?: number; y?: number }) {
  const zoom = crop?.zoom ?? 1;
  const fx = crop?.x ?? 0.5;
  const fy = crop?.y ?? 0.5;
  const W = CANVAS.width;
  const H = CANVAS.height;
  const coverW = Math.ceil((W * zoom) / 2) * 2;
  const coverH = Math.ceil((H * zoom) / 2) * 2;
  const k = Math.max(coverW / sourceW, coverH / sourceH);
  const width = sourceW * k;
  const height = sourceH * k;
  return { left: -(width - W) * fx, top: -(height - H) * fy, width, height };
}

/** Audio-track clips (music, voice-over, effects) sounding at t, with their track. */
export function audioClipsAt(project: Project, t: number): { clip: Clip; muted: boolean }[] {
  const out: { clip: Clip; muted: boolean }[] = [];
  for (const track of project.tracks) {
    if (track.kind !== "audio") continue;
    for (const clip of track.clips) if (t >= clip.start && t < clip.start + clip.duration) out.push({ clip, muted: Boolean(track.muted) });
  }
  return out;
}

function visibleClips(project: Project, kind: string, t: number): Clip[] {
  const fps = project.settings.fps;
  const result: Clip[] = [];
  for (const track of project.tracks) {
    if (track.kind !== kind || track.hidden) continue;
    for (const clip of track.clips) if (covers(clip, t, fps)) result.push(clip);
  }
  return result;
}

/** Zoom amount and anchor at t (later tracks win, like the render); smooth zooms grow. */
export function zoomAt(project: Project, t: number): { amount: number; anchorY: number } {
  let zoom = { amount: 1, anchorY: 0.4 };
  for (const clip of visibleClips(project, "effect", t)) {
    if (clip.type !== "zoom" || (clip.amount ?? 1) <= 1) continue;
    const full = clip.amount ?? 1;
    const k = clip.ease ? Math.min(1, Math.max(0, (t - clip.start) / clip.ease)) : 1;
    zoom = { amount: 1 + (full - 1) * k, anchorY: clip.anchor_y ?? 0.4 };
  }
  return zoom;
}

export function gradeAt(project: Project, t: number): string {
  return gradeLookAt(project, t).grade;
}

export function gradeLookAt(project: Project, t: number): { grade: string; intensity: number } {
  let look = { grade: "none", intensity: 1 };
  for (const clip of visibleClips(project, "effect", t)) if (clip.type === "grade") look = { grade: clip.grade ?? "none", intensity: clip.intensity ?? 1 };
  return look;
}

/** CSS filter for a colour look at a strength (0-1), like the engine's blend with the original. */
export function gradeCss(grade: string, intensity = 1): string {
  const parts = GRADE_PARTS[grade] ?? [];
  if (!parts.length || intensity <= 0) return "none";
  return parts
    .map(([fn, v]) => {
      const neutral = fn === "sepia" || fn === "grayscale" || fn === "hue-rotate" ? 0 : 1;
      const value = neutral + (v - neutral) * Math.min(1, intensity);
      return fn === "hue-rotate" ? `hue-rotate(${value}deg)` : `${fn}(${+value.toFixed(3)})`;
    })
    .join(" ");
}

const GRADE_PARTS: Record<string, [string, number][]> = {
  none: [],
  natural_clean: [["contrast", 1.06], ["brightness", 1.01], ["saturate", 1.12]],
  warm: [["sepia", 0.12], ["saturate", 1.08]],
  black_and_white: [["grayscale", 1], ["contrast", 1.15]],
  orange_teal: [["contrast", 1.05], ["saturate", 1.15], ["hue-rotate", -6]],
  high_contrast: [["contrast", 1.25], ["saturate", 1.15], ["brightness", 0.99]],
};

export interface FxState {
  effect: string;
  intensity: number;
  /** 0 at the start and end of the effect, 1 in its middle (as the engine's flash/dip). */
  peak: number;
  frame: number;
}

/** Moment effects (shake, flash...) on screen at t. */
export function fxAt(project: Project, t: number): FxState[] {
  const fps = project.settings.fps;
  return visibleClips(project, "effect", t)
    .filter((c) => c.type === "fx")
    .map((c) => ({
      effect: c.effect ?? "flash",
      intensity: c.intensity ?? 0.6,
      peak: Math.max(0, 1 - Math.abs((2 * (t - (c.start + c.duration / 2))) / c.duration)),
      frame: Math.floor(t * fps + 1e-6),
    }));
}

/** CSS filter that approximates each colour grade (the render uses FFmpeg's exact filters). */
export const GRADE_CSS: Record<string, string> = {
  none: "none",
  natural_clean: "contrast(1.06) brightness(1.01) saturate(1.12)",
  warm: "sepia(0.12) saturate(1.08)",
  black_and_white: "grayscale(1) contrast(1.15)",
  orange_teal: "contrast(1.05) saturate(1.15) hue-rotate(-6deg)",
  high_contrast: "contrast(1.25) saturate(1.15) brightness(0.99)",
};

/**
 * How the preview draws moment effects (an approximation; "Exact frame" shows the engine's):
 * transform/filter for the picture, and the colour/opacity of a layer over it.
 */
export function fxStyle(states: FxState[], canvasW: number, canvasH: number): { transform: string; filter: string; overlay: { color: string; opacity: number } | null } {
  const transforms: string[] = [];
  const filters: string[] = [];
  let overlay: { color: string; opacity: number } | null = null;
  for (const s of states) {
    const i = s.intensity;
    if (s.effect === "shake") {
      const a = Math.round(8 + 40 * i);
      // The engine crops (W-2a) x (H-2a) at a moving offset and scales it back up.
      const kx = canvasW / (canvasW - 2 * a);
      const ky = canvasH / (canvasH - 2 * a);
      transforms.push(`scale(${kx.toFixed(4)}, ${ky.toFixed(4)}) translate(${(-a * Math.sin(s.frame * 1.9)).toFixed(1)}px, ${(-a * Math.cos(s.frame * 2.7)).toFixed(1)}px)`);
    } else if (s.effect === "flash") {
      overlay = { color: "#ffffff", opacity: (0.25 + 0.75 * i) * s.peak };
      filters.push(`saturate(${(1 - i * s.peak).toFixed(3)})`);
    } else if (s.effect === "dip") {
      overlay = { color: "#000000", opacity: Math.min(1, (0.3 + 0.7 * i) * s.peak) };
      filters.push(`saturate(${(1 - i * s.peak).toFixed(3)})`);
    } else if (s.effect === "glitch") {
      const shift = Math.round(6 + 34 * i);
      transforms.push(`translateX(${s.frame % 2 ? shift / 3 : -shift / 3}px)`);
      filters.push(`hue-rotate(${(s.frame * 37) % 90 - 45}deg) contrast(${1 + 0.3 * i})`);
    } else if (s.effect === "whip") {
      filters.push(`blur(${((8 + 52 * i) / 3).toFixed(1)}px)`);
    }
  }
  return { transform: transforms.join(" "), filter: filters.join(" "), overlay };
}

export function overlaysAt(project: Project, t: number): Clip[] {
  return visibleClips(project, "overlay", t);
}

/** Size multiplier of a pop-in photo, t seconds after it starts (same curve as the render). */
export function popScale(t: number, d: number): number {
  if (t < 0.15) return 0.5 + (0.6 * t) / 0.15;
  if (t < 0.25) return 1.1 - (0.1 * (t - 0.15)) / 0.1;
  if (t > d - 0.2) return 1 - (0.2 * (t - (d - 0.2))) / 0.2;
  return 1;
}

export function popOpacity(t: number, d: number): number {
  return Math.max(0, Math.min(1, t / 0.15, (d - t) / 0.2));
}

// ---------------------------------------------------------------- captions

export function styleFor(clip: Clip): CaptionStyle {
  const base = data.styles.find((s) => s.name === clip.style || s.number === clip.style) ?? data.styles[1];
  return { ...base, ...(clip.overrides ?? {}) } as CaptionStyle;
}

export function displayText(word: Word, style: CaptionStyle): string {
  let text = word.text.replace(/\\/g, "/").replace(/{/g, "(").replace(/}/g, ")").trim();
  if (style.uppercase) text = text.toUpperCase();
  else if (style.lowercase) text = text.toLowerCase();
  if (word.highlight && style.keyword_color && style.keyword_uppercase) text = text.toUpperCase();
  return text;
}

export function maxCharsPerLine(style: CaptionStyle): number {
  if (style.max_chars) return style.max_chars;
  let perChar = ({ regular: 0.55, bold: 0.58, heavy: 0.64 } as Record<string, number>)[style.font] ?? 0.6;
  if (style.uppercase) perChar += 0.08;
  return Math.max(6, Math.floor(SAFE_WIDTH / (style.size * perChar)));
}

/** Words grouped into caption groups of lines (port of captions.chunk_words). */
export function chunkWords(words: Word[], style: CaptionStyle): Word[][][] {
  const limit = maxCharsPerLine(style);
  const groups: Word[][][] = [];
  let lines: Word[][] = [[]];
  let prev: Word | null = null;
  for (const word of words) {
    const line = lines[lines.length - 1];
    const text = [...line, word].map((w) => displayText(w, style)).join(" ");
    const newGroup = prev !== null && (word.start - prev.end > NEW_GROUP_PAUSE || /[.?!]$/.test(prev.text.trimEnd()));
    if (newGroup && lines[0].length) {
      groups.push(lines);
      lines = [[]];
    } else if (line.length && (line.length >= style.words_per_line || [...text].length > limit)) {
      if (lines.length < style.max_lines) lines.push([]);
      else {
        groups.push(lines);
        lines = [[]];
      }
    }
    lines[lines.length - 1].push(word);
    prev = word;
  }
  if (lines[0].length) groups.push(lines);
  return groups;
}

export interface CaptionFrame {
  clip: Clip;
  style: CaptionStyle;
  lines: Word[][];
  /** Index (reading order) of the word being spoken. */
  active: number;
}

/** The caption on screen at t, if any. */
export function captionAt(project: Project, t: number): CaptionFrame | null {
  for (const track of project.tracks) {
    if (track.kind !== "caption" || track.hidden) continue;
    for (const clip of track.clips) {
      const end = clip.start + clip.duration;
      if (t < clip.start || t >= end || !clip.words?.length) continue;
      const style = styleFor(clip);
      const useHighlight = clip.highlight_keywords !== false;
      const words = clip.words.map((w) => ({
        ...w,
        start: clip.start + w.start,
        end: clip.start + w.end,
        highlight: Boolean(useHighlight && w.highlight),
      }));
      const groups = chunkWords(words, style);
      for (let g = 0; g < groups.length; g++) {
        const flat = groups[g].flat();
        const next = groups[g + 1]?.[0][0];
        let groupEnd = end;
        if (next) {
          groupEnd = flat[flat.length - 1].end + data.caption_timing.hold;
          if (next.start - flat[flat.length - 1].end < data.caption_timing.merge_gap) groupEnd = next.start;
          groupEnd = Math.min(groupEnd, next.start);
        }
        if (t >= flat[0].start && t < groupEnd) {
          let active = 0;
          flat.forEach((w, i) => {
            if (w.start <= t) active = i;
          });
          return { clip, style, lines: groups[g], active };
        }
      }
    }
  }
  return null;
}

/** Where the caption block sits on the 1080x1920 frame (as the .ass file positions it). */
export function captionPlacement(style: CaptionStyle, lineCount: number) {
  const zone = (data.zones as Record<string, { align: number; x: number; y: number }>)[style.zone] ?? data.zones.lower;
  const left = style.align === "left";
  const x = left ? data.left_x : zone.x;
  const block = lineCount * style.size; // libass line height == font size
  const top = zone.align === 2 ? zone.y - block : zone.align === 5 ? zone.y - block / 2 : zone.y;
  return { x, top, left, height: block };
}
