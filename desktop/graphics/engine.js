// The motion-graphics runtime: what a template is, how it is built, measured and animated.
//
// A template is `defineTemplate(meta, build)`. `build(c)` creates DOM inside `c.root` at a
// base scale of 1 (the frame is 1080 px wide; templates stay under 900 px) and returns
// `{ w, h, update(t) }`. `update(t)` draws the graphic `t` seconds after it starts: it is a
// pure function of t (no CSS transitions, no timers, no Math.random), so the same time always
// gives the same pixels - the preview, the cached frames and the export agree.
//
// Nothing here touches the DOM when the file is imported (the catalog builder imports the
// templates in plain Node to read their `meta`).

export const FRAME_W = 1080;
export const FRAME_H = 1920;
export const MAX_W = 900;             // widest a template is built at size 1
export const RENDERER_VERSION = 3;    // bump when frames of the same template could differ

/** The font choices. `family` names are declared in fonts.css. */
export const FONT_STACKS = {
  inter: { family: "GfxInter", weight: 600, label: "Clean (Inter)" },
  black: { family: "GfxInter", weight: 900, label: "Black (Inter)" },
  thin: { family: "GfxInter", weight: 100, label: "Thin (Inter)" },
  impact: { family: "GfxAnton", weight: 400, label: "Impact (Anton)" },
  display: { family: "GfxArchivo", weight: 400, label: "Display (Archivo Black)" },
  condensed: { family: "GfxBebas", weight: 400, label: "Condensed (Bebas Neue)" },
  heavy: { family: "GfxOswald", weight: 700, label: "Heavy (Oswald)" },
  serif: { family: "GfxPlayfair", weight: 800, label: "Serif (Playfair)" },
  mono: { family: "GfxMono", weight: 700, label: "Mono (JetBrains Mono)" },
  hand: { family: "GfxCaveat", weight: 700, label: "Handwritten (Caveat)" },
  comic: { family: "GfxBangers", weight: 400, label: "Comic (Bangers)" },
};
export const FONT_KEYS = Object.keys(FONT_STACKS);
const EMOJI_FALLBACK = '"Noto Color Emoji","Segoe UI Emoji","Apple Color Emoji","Twemoji Mozilla",sans-serif';

export function fontCss(key) {
  const f = FONT_STACKS[key] || FONT_STACKS.inter;
  return { fontFamily: `"${f.family}",${EMOJI_FALLBACK}`, fontWeight: String(f.weight) };
}

export const MOODS = ["hype", "calm", "urgent", "funny", "serious", "money", "tech", "emotion", "warning", "luxury", "news", "playful"];

/** Default values every template understands (a template's meta.defaults override them). */
export const BASE_DEFAULTS = {
  text: "", text2: "", items: [], number: 0, prefix: "", suffix: "", image: "", emoji: "", icon: "",
  font: "", color: "#ffffff", accent: "#ffd23f", bg: "#111827",
  size: 1, intensity: 0.7, align: "center", case: "", angle: 0, dir: "right",
};

export const registry = new Map();

/** Register a template. `meta` is JSON-serialisable (it becomes graphics_catalog.json). */
export function defineTemplate(meta, build) {
  if (!meta || !meta.id) throw new Error("a template needs an id");
  if (registry.has(meta.id)) throw new Error(`duplicate template id ${meta.id}`);
  const full = {
    version: 1, tl: meta.name, category: "text", moods: [], inputs: [{ key: "text", type: "text", required: true }],
    duration: 2, minDuration: 0.8, maxDuration: 8, zone: "any", anchor: { x: 0.5, y: 0.5 },
    box: { w: 600, h: 200 }, pad: 60, fields: ["text", "font", "color", "accent", "size", "intensity"],
    bg: false, words: false, maxChars: 40, minFont: 28, defaults: {}, sample: {}, ...meta,
  };
  registry.set(full.id, { meta: full, build });
  return full;
}

export const listTemplates = () => [...registry.values()].map((t) => t.meta);
export const getTemplate = (id) => registry.get(id);

