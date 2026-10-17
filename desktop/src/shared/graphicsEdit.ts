// Motion graphics on the timeline: adding a template at the playhead, changing its words,
// colours and look, locking it, "another look", the before/after wipe, and the flash / whip /
// punch-in a graphic can carry. Every result is a valid project (the engine checks them in tests).
import catalogJson from "./graphics-catalog.json";
import { EditError, allIds, clipEnd, clone, findClip, newId, placeClip, projectDuration, r4 } from "./edit";
import type { AttachKind, Clip, GraphicParams, Project, Track } from "./types";

export interface TemplateInput {
  key: string;
  type: "text" | "number" | "image" | "list";
  required: boolean;
}

export interface TemplateMeta {
  id: string;
  name: string;
  tl: string;
  category: string;
  moods: string[];
  inputs: TemplateInput[];
  duration: number;
  minDuration: number;
  maxDuration: number;
  zone: string;
  anchor: { x: number; y: number };
  box: { w: number; h: number };
  fields: (keyof GraphicParams)[];
  bg: boolean;
  maxChars: number;
  minFont: number;
  numRange: [number, number] | null;
  defaults: GraphicParams;
  sample: GraphicParams;
  tip?: { dist: number };
}

export interface Catalog {
  version: number;
  renderer: number;
  moods: string[];
  fonts: Record<string, string>;
  icons: string[];
  templates: TemplateMeta[];
}

export const CATALOG = catalogJson as unknown as Catalog;
const BY_ID = new Map(CATALOG.templates.map((t) => [t.id, t]));
export const templateMeta = (id: string | undefined): TemplateMeta | undefined => (id ? BY_ID.get(id) : undefined);

export const CATEGORY_LABELS: Record<string, { label: string; tl: string }> = {
  text: { label: "Words", tl: "Mga salita" },
  card: { label: "Cards", tl: "Cards" },
  pill: { label: "Pills", tl: "Pills" },
  data: { label: "Numbers", tl: "Numero" },
  pointer: { label: "Arrows", tl: "Arrow / bilog" },
  emoji: { label: "Emoji", tl: "Emoji" },
  banner: { label: "Banners", tl: "Banner" },
};

/** The Director's looks (autoedit/director_styles.py; a test keeps both lists the same). */
export const GRAPHIC_STYLES: { id: string; label: string; tl: string }[] = [
  { id: "auto", label: "Auto (when the instructions ask)", tl: "Kapag hiniling" },
  { id: "off", label: "No graphics", tl: "Walang graphics" },
  { id: "promoter", label: "Professional promoter", tl: "Propesyonal na promoter" },
  { id: "calm_documentary", label: "Calm documentary", tl: "Kalmadong documentary" },
  { id: "meme", label: "Meme / funny", tl: "Meme / nakakatawa" },
  { id: "news", label: "News / explainer", tl: "Balita / paliwanag" },
  { id: "luxury", label: "Luxury / premium", tl: "Luxury / premium" },
  { id: "minimal", label: "Minimal", tl: "Minimal" },
];

export const ATTACH_LABELS: Record<AttachKind, string> = { flash: "Flash", whip: "Whip", punch: "Punch-in" };
const HEX = /^#[0-9a-fA-F]{6}$/;
const clamp = (x: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, x));

/** Templates matching a search text, a mood and (optionally) only favourites. */
export function searchTemplates(query: string, mood: string, favourites?: Set<string>): TemplateMeta[] {
  const q = query.trim().toLowerCase();
  return CATALOG.templates.filter(
    (t) =>
      (!q || [t.id, t.name, t.tl, t.category, ...t.moods].some((s) => s.toLowerCase().includes(q))) &&
      (!mood || t.moods.includes(mood)) &&
      (!favourites || favourites.has(t.id)),
  );
}

const isGraphics = (t: Track) => t.kind === "graphics";

/** A graphic from a template, starting at `at`, with the template's own sample words. */
export function addGraphic(p: Project, templateId: string, at: number, params?: GraphicParams): { project: Project; clipId: string } {
  const meta = templateMeta(templateId);
  if (!meta) throw new EditError(`There is no graphic called "${templateId}".`);
  const total = Math.max(projectDuration(p), meta.minDuration);
  const start = r4(clamp(at, 0, Math.max(0, total - meta.minDuration)));
  const duration = r4(clamp(Math.min(meta.duration, total - start), meta.minDuration, meta.maxDuration));
  const id = newId(p, "g", allIds(p));
  const clip: Clip = {
    id, type: "graphic", start, duration, template: templateId, x: meta.anchor.x, y: meta.anchor.y,
    params: cleanParams(meta, { ...meta.sample, ...(params ?? {}) }), label: meta.name,
  };
  const n = p.tracks.filter(isGraphics).length;
  const placed = placeClip(p, clip, "graphics", () => ({ id: newId(p, "graphics"), kind: "graphics", name: n ? `Graphics ${n + 1}` : "Graphics", clips: [] }));
  return { project: placed.project, clipId: id };
}

