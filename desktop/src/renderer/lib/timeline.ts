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

/** Source-file time for a timeline time inside a video segment. */
export function sourceTime(seg: Segment, t: number): number {
  return (seg.clip?.in ?? 0) + Math.max(0, t - seg.start);
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

/** Zoom amount and anchor at t (later tracks win, like the render). */
export function zoomAt(project: Project, t: number): { amount: number; anchorY: number } {
  let zoom = { amount: 1, anchorY: 0.4 };
  for (const clip of visibleClips(project, "effect", t)) {
    if (clip.type === "zoom" && (clip.amount ?? 1) > 1) zoom = { amount: clip.amount ?? 1, anchorY: clip.anchor_y ?? 0.4 };
  }
  return zoom;
}

export function gradeAt(project: Project, t: number): string {
  let grade = "none";
  for (const clip of visibleClips(project, "effect", t)) if (clip.type === "grade") grade = clip.grade ?? "none";
  return grade;
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