// ---------------------------------------------------------------- parameters

const HEX = /^#[0-9a-fA-F]{6}$/;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));

/** Text as it is shown: trimmed, collapsed whitespace, case rule applied, length capped. */
export function shapeText(text, meta, caseRule) {
  let s = String(text ?? "").replace(/\s+/g, " ").trim();
  const cap = (meta && meta.maxChars) || 80;
  const plain = [...s].filter((ch) => ch !== "*").length;
  if (plain > cap) {
    let n = 0, out = "";
    for (const ch of [...s]) { if (ch !== "*") n++; if (n > cap - 1) break; out += ch; }
    s = out.trimEnd().replace(/\*([^*\s]*)$/u, "$1") + "…";
  }
  if (caseRule === "upper") s = s.toLocaleUpperCase("fil");
  else if (caseRule === "lower") s = s.toLocaleLowerCase("fil");
  else if (caseRule === "title") s = s.toLocaleLowerCase("fil").replace(/(^|\s)(\S)/gu, (m, a, b) => a + b.toLocaleUpperCase("fil"));
  return s;
}

/** The full parameter set for a template: defaults, then the user's values, made safe. */
export function resolveParams(meta, given = {}) {
  const p = { ...BASE_DEFAULTS, ...meta.defaults, ...Object.fromEntries(Object.entries(given || {}).filter(([, v]) => v !== undefined && v !== null)) };
  for (const k of ["color", "accent", "bg"]) if (!HEX.test(String(p[k]))) p[k] = (meta.defaults && meta.defaults[k]) || BASE_DEFAULTS[k];
  p.size = clamp(Number(p.size) || 1, 0.4, 2.5);
  p.intensity = clamp(Number.isFinite(Number(p.intensity)) ? Number(p.intensity) : 0.7, 0, 1);
  p.number = Number.isFinite(Number(p.number)) ? Number(p.number) : 0;
  p.angle = Number.isFinite(Number(p.angle)) ? Number(p.angle) : 0;
  if (!FONT_STACKS[p.font]) p.font = (meta.defaults && FONT_STACKS[meta.defaults.font] && meta.defaults.font) || "";
  if (!["left", "center", "right"].includes(p.align)) p.align = "center";
  p.text = shapeText(p.text, meta, p.case);
  p.text2 = shapeText(p.text2, { maxChars: 60 }, p.case === "upper" ? "" : "");
  p.items = (Array.isArray(p.items) ? p.items : []).slice(0, 8).map((x) => shapeText(x, { maxChars: 40 }, ""));
  p.prefix = String(p.prefix ?? "").slice(0, 8);
  p.suffix = String(p.suffix ?? "").slice(0, 12);
  p.emoji = String(p.emoji ?? "").slice(0, 16);
  return p;
}

// ---------------------------------------------------------------- math and easing