/** Only what the template uses, inside the allowed ranges (as the engine's schema). */
export function cleanParams(meta: TemplateMeta, given: GraphicParams): GraphicParams {
  const out: GraphicParams = {};
  const allowed = new Set<string>([...meta.fields, ...meta.inputs.map((i) => i.key)]);
  for (const [k, v] of Object.entries(given) as [keyof GraphicParams, unknown][]) {
    if (!allowed.has(k) || v === undefined || v === null || v === "") continue;
    switch (k) {
      case "text":
        out.text = String(v).slice(0, 200);
        break;
      case "text2":
        out.text2 = String(v).slice(0, 120);
        break;
      case "items":
        out.items = (Array.isArray(v) ? v : String(v).split("\n")).map((x) => String(x).trim()).filter(Boolean).slice(0, 8).map((x) => x.slice(0, 80));
        break;
      case "number": {
        const n = Number(v);
        if (Number.isFinite(n)) out.number = n;
        break;
      }
      case "prefix":
        out.prefix = String(v).slice(0, 8);
        break;
      case "suffix":
        out.suffix = String(v).slice(0, 12);
        break;
      case "emoji":
        out.emoji = String(v).slice(0, 16);
        break;
      case "icon":
        if (CATALOG.icons.includes(String(v))) out.icon = String(v);
        break;
      case "font":
        if (String(v) in CATALOG.fonts) out.font = String(v);
        break;
      case "color":
      case "accent":
      case "bg":
        if (HEX.test(String(v))) out[k] = String(v).toLowerCase();
        break;
      case "size":
        out.size = r4(clamp(Number(v) || 1, 0.4, 2.5));
        break;
      case "intensity":
        out.intensity = r4(clamp(Number(v), 0, 1));
        break;
      case "angle":
        out.angle = r4(clamp(Number(v) || 0, -360, 360));
        break;
      case "align":
        if (["left", "center", "right"].includes(String(v))) out.align = v as GraphicParams["align"];
        break;
      case "case":
        if (["upper", "lower", "title"].includes(String(v))) out.case = v as GraphicParams["case"];
        break;
      case "dir":
        if (["left", "right", "up", "down"].includes(String(v))) out.dir = v as GraphicParams["dir"];
        break;
      case "image":
        out.image = String(v);
        break;
    }
  }
  return out;
}

export interface GraphicPatch {
  template?: string;
  params?: GraphicParams;
  x?: number;
  y?: number;
  attach?: { kind: AttachKind; intensity?: number } | null;
  label?: string;
}

function editable(p: Project, id: string) {
  const f = findClip(p, id);
  if (!f) throw new EditError("That clip is no longer on the timeline.");
  if (f.track.locked) throw new EditError(`The ${f.track.name ?? f.track.id} track is locked. Unlock it first.`);
  if (f.clip.locked) throw new EditError("This graphic is locked. Unlock it first.");
  return f;
}

/** Change a graphic: its template, words, colours, size, position or emphasis transition. */
export function setGraphic(p: Project, id: string, patch: GraphicPatch): Project {
  const { clip } = editable(p, id);
  if (clip.type !== "graphic") throw new EditError("That clip is not a graphic.");
  const template = patch.template ?? clip.template;
  const meta = templateMeta(template);
  if (!meta) throw new EditError(`There is no graphic called "${template}".`);
  if (patch.params?.image && !p.media.some((m) => m.id === patch.params?.image && m.kind === "image")) {
    throw new EditError("Choose a picture from your media for this graphic.");
  }
  const q = clone(p);
  const fix = (c: Clip): Clip => {
    const n: Clip = { ...c, template };
    const merged = { ...(c.params ?? {}), ...(patch.params ?? {}) };
    // a template change keeps the words but drops settings the new one does not have
    n.params = cleanParams(meta, patch.template && patch.template !== c.template ? { ...meta.sample, ...pickText(merged) } : merged);
    for (const k of Object.keys(patch.params ?? {}) as (keyof GraphicParams)[]) {
      if (patch.params?.[k] === "" || patch.params?.[k] === undefined) delete n.params[k];
    }
    if (patch.x !== undefined) n.x = r4(clamp(patch.x, -0.5, 1.5));
    if (patch.y !== undefined) n.y = r4(clamp(patch.y, -0.5, 1.5));
    if (patch.label !== undefined) {
      if (patch.label) n.label = patch.label.slice(0, 200);
      else delete n.label;
    }
    if (patch.attach === null) delete n.attach;
    else if (patch.attach) n.attach = { kind: patch.attach.kind, intensity: r4(clamp(patch.attach.intensity ?? 0.6, 0, 1)) };
    if (patch.template && patch.template !== c.template) {
      const d = clamp(c.duration, meta.minDuration, meta.maxDuration);
      n.duration = r4(d);
    }
    return n;
  };
  const out = { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? fix(c) : c)) })) };
  // a longer duration must not run into the next clip on the track
  const f = findClip(out, id)!;
  const next = f.track.clips.filter((c) => c.id !== id && c.start >= f.clip.start).sort((a, b) => a.start - b.start)[0];
  if (next && clipEnd(f.clip) > next.start + 0.002) f.clip.duration = r4(Math.max(1 / p.settings.fps, next.start - f.clip.start));
  return out;
}

