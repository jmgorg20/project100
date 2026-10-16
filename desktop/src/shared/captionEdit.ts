// Caption editing: words, timing, style, position, highlights, emoji; and your vocabulary's
// corrections (the same rules as autoedit/vocabulary.py, so the app and engine agree).
import { EditError, allIds, clone, mustFind, newId, placeClip, r4 } from "./edit";
import type { Clip, Project, Word } from "./types";

export interface Correction {
  from: string;
  to: string;
}

export interface Vocabulary {
  words: string[];
  corrections: Correction[];
}

/** Lower-case, punctuation removed (as autoedit.words.normalize). */
export function normalizeWord(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_'-]+/gu, "")
    .replace(/^['-]+|['-]+$/g, "");
}

const tokens = (text: string) => text.split(/\s+/).map(normalizeWord).filter(Boolean);

/** Keep well-formed entries only (as vocabulary.clean). */
export function cleanVocabulary(v: Partial<Vocabulary> | null | undefined): Vocabulary {
  const seen = new Set<string>();
  const words: string[] = [];
  for (const w of v?.words ?? []) {
    const t = String(w).trim();
    if (t && !seen.has(t.toLowerCase())) {
      seen.add(t.toLowerCase());
      words.push(t);
    }
  }
  const corrections = (v?.corrections ?? [])
    .filter((c) => c && String(c.from ?? "").trim() && String(c.to ?? "").trim())
    .map((c) => ({ from: String(c.from).trim(), to: String(c.to).trim() }));
  return { words, corrections };
}

/** Apply corrections to a list of words (clip-local times). Longest phrases first. */
export function correctWords(words: Word[], corrections: Correction[]): Word[] {
  const rules = corrections
    .map((c) => ({ toks: tokens(c.from), to: c.to.trim() }))
    .filter((r) => r.toks.length && r.to)
    .sort((a, b) => b.toks.length - a.toks.length);
  if (!rules.length) return words;
  const plain = words.map((w) => normalizeWord(w.text));
  const out: Word[] = [];
  let i = 0;
  while (i < words.length) {
    const rule = rules.find((r) => r.toks.every((t, k) => plain[i + k] === t));
    if (!rule) {
      out.push(words[i]);
      i++;
      continue;
    }
    const group = words.slice(i, i + rule.toks.length);
    const last = group[group.length - 1];
    const tail = /[.,!?;:]*$/.exec(last.text)?.[0] ?? "";
    out.push({ ...words[i], text: rule.to + tail, end: last.end, highlight: group.some((w) => w.highlight) || undefined });
    if (out[out.length - 1].highlight === undefined) delete out[out.length - 1].highlight;
    i += rule.toks.length;
  }
  return out;
}

/** Apply corrections to every caption in the project. Returns how many captions changed. */
export function correctCaptions(p: Project, corrections: Correction[]): { project: Project; changed: number } {
  let changed = 0;
  const q = clone(p);
  for (const t of q.tracks) {
    if (t.kind !== "caption" || t.locked) continue;
    t.clips = t.clips.map((c) => {
      if (!c.words) return c;
      const fixed = correctWords(c.words, corrections);
      const before = c.words.map((w) => w.text).join(" ");
      const after = fixed.map((w) => w.text).join(" ");
      if (before === after) return c;
      changed++;
      return { ...c, words: fixed };
    });
  }
  return { project: q, changed };
}

function captionOf(p: Project, id: string): Clip {
  const { track, clip } = mustFind(p, id);
  if (track.kind !== "caption" || !clip.words) throw new EditError("That is not a caption.");
  return clip;
}

/**
 * Replace a caption's words. Empty words are dropped, times are kept inside the caption and in
 * order. A caption needs at least one word (delete the caption to remove it).
 */
export function setCaptionWords(p: Project, id: string, words: Word[]): Project {
  const clip = captionOf(p, id);
  const kept = words.map((w) => ({ ...w, text: w.text.replace(/\s+/g, " ").trim() })).filter((w) => w.text);
  if (!kept.length) throw new EditError("A caption needs at least one word. To remove it, delete the caption.");
  let last = 0;
  const fixed = kept.map((w) => {
    const start = r4(Math.min(Math.max(w.start, last), clip.duration));
    const end = r4(Math.min(Math.max(w.end, start), clip.duration));
    last = start;
    const out: Word = { text: w.text, start, end };
    if (w.highlight) out.highlight = true;
    return out;
  });
  const q = clone(p);
  return { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? { ...c, words: fixed } : c)) })) };
}