export const ease = {
  lin: (x) => x,
  out: (x) => 1 - Math.pow(1 - x, 3),
  in: (x) => x * x * x,
  inOut: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  back: (x, k = 1.70158) => 1 + (k + 1) * Math.pow(x - 1, 3) + k * Math.pow(x - 1, 2),
  elastic: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * ((2 * Math.PI) / 3)) + 1),
  bounce: (x) => {
    const n = 7.5625, d = 2.75;
    if (x < 1 / d) return n * x * x;
    if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75;
    if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375;
    return n * (x -= 2.625 / d) * x + 0.984375;
  },
};
export const c01 = (x) => clamp(x, 0, 1);
export const lerp = (a, b, x) => a + (b - a) * x;
/** 0..1 progress of t between a and b. */
export const prog = (t, a, b) => (b <= a ? (t >= b ? 1 : 0) : c01((t - a) / (b - a)));
/** Seeded random numbers (mulberry32): graphics never use Math.random. */
export function rng(seed) {
  let a = (seed >>> 0) || 1;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
/** In/out envelope for a graphic `dur` long: i = in progress, o = out progress (0 until the end). */
export function envelope(t, dur, tin = 0.3, tout = 0.25) {
  const tinC = Math.min(tin, dur * 0.4);
  const toutC = Math.min(tout, dur * 0.4);
  return { i: prog(t, 0, tinC), o: prog(t, dur - toutC, dur), alive: t >= 0 && t <= dur };
}

// ---------------------------------------------------------------- colours

export function hexToRgb(hex) {
  const h = String(hex).replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
export const rgba = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };
export function luminance(hex) {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const [r, g, b] = hexToRgb(hex);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
/** WCAG contrast ratio between two colours (1 - 21). */
export function contrast(a, b) {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
/** Black or white, whichever reads better on `bg`. */
export const readableOn = (bg) => (contrast("#ffffff", bg) >= contrast("#111111", bg) ? "#ffffff" : "#111111");
export function mix(a, b, x) {
  const A = hexToRgb(a), B = hexToRgb(b);
  return "#" + A.map((v, i) => Math.round(lerp(v, B[i], x)).toString(16).padStart(2, "0")).join("");
}

// ---------------------------------------------------------------- DOM helpers

export function mk(tag, css, text, parent) {
  const el = document.createElement(tag);
  if (css) Object.assign(el.style, css);
  if (text !== undefined && text !== null) el.textContent = text;
  if (parent) parent.appendChild(el);
  return el;
}

export function svgEl(tag, attrs, parent) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  if (parent) parent.appendChild(el);
  return el;
}

/** Simple self-drawn 24x24 icons (stroke icons). */
export const ICONS = {
  check: [["path", { d: "M5 13l4 4L19 7" }]],
  star: [["path", { d: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" }]],
  bolt: [["path", { d: "M13 2L4 14h7l-1 8 9-12h-7z" }]],
  heart: [["path", { d: "M12 21s-8-5.5-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.5-8 11-8 11z" }]],
  lock: [["rect", { x: 5, y: 11, width: 14, height: 10, rx: 2 }], ["path", { d: "M8 11V8a4 4 0 0 1 8 0v3" }]],
  bell: [["path", { d: "M6 17v-6a6 6 0 0 1 12 0v6l2 2H4z" }], ["path", { d: "M10 21a2 2 0 0 0 4 0" }]],
  play: [["path", { d: "M8 5v14l11-7z" }]],
  chat: [["path", { d: "M4 5h16v11H10l-5 4v-4H4z" }]],
  fire: [["path", { d: "M12 2c1 4 5 6 5 11a5 5 0 0 1-10 0c0-2 1-3 2-4 0 2 1 3 2 3 0-4-1-6 1-10z" }]],
  money: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M14.5 9c-.5-1-1.5-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1 0-2-.5-2.5-1.5M12 6v1.5M12 16.5V18" }]],
  rocket: [["path", { d: "M12 2c4 3 5 8 4 13l-4 3-4-3c-1-5 0-10 4-13z" }], ["path", { d: "M9 18l-3 4M15 18l3 4" }], ["circle", { cx: 12, cy: 10, r: 1.6 }]],
  warning: [["path", { d: "M12 3l10 18H2z" }], ["path", { d: "M12 10v5M12 18v.2" }]],
  clock: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M12 7v5l3.5 2" }]],
  mic: [["rect", { x: 9, y: 3, width: 6, height: 11, rx: 3 }], ["path", { d: "M6 11a6 6 0 0 0 12 0M12 17v4" }]],
  camera: [["rect", { x: 3, y: 7, width: 18, height: 13, rx: 2 }], ["circle", { cx: 12, cy: 13, r: 3.6 }], ["path", { d: "M8 7l1.5-3h5L16 7" }]],
  user: [["circle", { cx: 12, cy: 8, r: 4 }], ["path", { d: "M4 21c0-5 4-7 8-7s8 2 8 7" }]],
  thumb: [["path", { d: "M7 11v10H3V11zM7 11l4-8c2 0 3 1 3 3l-1 4h7l-2 11H7" }]],
  link: [["path", { d: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" }]],
  eye: [["path", { d: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" }], ["circle", { cx: 12, cy: 12, r: 3 }]],
  globe: [["circle", { cx: 12, cy: 12, r: 9 }], ["path", { d: "M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" }]],
  cart: [["path", { d: "M3 4h3l2.5 11h10L21 7H7" }], ["circle", { cx: 10, cy: 19, r: 1.5 }], ["circle", { cx: 17, cy: 19, r: 1.5 }]],
};
export const ICON_KEYS = Object.keys(ICONS);

export function icon(name, size, color, parent, { fill = false, stroke = 2.2 } = {}) {
  const s = svgEl("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: fill ? color : "none", stroke: color, "stroke-width": stroke, "stroke-linecap": "round", "stroke-linejoin": "round" }, parent);
  s.style.display = "block";
  for (const [tag, attrs] of ICONS[name] || ICONS.star) svgEl(tag, attrs, s);
  return s;
}

/**
 * Make `node`'s text fit a box: the biggest font size (between min and max) at which the text
 * wraps inside maxW and is no taller than maxH. Words are never broken unless a single word is
 * wider than the box even at the smallest size (then it may break anywhere, and `broke` says so).
 * Returns { size, shrunk, broke }.
 */
export function fitText(node, { maxW, maxH, min = 20, max = 160, lines = 0 }) {
  const st = node.style;
  st.width = `${maxW}px`;
  st.maxWidth = `${maxW}px`;
  st.overflowWrap = "normal";
  st.wordBreak = "keep-all";
  st.hyphens = "manual";
  st.whiteSpace = lines === 1 ? "nowrap" : "normal";
  const fits = (px) => {
    st.fontSize = `${px}px`;
    const w = node.scrollWidth, h = node.getBoundingClientRect().height;
    return w <= maxW + 0.5 && h <= maxH + 0.5;
  };
  let lo = min, hi = max, best = null;
  if (fits(max)) best = max;
  else {
    while (hi - lo > 0.5) {
      const mid = (lo + hi) / 2;
      if (fits(mid)) { best = mid; lo = mid; } else hi = mid;
    }
  }
  let broke = false;
  if (best === null) {
    best = min;
    if (!fits(min)) {
      st.overflowWrap = "anywhere";
      st.wordBreak = "normal";
      st.whiteSpace = "normal";
      broke = true;
      if (!fits(min)) { // still too tall: the smallest readable size is the limit; report it
        st.fontSize = `${min}px`;
      }
    }
  }
  st.fontSize = `${best}px`;
  // Shrink the box to the text (so its size, and where it may sit, are the real ones).
  const heightBefore = node.getBoundingClientRect().height;
  const range = document.createRange();
  range.selectNodeContents(node);
  let right = 0, left = Infinity;
  for (const r of range.getClientRects()) { right = Math.max(right, r.right); left = Math.min(left, r.left); }
  const tight = Math.ceil(right - node.getBoundingClientRect().left) + 8;
  if (tight > 8 && tight < maxW) {
    st.width = `${tight}px`;
    if (node.getBoundingClientRect().height > heightBefore + 1) st.width = `${maxW}px`;
  } else st.width = `${maxW}px`;
  return { size: best, shrunk: best < max - 0.5, broke };
}

/** Words of a text; a word written *like this* is marked as an emphasised word. */
export function parseWords(text) {
  return String(text).split(" ").filter(Boolean).map((w) => ({ t: w.replace(/\*/g, ""), em: /\*/.test(w) }));
}
/** Plain text without the emphasis marks. */
export const plainText = (text) => String(text).replace(/\*/g, "");

/** Split text into word spans (inline-block so a word never breaks). `span.em` marks emphasis. */
export function wordSpans(parent, text, css = {}) {
  const spans = [];
  const words = parseWords(text);
  words.forEach((w, i) => {
    const s = mk("span", { display: "inline-block", whiteSpace: "pre", ...css }, w.t, parent);
    s.em = w.em;
    spans.push(s);
    if (i < words.length - 1) parent.appendChild(document.createTextNode(" "));
  });
  return spans;
}

/** The emphasised word spans; with no marks, the longest word is the emphasis. */
export function emphasis(spans) {
  const marked = spans.filter((s) => s.em);
  if (marked.length) return marked;
  if (spans.length < 2) return spans.slice();
  return [spans.reduce((a, b) => (b.textContent.length > a.textContent.length ? b : a))];
}

/** Split into letter spans (for staggered reveals); spaces stay real spaces. */
export function letterSpans(parent, text, css = {}) {
  const out = [];
  for (const word of plainText(text).split(" ").filter(Boolean)) {
    const wrap = mk("span", { display: "inline-block", whiteSpace: "nowrap" }, null, parent);
    for (const ch of [...word]) out.push(mk("span", { display: "inline-block", ...css }, ch, wrap));
    parent.appendChild(document.createTextNode(" "));
  }
  return out;
}

export function setT(el, { x = 0, y = 0, s = 1, sx, sy, r = 0 } = {}) {
  el.style.transform = `translate(${x}px,${y}px) rotate(${r}deg) scale(${sx ?? s},${sy ?? s})`;
}

/** Text shadow that keeps text readable on any picture (stronger with `strength`). */
export const legible = (strength = 1) =>
  `0 2px ${6 * strength}px rgba(0,0,0,${0.55 * Math.min(1, strength)}),0 0 ${18 * strength}px rgba(0,0,0,${0.35 * Math.min(1, strength)})`;

// ---------------------------------------------------------------- instances

/**
 * Build a template into a tile. Returns
 *   { tile, w, h, pad, update(t), report, destroy() }
 * where tile is a (w+2pad) x (h+2pad) box whose content sits at (pad, pad) and is already
 * scaled by `size`. `report` tells how well the text fits (font size in px at the frame).
 */
export function instantiate(id, params, { doc = document, duration, quality = "final" } = {}) {
  const t = registry.get(id);
  if (!t) throw new Error(`unknown template '${id}'`);
  const { meta } = t;
  const p = resolveParams(meta, params);
  const dur = duration && duration > 0 ? duration : meta.duration;
  const report = { fontPx: null, shrunk: false, broke: false, lines: 0 };
  const inner = mk("div", { position: "absolute", left: "0px", top: "0px", transformOrigin: "0 0" });
  inner.className = "gfx-inner";
  const fam = fontCss(p.font || "inter");
  Object.assign(inner.style, { fontFamily: fam.fontFamily, fontWeight: fam.fontWeight, color: p.color });
  const tile = mk("div", { position: "relative", overflow: "visible", pointerEvents: "none" });
  tile.className = "gfx-tile";
  const stage = mk("div", { position: "absolute", left: "0px", top: "0px", visibility: "hidden" });
  stage.appendChild(inner);
  tile.appendChild(stage);
  doc.body.appendChild(tile); // measured while attached; the caller moves it
  const c = {
    p, meta, root: inner, dur, q: quality, final: quality === "final", report, id,
    fonts: fam, fit: (node, o) => {
      const r = fitText(node, { min: meta.minFont, ...o });
      if (report.fontPx === null || r.size < report.fontPx) report.fontPx = r.size;
      report.shrunk = report.shrunk || r.shrunk;
      report.broke = report.broke || r.broke;
      return r;
    },
    blur: (px) => (quality === "final" ? px : px * 0.5),
  };
  const out = t.build(c);
  const s = p.size;
  inner.style.transform = `scale(${s})`;
  const pad = meta.pad;
  const w = Math.ceil(out.w * s), h = Math.ceil(out.h * s);
  Object.assign(tile.style, { width: `${w + 2 * pad}px`, height: `${h + 2 * pad}px` });
  Object.assign(stage.style, { left: `${pad}px`, top: `${pad}px`, width: `${w}px`, height: `${h}px`, visibility: "visible" });
  if (report.fontPx !== null) report.fontPx = Math.round(report.fontPx * s * 10) / 10;
  const update = (time) => out.update(Math.max(0, Math.min(time, dur + 1)), dur);
  update(0);
  return {
    tile, w, h, pad, update, report, params: p, meta, duration: dur,
    destroy() { tile.remove(); },
  };
}