function pickText(p: GraphicParams): GraphicParams {
  const { text, text2, items, number, prefix, suffix, emoji, image } = p;
  return Object.fromEntries(Object.entries({ text, text2, items, number, prefix, suffix, emoji, image }).filter(([, v]) => v !== undefined)) as GraphicParams;
}

/** Lock or unlock a clip (locked: no moving, trimming, changing or deleting; the AI keeps it). */
export function setClipLocked(p: Project, id: string, locked: boolean): Project {
  const f = findClip(p, id);
  if (!f) throw new EditError("That clip is no longer on the timeline.");
  const q = clone(p);
  return {
    ...q,
    tracks: q.tracks.map((t) => ({
      ...t,
      clips: t.clips.map((c) => {
        if (c.id !== id) return c;
        const n = { ...c };
        if (locked) n.locked = true;
        else delete n.locked;
        return n;
      }),
    })),
  };
}

/** Templates that could replace this graphic (same kind of thing, its inputs available). */
export function alternatives(p: Project, id: string): TemplateMeta[] {
  const f = findClip(p, id);
  const meta = templateMeta(f?.clip.template);
  if (!f || !meta) return [];
  const params = f.clip.params ?? {};
  const have = new Set(Object.keys(params));
  const group = (m: TemplateMeta) => (["card", "pill", "banner"].includes(m.category) ? "block" : m.category);
  return CATALOG.templates.filter((m) => {
    if (m.id === meta.id || group(m) !== group(meta)) return false;
    const need = m.inputs.filter((i) => i.required).map((i) => (i.key === "items" ? "items" : i.key));
    if (!need.every((k) => have.has(k) || (k === "text" && have.has("text")))) return false;
    if (m.numRange && params.number !== undefined && !(params.number >= m.numRange[0] && params.number <= m.numRange[1])) return false;
    return true;
  });
}

/**
 * "Another look": the next template of the same kind, never the same as the graphics just
 * before or after it (so two neighbours never look the same). Words and colours stay.
 */
export function anotherLook(p: Project, id: string): Project {
  const { clip } = editable(p, id);
  const all = p.tracks.filter(isGraphics).flatMap((t) => t.clips).sort((a, b) => a.start - b.start);
  const i = all.findIndex((c) => c.id === id);
  const near = new Set([all[i - 1]?.template, all[i + 1]?.template]);
  const options = alternatives(p, id).filter((m) => !near.has(m.id));
  if (!options.length) throw new EditError("No other look of this kind fits these words.");
  const mood = clip.director?.mood;
  const ranked = [...options.filter((m) => !mood || m.moods.includes(mood)), ...options.filter((m) => mood && !m.moods.includes(mood))];
  // step through the list in a fixed order, starting after the current template
  const order = CATALOG.templates.map((t) => t.id);
  const cur = order.indexOf(clip.template ?? "");
  const nextOne = ranked.slice().sort((a, b) => ((order.indexOf(a.id) - cur + order.length) % order.length) - ((order.indexOf(b.id) - cur + order.length) % order.length))[0];
  const params = clip.params ?? {};
  return setGraphic(p, id, { template: nextOne.id, params: { ...pickText(params), color: params.color, accent: params.accent, size: params.size } });
}

// ---------------------------------------------------------------- the before/after wipe

export const WIPE_DIRECTIONS = ["right", "left", "down", "up"] as const;

export function addWipe(p: Project, at: number, grade = "orange_teal", seconds = 3): { project: Project; clipId: string } {
  const total = projectDuration(p);
  const start = r4(clamp(at, 0, Math.max(0, total - 1)));
  const id = newId(p, "w", allIds(p));
  const clip: Clip = { id, type: "wipe", start, duration: r4(clamp(seconds, 1, Math.max(1, total - start))), grade, direction: "right", sweep: 0.9, stop: 0.5, intensity: 1, label: "Before / after" };
  const n = p.tracks.filter((t) => t.kind === "effect").length;
  const placed = placeClip(p, clip, "effect", () => ({ id: newId(p, "effects"), kind: "effect", name: n ? `Effects ${n + 1}` : "Effects", clips: [] }));
  return { project: placed.project, clipId: id };
}