/** Change the text of one word; several words typed in one box share its time evenly. */
export function editWordText(p: Project, id: string, index: number, text: string): Project {
  const clip = captionOf(p, id);
  const w = clip.words![index];
  if (!w) throw new EditError("That word is no longer in the caption.");
  const parts = text.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) {
    const rest = clip.words!.filter((_, i) => i !== index);
    return setCaptionWords(p, id, rest);
  }
  const step = (w.end - w.start) / parts.length;
  const replaced: Word[] = parts.map((t, k) => ({ text: t, start: w.start + k * step, end: w.start + (k + 1) * step, highlight: w.highlight }));
  return setCaptionWords(p, id, [...clip.words!.slice(0, index), ...replaced, ...clip.words!.slice(index + 1)]);
}

export interface CaptionLook {
  style?: string;
  /** "auto" = the style's own place. */
  zone?: "auto" | "lower" | "center" | "top";
  /** Size override in pixels (null = the style's size). */
  size?: number | null;
  highlight_keywords?: boolean;
}

/** Style, position, size and keyword highlighting, for some captions or all of them. */
export function setCaptionLook(p: Project, ids: string[] | "all", look: CaptionLook): Project {
  if (ids !== "all") ids.forEach((id) => captionOf(p, id));
  const q = clone(p);
  const apply = (c: Clip): Clip => {
    const n: Clip = { ...c };
    if (look.style !== undefined) n.style = look.style;
    if (look.highlight_keywords !== undefined) n.highlight_keywords = look.highlight_keywords;
    const o: Record<string, unknown> = { ...(c.overrides ?? {}) };
    if (look.zone !== undefined) {
      if (look.zone === "auto") delete o.zone;
      else o.zone = look.zone;
    }
    if (look.size !== undefined) {
      if (look.size === null) delete o.size;
      else o.size = Math.round(Math.min(300, Math.max(16, look.size)));
    }
    if (Object.keys(o).length) n.overrides = o;
    else delete n.overrides;
    return n;
  };
  return {
    ...q,
    tracks: q.tracks.map((t) =>
      t.kind !== "caption" || t.locked ? t : { ...t, clips: t.clips.map((c) => (ids === "all" || ids.includes(c.id) ? apply(c) : c)) },
    ),
  };
}

/** Highlight (or un-highlight) one word in the keyword colour. */
export function toggleHighlight(p: Project, id: string, index: number): Project {
  const clip = captionOf(p, id);
  return setCaptionWords(p, id, clip.words!.map((w, i) => (i === index ? { ...w, highlight: !w.highlight } : w)));
}

export const EMOJI = ["😂", "🔥", "❤️", "👍", "😮", "💯", "✨", "🙏", "😭", "🎉", "💸", "👀"];

/** Add an emoji after a word (it shows with that word). */
export function addEmoji(p: Project, id: string, index: number, emoji: string): Project {
  const clip = captionOf(p, id);
  const i = Math.min(Math.max(0, index), clip.words!.length - 1);
  return setCaptionWords(p, id, clip.words!.map((w, k) => (k === i ? { ...w, text: `${w.text} ${emoji}` } : w)));
}

/** A new caption at `at` (2 s, words spread evenly), in the style of the nearest caption. */
export function addCaption(p: Project, at: number, text: string, seconds = 2): { project: Project; clipId: string } {
  const parts = text.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) throw new EditError("Type the caption's words first.");
  const caps = p.tracks.filter((t) => t.kind === "caption").flatMap((t) => t.clips);
  const near = [...caps].sort((a, b) => Math.abs(a.start - at) - Math.abs(b.start - at))[0];
  const step = seconds / parts.length;
  const id = newId(p, "t", allIds(p));
  const clip: Clip = {
    id,
    type: "caption",
    start: r4(Math.max(0, at)),
    duration: seconds,
    style: near?.style ?? "yellow_pop",
    highlight_keywords: near?.highlight_keywords ?? true,
    words: parts.map((t, k) => ({ text: t, start: r4(k * step), end: r4((k + 0.9) * step) })),
  };
  if (near?.overrides) clip.overrides = { ...near.overrides };
  const r = placeClip(p, clip, "caption", () => ({ id: newId(p, "captions"), kind: "caption", name: "Captions", clips: [] }));
  return { project: r.project, clipId: id };
}