export interface WipePatch {
  grade?: string;
  intensity?: number;
  direction?: (typeof WIPE_DIRECTIONS)[number];
  sweep?: number;
  stop?: number;
  divider?: boolean;
}

export function setWipe(p: Project, id: string, patch: WipePatch): Project {
  const { clip } = editable(p, id);
  if (clip.type !== "wipe") throw new EditError("That clip is not a before/after wipe.");
  const q = clone(p);
  const fix = (c: Clip): Clip => {
    const n: Clip = { ...c };
    if (patch.grade !== undefined) n.grade = patch.grade;
    if (patch.intensity !== undefined) n.intensity = r4(clamp(patch.intensity, 0, 1));
    if (patch.direction !== undefined) n.direction = patch.direction;
    if (patch.sweep !== undefined) n.sweep = r4(clamp(patch.sweep, 0.2, 3));
    if (patch.stop !== undefined) n.stop = r4(clamp(patch.stop, 0.05, 0.95));
    if (patch.divider !== undefined) {
      if (patch.divider) delete n.divider;
      else n.divider = false;
    }
    return n;
  };
  return { ...q, tracks: q.tracks.map((t) => ({ ...t, clips: t.clips.map((c) => (c.id === id ? fix(c) : c)) })) };
}

/** Where the wipe's divider is at t (0-1 across the frame along its direction), or null. */
export function wipeAt(project: Project, t: number): { clip: Clip; pos: number } | null {
  for (const track of project.tracks) {
    if (track.kind !== "effect" || track.hidden) continue;
    for (const c of track.clips) {
      if (c.type !== "wipe" || t < c.start || t >= clipEnd(c)) continue;
      const u = clamp((t - c.start) / (c.sweep ?? 0.8), 0, 1);
      const e = 1 - Math.pow(1 - u, 3);
      return { clip: c, pos: (c.stop ?? 0.5) * e };
    }
  }
  return null;
}

// ---------------------------------------------------------------- emphasis transitions

/** The synthetic effect clips for the graphics' flash / whip / punch-in (as the engine adds them). */
export function attachClips(p: Project): Clip[] {
  const fps = p.settings.fps;
  const out: Clip[] = [];
  for (const t of p.tracks) {
    if (!isGraphics(t) || t.hidden) continue;
    for (const c of t.clips) {
      if (c.type !== "graphic" || !c.attach) continue;
      const k = c.attach.intensity ?? 0.6;
      const id = `att-${c.id}`;
      if (c.attach.kind === "flash") out.push({ id, type: "fx", effect: "flash", start: c.start, duration: Math.max(3 / fps, 0.14), intensity: k });
      else if (c.attach.kind === "whip") out.push({ id, type: "fx", effect: "whip", start: c.start, duration: Math.max(4 / fps, 0.2), intensity: k });
      else out.push({ id, type: "zoom", start: c.start, duration: Math.min(c.duration, 0.5), amount: Math.round((1.04 + 0.12 * k) * 1000) / 1000, ease: 0.12 });
    }
  }
  return out;
}

/** The project plus a hidden effects track with those transitions (for the preview). */
export function withAttachments(p: Project): Project {
  const extra = attachClips(p);
  if (!extra.length) return p;
  return { ...p, tracks: [...p.tracks, { id: "attach-fx", kind: "effect", name: "Graphic transitions", clips: extra }] };
}

/** Graphics on screen at t, bottom track first (later tracks are drawn on top). */
export function graphicsAt(p: Project, t: number): Clip[] {
  const fps = p.settings.fps;
  const f = Math.floor(t * fps + 1e-6);
  const out: Clip[] = [];
  for (const track of p.tracks) {
    if (!isGraphics(track) || track.hidden) continue;
    for (const c of track.clips) {
      const f0 = Math.floor(c.start * fps + 0.5 + 1e-9);
      const f1 = Math.floor(clipEnd(c) * fps + 0.5 + 1e-9);
      if (c.type === "graphic" && f >= f0 && f < f1) out.push(c);
    }
  }
  return out;
}

export function graphicLabel(c: Clip): string {
  const meta = templateMeta(c.template);
  const text = (c.params?.text ?? c.params?.emoji ?? (c.params?.number !== undefined ? `${c.params.prefix ?? ""}${c.params.number}${c.params.suffix ?? ""}` : "")).replace(/\*/g, "");
  return `${meta?.name ?? c.template}${text ? `: ${text}` : ""}`;
}
