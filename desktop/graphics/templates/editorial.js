// Premium Editorial: magazine typography, cream cards, floating screenshots, UI panels and the
// other graphics of the PREMIUM EDITORIAL VIRAL style. Calm, expensive-looking motion: soft
// shadows, rounded corners, serif headlines, one accent colour.
//
// Timing: a graphic's words / items / steps appear at `cues` (seconds from the graphic's start)
// when given - the Director fills them from the spoken words, so each element lands on the word
// that names it - and on an even schedule otherwise (cueTimes in engine.js).
//
// Pictures: `image` / `images` are the user's own files (screenshots, photos, logo). Without
// them a neutral placeholder is drawn; nothing is ever downloaded or invented.
import {
  defineTemplate, mk, icon, ease, prog, c01, lerp, envelope, setT, plainText, parseWords, fontCss,
  mix, rgba, readableOn, cueTimes,
} from "../engine.js";

const ONLY = ["premium_editorial"];          // the Director styles that use these (others: never)
const CREAM = "#f4efe6", INK = "#17140f", ACCENT = "#c8553d", PAPER = "#fbf8f2";
const SOFT = "0 26px 60px rgba(23,20,15,.30),0 6px 16px rgba(23,20,15,.16)";
const serif = fontCss("serif"), inter = fontCss("inter"), mono = fontCss("mono");
const dims = (el) => { const r = el.getBoundingClientRect(); return { w: Math.ceil(r.width), h: Math.ceil(r.height) }; };
const EDITORIAL_MOODS = ["luxury", "calm", "serious", "tech", "news", "money", "emotion"];
/** A soft eased "arrive" for an element appearing at time a (0 before, 1 after ~d seconds). */
const arrive = (t, a, d = 0.45) => ease.out(prog(t, a, a + d));

/** A picture box: the user's image (cover / contain), or a quiet placeholder with a number. */
function picture(parent, src, css, { fit = "cover", label = "" } = {}) {
  const box = mk("div", { position: "relative", overflow: "hidden", background: "linear-gradient(145deg,#e7dfd2,#cfc4b2)", ...css }, null, parent);
  if (src) {
    const img = mk("img", { position: "absolute", left: "0", top: "0", width: "100%", height: "100%", objectFit: fit, display: "block" }, null, box);
    img.src = src;
  } else if (label) {
    mk("div", { position: "absolute", inset: "0", display: "grid", placeItems: "center", color: "rgba(23,20,15,.35)", fontFamily: serif.fontFamily, fontWeight: "800", fontSize: "56px" }, label, box);
  }
  return box;
}

/** Fade + small push-in for a whole graphic (the shared editorial entrance / exit). */
function settle(el, t, dur, { tin = 0.5, tout = 0.4, from = 0.94, rise = 30 } = {}) {
  const e = envelope(t, dur, tin, tout);
  const k = ease.out(e.i);
  el.style.opacity = String(c01(e.i * 1.6) * (1 - ease.inOut(e.o)));
  setT(el, { s: lerp(from, 1, k) * (1 + 0.012 * c01(t / Math.max(dur, 0.1))) - 0.02 * ease.in(e.o), y: (1 - k) * rise - 12 * ease.in(e.o) });
  return e;
}

// ---------------------------------------------------------------- 1. editorial headline
defineTemplate({
  id: "editorial-headline", name: "Editorial headline", tl: "Editorial na headline", category: "text", styles: ONLY,
  moods: EDITORIAL_MOODS, zone: "any", anchor: { x: 0.5, y: 0.42 }, box: { w: 820, h: 360 }, duration: 3.2, maxDuration: 8,
  words: true, maxChars: 60, minFont: 34, bg: true, pad: 80,
  fields: ["text", "text2", "number", "font", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: CREAM, color: INK, accent: ACCENT, font: "serif", text2: "The idea", number: 0 },
  sample: { text: "Ang *sikreto* ng magandang video", text2: "Chapter one", number: 1 },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "820px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "28px", padding: "38px 46px 42px", boxShadow: SOFT }, null, c.root);
  const top = mk("div", { display: "flex", alignItems: "center", gap: "18px", marginBottom: "18px", fontFamily: inter.fontFamily }, null, card);
  const kicker = mk("div", { fontSize: "24px", fontWeight: "800", letterSpacing: "0.32em", textTransform: "uppercase", color: p.accent, whiteSpace: "nowrap" }, plainText(p.text2), top);
  if (!p.text2) kicker.style.display = "none";
  const rule = mk("div", { flex: "1", height: "2px", background: rgba(p.color, 0.25), transformOrigin: "0 50%" }, null, top);
  const no = mk("div", { fontSize: "24px", fontWeight: "700", letterSpacing: "0.12em", color: rgba(p.color, 0.55), fontFamily: serif.fontFamily, whiteSpace: "nowrap" }, p.number ? `No. ${String(Math.round(p.number)).padStart(2, "0")}` : "", top);
  const head = mk("div", { fontFamily: fontCss(p.font || "serif").fontFamily, fontWeight: "800", lineHeight: "1.08", letterSpacing: "-0.01em" }, null, card);
  const words = parseWords(p.text);
  const spans = words.map((w, i) => {
    const s = mk("span", { display: "inline-block", whiteSpace: "pre", ...(w.em ? { fontStyle: "italic", color: p.accent } : {}) }, w.t, head);
    if (i < words.length - 1) head.appendChild(document.createTextNode(" "));
    return s;
  });
  c.fit(head, { maxW: 728, maxH: 240, max: 92, min: 34 });
  const under = mk("div", { height: "3px", width: "120px", background: p.accent, marginTop: "22px", transformOrigin: "0 50%" }, null, card);
  const { w, h } = dims(card);
  const times = cueTimes(p, spans.length, c.dur, { from: 0.35, to: Math.min(c.dur * 0.55, 0.35 + spans.length * 0.16) });
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur);
      rule.style.transform = `scaleX(${arrive(t, 0.15, 0.8)})`;
      kicker.style.opacity = String(arrive(t, 0.1));
      no.style.opacity = String(arrive(t, 0.3));
      spans.forEach((s, i) => {
        const k = arrive(t, times[i], 0.5);
        s.style.opacity = String(k);
        setT(s, { y: (1 - k) * 26 });
      });
      under.style.transform = `scaleX(${arrive(t, times[times.length - 1] + 0.2, 0.6)})`;
    },
  };
});

// ---------------------------------------------------------------- 2. minimalist subtitle card
defineTemplate({
  id: "subtitle-card", name: "Subtitle card (cream)", tl: "Subtitle card (cream)", category: "text", styles: ONLY,
  moods: EDITORIAL_MOODS, zone: "lower", anchor: { x: 0.5, y: 0.72 }, box: { w: 760, h: 150 }, duration: 2.6, maxDuration: 8,
  words: true, maxChars: 70, minFont: 30, bg: true, pad: 70,
  fields: ["text", "font", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }],
  defaults: { bg: CREAM, color: INK, accent: ACCENT, font: "inter" },
  sample: { text: "Ito ang *pinaka-importante* sa lahat" },
}, (c) => {
  const { p } = c;
  const card = mk("div", { display: "inline-block", maxWidth: "760px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "26px", padding: "22px 34px 24px", boxShadow: SOFT, textAlign: "center" }, null, c.root);
  const line = mk("div", { fontFamily: fontCss(p.font || "inter").fontFamily, fontWeight: "650", lineHeight: "1.22" }, null, card);
  const words = parseWords(p.text);
  const spans = words.map((w, i) => {
    const s = mk("span", { display: "inline-block", whiteSpace: "pre", position: "relative", ...(w.em ? { fontFamily: serif.fontFamily, fontStyle: "italic", fontWeight: "800" } : {}) }, w.t, line);
    s.mark = mk("span", { position: "absolute", left: "-4px", right: "-4px", bottom: "0.08em", height: "0.32em", background: rgba(p.accent, 0.28), borderRadius: "4px", transformOrigin: "0 50%", zIndex: "-1" }, null, s);
    s.style.zIndex = "0";
    if (i < words.length - 1) line.appendChild(document.createTextNode(" "));
    return s;
  });
  c.fit(line, { maxW: 692, maxH: 128, max: 50, min: 30 });
  line.style.isolation = "isolate";
  const { w, h } = dims(card);
  const times = cueTimes(p, spans.length, c.dur, { from: 0.2, to: Math.max(0.3, c.dur - 0.6) });
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur, { tin: 0.35, tout: 0.3, from: 0.96, rise: 18 });
      spans.forEach((s, i) => {
        const spoken = t >= times[i];
        s.style.opacity = spoken ? "1" : "0.38";
        const markOn = words[i].em ? arrive(t, times[i], 0.35) : 0;
        s.mark.style.transform = `scaleX(${markOn})`;
      });
    },
  };
});

// ---------------------------------------------------------------- 3. kinetic words
defineTemplate({
  id: "kinetic-words", name: "Kinetic words (editorial)", tl: "Gumagalaw na salita (editorial)", category: "text", styles: ONLY,
  moods: ["hype", "luxury", "serious", "emotion", "money", "news"], zone: "center", anchor: { x: 0.5, y: 0.42 }, box: { w: 800, h: 360 },
  duration: 2.4, maxDuration: 6, words: true, maxChars: 40, minFont: 40, pad: 90,
  fields: ["text", "font", "color", "accent", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }],
  defaults: { color: "#ffffff", accent: "#f2c46d", font: "black" },
  sample: { text: "Hindi ito *magic* — ito ay *sistema*" },
}, (c) => {
  const { p } = c;
  const box = mk("div", { width: "800px", textAlign: "center", lineHeight: "1.02", wordSpacing: "0.14em", color: p.color, textShadow: "0 6px 24px rgba(0,0,0,.45)" }, null, c.root);
  const words = parseWords(p.text);
  const spans = words.map((w, i) => {
    const s = mk("span", { display: "inline-block", whiteSpace: "pre", transformOrigin: "50% 70%", ...(w.em ? { fontFamily: serif.fontFamily, fontStyle: "italic", fontWeight: "800", color: p.accent } : { fontFamily: fontCss(p.font || "black").fontFamily, fontWeight: fontCss(p.font || "black").fontWeight, textTransform: "uppercase", letterSpacing: "-0.01em" }) }, w.t, box);
    if (i < words.length - 1) box.appendChild(document.createTextNode(" "));
    return s;
  });
  c.fit(box, { maxW: 800, maxH: 340, max: 130, min: 40 });
  const { w, h } = dims(box);
  const times = cueTimes(p, spans.length, c.dur, { from: 0.05, to: Math.min(c.dur * 0.6, 0.05 + spans.length * 0.22) });
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.2, 0.3);
      box.style.opacity = String(1 - ease.inOut(e.o));
      spans.forEach((s, i) => {
        const a = prog(t, times[i], times[i] + 0.32);
        const k = ease.back(a, 1.6);
        s.style.opacity = String(c01(a * 3));
        setT(s, { s: a <= 0 ? 0.6 : lerp(1.35, 1, k) * (1 + 0.025 * c01((t - times[i]) / 1.2)), y: (1 - ease.out(a)) * 30 });
      });
    },
  };
});

// ---------------------------------------------------------------- 4. keyword marker highlight
defineTemplate({
  id: "marker-highlight", name: "Marker highlight", tl: "Marker na highlight", category: "text", styles: ONLY,
  moods: EDITORIAL_MOODS, zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 800, h: 230 }, duration: 2.8, maxDuration: 8,
  words: true, maxChars: 56, minFont: 32, bg: true, pad: 70,
  fields: ["text", "font", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }],
  defaults: { bg: PAPER, color: INK, accent: "#f6d36b", font: "serif" },
  sample: { text: "Ang tamang *timing* ang lahat" },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "800px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "24px", padding: "34px 42px", boxShadow: SOFT }, null, c.root);
  const line = mk("div", { fontFamily: fontCss(p.font || "serif").fontFamily, fontWeight: "800", lineHeight: "1.18", isolation: "isolate" }, null, card);
  const words = parseWords(p.text);
  const marked = [];
  words.forEach((w, i) => {
    const s = mk("span", { display: "inline-block", whiteSpace: "pre", position: "relative" }, w.t, line);
    if (w.em) {
      const m = mk("span", { position: "absolute", left: "-6px", right: "-6px", top: "18%", bottom: "6%", background: p.accent, borderRadius: "6px 14px 8px 12px", transformOrigin: "0 50%", zIndex: "-1", transform: "scaleX(0) skewX(-6deg)" }, null, s);
      marked.push(m);
    }
    if (i < words.length - 1) line.appendChild(document.createTextNode(" "));
  });
  if (!marked.length && line.children.length) {             // no *marks*: the longest word
    const longest = [...line.children].reduce((a, b) => (b.textContent.length > a.textContent.length ? b : a));
    marked.push(mk("span", { position: "absolute", left: "-6px", right: "-6px", top: "18%", bottom: "6%", background: p.accent, borderRadius: "6px 14px 8px 12px", transformOrigin: "0 50%", zIndex: "-1" }, null, longest));
  }
  c.fit(line, { maxW: 716, maxH: 170, max: 72, min: 32 });
  const { w, h } = dims(card);
  const times = cueTimes(p, marked.length, c.dur, { from: 0.55, to: Math.min(c.dur * 0.6, 0.55 + marked.length * 0.45) });
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur);
      marked.forEach((m, i) => { m.style.transform = `scaleX(${ease.inOut(prog(t, times[i], times[i] + 0.45))}) skewX(-6deg)`; });
    },
  };
});

// ---------------------------------------------------------------- 5. floating screenshot collage
const COLLAGE = [
  { x: -170, y: -120, r: -7, w: 430 }, { x: 170, y: -60, r: 5, w: 420 }, { x: -110, y: 170, r: 3, w: 400 }, { x: 190, y: 210, r: -5, w: 360 },
];
defineTemplate({
  id: "screenshot-collage", name: "Floating screenshot collage", tl: "Collage ng screenshots", category: "card", styles: ONLY,
  moods: ["tech", "money", "news", "serious", "luxury"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 860, h: 860 }, duration: 3.6, maxDuration: 8,
  maxChars: 40, bg: true, pad: 70, covers: true,
  fields: ["text", "images", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "images", type: "images", required: false }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT },
  sample: { text: "Real results" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { position: "relative", width: "860px", height: "860px" }, null, c.root);
  const pics = (p.images.length ? p.images : ["", "", ""]).slice(0, 4);
  const cards = pics.map((src, i) => {
    const L = COLLAGE[i];
    const card = mk("div", { position: "absolute", left: `${430 + L.x - L.w / 2}px`, top: `${430 + L.y - L.w * 0.34}px`, width: `${L.w}px`, padding: "10px", background: p.bg, borderRadius: "22px", boxShadow: SOFT, boxSizing: "border-box" }, null, wrap);
    picture(card, src, { width: "100%", height: `${Math.round(L.w * 0.62)}px`, borderRadius: "14px" }, { label: String(i + 1) });
    return card;
  });
  const label = mk("div", { position: "absolute", left: "0", right: "0", bottom: "6px", textAlign: "center", fontFamily: serif.fontFamily, fontWeight: "800", fontStyle: "italic", color: "#ffffff", textShadow: "0 4px 18px rgba(0,0,0,.5)" }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 800, maxH: 90, max: 64, min: 30, lines: 1 }); else label.style.display = "none";
  const times = cueTimes(p, cards.length, c.dur, { from: 0.1, to: Math.min(c.dur * 0.5, 0.1 + cards.length * 0.35) });
  return {
    w: 860, h: 860,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.4);
      wrap.style.opacity = String(1 - ease.inOut(e.o));
      cards.forEach((card, i) => {
        const L = COLLAGE[i];
        const k = arrive(t, times[i], 0.55);
        card.style.opacity = String(c01(k * 2));
        const drift = Math.sin(t * 0.9 + i * 1.7) * 6;
        setT(card, { y: (1 - k) * 140 + drift, r: L.r + (1 - k) * (i % 2 ? 9 : -9), s: lerp(0.86, 1, k) });
      });
      label.style.opacity = String(arrive(t, times[times.length - 1] + 0.2));
    },
  };
});

// ---------------------------------------------------------------- 6. animated mosaic grid
defineTemplate({
  id: "mosaic-grid", name: "Animated mosaic grid", tl: "Mosaic grid", category: "card", styles: ONLY,
  moods: ["luxury", "emotion", "tech", "money", "playful", "news"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 840, h: 840 }, duration: 3.4, maxDuration: 8,
  maxChars: 36, bg: true, pad: 60, covers: true, numRange: [0, 9],
  fields: ["text", "images", "number", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "images", type: "images", required: false }, { key: "text", type: "text", required: false }],
  defaults: { bg: CREAM, color: INK, accent: ACCENT, number: 0 },
  sample: { text: "Bawat detalye", number: 0 },
}, (c) => {
  const { p } = c;
  const n = Math.max(4, Math.min(9, p.images.length || 6));
  const cols = n <= 4 ? 2 : 3;
  const rows = Math.ceil(n / cols);
  const gap = 12, inner = 800 - gap * (cols - 1);
  const tile = Math.floor(inner / cols);
  const th = Math.round(tile * (rows === 2 && cols === 2 ? 1 : 0.95));
  const board = mk("div", { width: "840px", boxSizing: "border-box", padding: "20px", background: p.bg, borderRadius: "30px", boxShadow: SOFT }, null, c.root);
  const grid = mk("div", { display: "grid", gridTemplateColumns: `repeat(${cols},${tile}px)`, gap: `${gap}px` }, null, board);
  const tiles = [];
  for (let i = 0; i < n; i++) tiles.push(picture(grid, p.images[i] || "", { width: `${tile}px`, height: `${th}px`, borderRadius: "16px" }, { label: String(i + 1) }));
  const cap = mk("div", { marginTop: "16px", fontFamily: serif.fontFamily, fontWeight: "800", color: p.color, textAlign: "center" }, plainText(p.text), board);
  if (p.text) c.fit(cap, { maxW: 780, maxH: 70, max: 50, min: 28, lines: 1 }); else cap.style.display = "none";
  const { w, h } = dims(board);
  const focus = Math.round(p.number) - 1;
  const times = cueTimes(p, n, c.dur, { from: 0.15, to: Math.min(c.dur * 0.55, 0.15 + n * 0.12) });
  return {
    w, h,
    update(t, dur) {
      settle(board, t, dur, { tin: 0.35, from: 0.97, rise: 20 });
      tiles.forEach((el, i) => {
        const k = ease.back(prog(t, times[i], times[i] + 0.4), 1.2);
        el.style.opacity = String(c01(k * 2));
        const f = focus === i ? ease.inOut(prog(t, dur * 0.6, dur * 0.6 + 0.5)) : 0;
        setT(el, { s: lerp(0.6, 1, k) * (1 + 0.08 * f) });
        el.style.zIndex = focus === i ? "2" : "1";
        el.style.boxShadow = f > 0 ? `0 18px 40px rgba(0,0,0,${0.35 * f})` : "none";
      });
    },
  };
});

// ---------------------------------------------------------------- 7. search bar typing
defineTemplate({
  id: "search-bar", name: "Search bar (typing)", tl: "Search bar na nagta-type", category: "card", styles: ONLY,
  moods: ["tech", "news", "money", "serious", "calm"], zone: "any", anchor: { x: 0.5, y: 0.4 }, box: { w: 820, h: 240 }, duration: 3.2, maxDuration: 8,
  maxChars: 48, minFont: 30, bg: true, pad: 70,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "items", type: "list", required: false }],
  defaults: { bg: "#ffffff", color: "#202124", accent: "#4f7cff" },
  sample: { text: "paano mag-edit ng viral video", items: ["paano mag-edit ng viral video sa phone", "paano mag-edit ng reels"] },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { width: "820px", fontFamily: inter.fontFamily }, null, c.root);
  const bar = mk("div", { display: "flex", alignItems: "center", gap: "20px", background: p.bg, borderRadius: "60px", padding: "26px 34px", boxShadow: SOFT, boxSizing: "border-box" }, null, wrap);
  icon("search", 46, rgba(p.color, 0.55), bar, { stroke: 2.6 });
  const field = mk("div", { position: "relative", flex: "1", fontSize: "44px", fontWeight: "500", color: p.color, whiteSpace: "nowrap", overflow: "hidden" }, null, bar);
  const ghost = mk("div", { visibility: "hidden", whiteSpace: "nowrap" }, plainText(p.text), field);
  c.fit(ghost, { maxW: 640, maxH: 62, max: 46, min: 20, lines: 1 });   // a query stays on one line
  const live = mk("div", { position: "absolute", left: "0", top: "0", whiteSpace: "nowrap", fontSize: ghost.style.fontSize }, null, field);
  const typed = mk("span", {}, null, live);
  const caret = mk("span", { display: "inline-block", width: "3px", height: "1.05em", background: p.accent, verticalAlign: "-0.17em", marginLeft: "3px" }, null, live);
  const list = mk("div", { marginTop: "14px", background: p.bg, borderRadius: "28px", boxShadow: SOFT, overflow: "hidden" }, null, wrap);
  const rows = p.items.slice(0, 4).map((it) => {
    const row = mk("div", { display: "flex", alignItems: "center", gap: "18px", padding: "16px 30px", fontSize: "32px", color: rgba(p.color, 0.85), whiteSpace: "nowrap", overflow: "hidden" }, null, list);
    icon("search", 30, rgba(p.color, 0.4), row, { stroke: 2.4 });
    mk("span", { overflow: "hidden", textOverflow: "ellipsis" }, plainText(it), row);
    return row;
  });
  if (!rows.length) list.style.display = "none";
  const { w, h } = dims(wrap);
  const chars = [...plainText(p.text)];
  const typing = cueTimes(p, 2, c.dur, { from: 0.4, to: Math.min(c.dur * 0.65, 0.4 + chars.length * 0.055) });
  return {
    w, h,
    update(t, dur) {
      settle(wrap, t, dur, { tin: 0.35, from: 0.96, rise: 24 });
      const k = prog(t, typing[0], typing[1]);
      typed.textContent = chars.slice(0, Math.round(chars.length * k)).join("");
      caret.style.opacity = k >= 1 ? String(Math.floor(t * 2.2) % 2 ? 0 : 1) : "1";
      const show = arrive(t, typing[1] + 0.15, 0.35);
      list.style.opacity = String(show);
      setT(list, { y: (1 - show) * -14 });
      rows.forEach((r, i) => { r.style.opacity = String(arrive(t, typing[1] + 0.2 + i * 0.12, 0.3)); });
    },
  };
});

// ---------------------------------------------------------------- 8. floating UI panel
defineTemplate({
  id: "ui-panel", name: "Floating UI panel", tl: "Lumulutang na UI panel", category: "card", styles: ONLY,
  moods: ["tech", "money", "serious", "calm", "news"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 760, h: 470 }, duration: 3.6, maxDuration: 8,
  maxChars: 32, bg: true, pad: 70,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: "#2f8f6b", text: "Settings" },
  sample: { text: "Your setup", items: ["Good lighting", "Clear audio", "Strong hook"] },
}, (c) => {
  const { p } = c;
  const win = mk("div", { width: "760px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "30px", boxShadow: SOFT, overflow: "hidden", fontFamily: inter.fontFamily }, null, c.root);
  const bar = mk("div", { display: "flex", alignItems: "center", gap: "12px", padding: "20px 26px", background: mix(p.bg, "#000000", 0.04), borderBottom: `1px solid ${rgba(p.color, 0.08)}` }, null, win);
  for (const col of ["#ff5f57", "#febc2e", "#28c840"]) mk("div", { width: "16px", height: "16px", borderRadius: "50%", background: col }, null, bar);
  const title = mk("div", { marginLeft: "14px", fontSize: "28px", fontWeight: "700", opacity: "0.7", whiteSpace: "nowrap" }, plainText(p.text), bar);
  c.fit(title, { maxW: 560, maxH: 40, max: 30, min: 22, lines: 1 });
  const body = mk("div", { padding: "14px 30px 26px" }, null, win);
  const rows = (p.items.length ? p.items : [p.text || "Ready"]).slice(0, 6).map((it) => {
    const row = mk("div", { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "18px", padding: "16px 0", borderBottom: `1px solid ${rgba(p.color, 0.07)}` }, null, body);
    const label = mk("div", { fontSize: "36px", fontWeight: "600", whiteSpace: "nowrap" }, plainText(it), row);
    c.fit(label, { maxW: 520, maxH: 50, max: 38, min: 24, lines: 1 });
    label.style.width = "auto";
    const sw = mk("div", { width: "86px", height: "48px", borderRadius: "24px", background: rgba(p.color, 0.15), position: "relative", flex: "none" }, null, row);
    const knob = mk("div", { position: "absolute", left: "5px", top: "5px", width: "38px", height: "38px", borderRadius: "50%", background: "#ffffff", boxShadow: "0 2px 6px rgba(0,0,0,.25)" }, null, sw);
    return { sw, knob };
  });
  const track = mk("div", { height: "10px", borderRadius: "5px", background: rgba(p.color, 0.1), marginTop: "20px", overflow: "hidden" }, null, body);
  const fill = mk("div", { height: "100%", width: "100%", background: p.accent, transformOrigin: "0 50%", transform: "scaleX(0)" }, null, track);
  const { w, h } = dims(win);
  const times = cueTimes(p, rows.length, c.dur, { from: 0.6, to: Math.min(c.dur * 0.7, 0.6 + rows.length * 0.45) });
  return {
    w, h,
    update(t, dur) {
      settle(win, t, dur);
      let on = 0;
      rows.forEach((r, i) => {
        const k = ease.inOut(prog(t, times[i], times[i] + 0.3));
        on += k;
        r.sw.style.background = mix("#d9d6d0", p.accent, k);
        setT(r.knob, { x: 38 * k });
      });
      fill.style.transform = `scaleX(${on / rows.length})`;
    },
  };
});

// ---------------------------------------------------------------- 9. editorial checklist
defineTemplate({
  id: "editorial-checklist", name: "Editorial checklist", tl: "Editorial na checklist", category: "data", styles: ONLY,
  moods: EDITORIAL_MOODS, zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 760, h: 440 }, duration: 3.8, maxDuration: 8,
  maxChars: 32, bg: true, pad: 70,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: PAPER, color: INK, accent: ACCENT },
  sample: { text: "Bago ka mag-post", items: ["Malakas na hook", "Malinaw na audio", "Isang call to action"] },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "760px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "28px", padding: "34px 42px 30px", boxShadow: SOFT }, null, c.root);
  const head = mk("div", { display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "16px", marginBottom: "10px" }, null, card);
  const title = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", fontSize: "48px", whiteSpace: "nowrap" }, plainText(p.text), head);
  if (p.text) c.fit(title, { maxW: 520, maxH: 64, max: 50, min: 28, lines: 1 }); else title.style.visibility = "hidden";
  const count = mk("div", { fontFamily: mono.fontFamily, fontSize: "26px", color: rgba(p.color, 0.55), whiteSpace: "nowrap" }, "", head);
  const items = (p.items.length ? p.items : [p.text]).slice(0, 6);
  const rows = items.map((it) => {
    const row = mk("div", { display: "flex", alignItems: "center", gap: "22px", padding: "14px 0", borderTop: `1px solid ${rgba(p.color, 0.1)}` }, null, card);
    const ring = mk("div", { width: "50px", height: "50px", borderRadius: "50%", border: `3px solid ${rgba(p.color, 0.3)}`, boxSizing: "border-box", display: "grid", placeItems: "center", flex: "none" }, null, row);
    const tick = icon("check", 30, "#ffffff", ring, { stroke: 3.4 });
    const path = tick.querySelector("path");
    path.setAttribute("stroke-dasharray", "20");
    const label = mk("div", { fontFamily: inter.fontFamily, fontWeight: "600", whiteSpace: "nowrap" }, plainText(it), row);
    c.fit(label, { maxW: 560, maxH: 52, max: 40, min: 24, lines: 1 });
    label.style.width = "auto";
    return { row, ring, path, label };
  });
  const { w, h } = dims(card);
  const times = cueTimes(p, rows.length, c.dur, { from: 0.7, to: Math.min(c.dur * 0.75, 0.7 + rows.length * 0.55) });
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur);
      let done = 0;
      rows.forEach((r, i) => {
        const shown = arrive(t, 0.25 + i * 0.1, 0.4);
        r.row.style.opacity = String(shown);
        const k = ease.out(prog(t, times[i], times[i] + 0.35));
        if (k > 0) done++;
        r.ring.style.background = k > 0 ? mix(p.bg, p.accent, c01(k * 2)) : "transparent";
        r.ring.style.borderColor = k > 0 ? p.accent : rgba(p.color, 0.3);
        r.path.setAttribute("stroke-dashoffset", String(20 * (1 - k)));
        r.label.style.opacity = String(lerp(0.55, 1, k));
      });
      count.textContent = `${done}/${rows.length}`;
    },
  };
});

// ---------------------------------------------------------------- 10. countdown timer
defineTemplate({
  id: "countdown-timer", name: "Countdown timer", tl: "Countdown timer", category: "data", styles: ONLY,
  moods: ["urgent", "money", "hype", "serious", "tech"], zone: "any", anchor: { x: 0.5, y: 0.42 }, box: { w: 520, h: 600 }, duration: 3.4, maxDuration: 12,
  maxChars: 28, bg: true, pad: 70, numRange: [1, 5999],
  fields: ["text", "number", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "number", type: "number", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: CREAM, color: INK, accent: ACCENT, number: 10 },
  sample: { number: 10, text: "Huling tsansa" },
}, (c) => {
  const { p } = c;
  const total = Math.max(1, Math.round(p.number));
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "22px", minWidth: "440px" }, null, c.root);
  const dial = mk("div", { position: "relative", width: "440px", height: "440px", borderRadius: "50%", background: p.bg, boxShadow: SOFT }, null, wrap);
  const R = 190, L = 2 * Math.PI * R;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 440 440");
  Object.assign(svg.style, { position: "absolute", left: "0", top: "0", width: "440px", height: "440px", transform: "rotate(-90deg)" });
  dial.appendChild(svg);
  const ring = (stroke, width) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    for (const [k, v] of Object.entries({ cx: 220, cy: 220, r: R, fill: "none", stroke, "stroke-width": width, "stroke-linecap": "round" })) el.setAttribute(k, String(v));
    svg.appendChild(el);
    return el;
  };
  ring(rgba(p.color, 0.1), 14);
  const arc = ring(p.accent, 14);
  arc.setAttribute("stroke-dasharray", String(L));
  const digits = mk("div", { position: "absolute", inset: "0", display: "grid", placeItems: "center", fontFamily: mono.fontFamily, fontWeight: "700", color: p.color, fontSize: total >= 60 ? "104px" : "150px", letterSpacing: "-0.03em" }, "", dial);
  const label = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", fontStyle: "italic", color: "#ffffff", textShadow: "0 4px 18px rgba(0,0,0,.5)", whiteSpace: "nowrap" }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 700, maxH: 80, max: 60, min: 28, lines: 1 }); else label.style.display = "none";
  const fmt = (s) => (total >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : String(s));
  const { w, h } = dims(wrap);
  return {
    w: Math.max(w, 440), h,
    update(t, dur) {
      settle(wrap, t, dur, { tin: 0.35, from: 0.9, rise: 20 });
      // spoken countdown ("tatlo... dalawa... isa"): each number shows on its own word (cues);
      // otherwise the time shown runs over the graphic
      const said = p.cues.length >= 2 ? p.cues.filter((x) => x <= t + 1e-6).length : -1;
      const run = said >= 0 ? c01(said / p.cues.length) : prog(t, 0.3, Math.max(0.6, dur - 0.35));
      const left = said >= 0 ? Math.max(total - p.cues.length + 1, total - Math.max(0, said - 1)) : Math.max(0, Math.ceil(total * (1 - run) - 1e-9));
      digits.textContent = fmt(left);
      arc.setAttribute("stroke-dashoffset", String(L * run));
      const last = said > 0 ? p.cues[said - 1] : null;
      const tick = said >= 0 ? (last === null ? 1 : c01((t - last) / 0.25)) : (total * run) % 1;
      setT(digits, { s: 1 + (said >= 0 ? 0.14 : 0.06) * (1 - ease.out(c01(said >= 0 ? tick : tick * 4))) * (run < 1 || said >= 0 ? 1 : 0) });
    },
  };
});

// ---------------------------------------------------------------- 11. storyboard document
defineTemplate({
  id: "storyboard-doc", name: "Storyboard document", tl: "Storyboard na dokumento", category: "card", styles: ONLY,
  moods: ["calm", "tech", "serious", "news", "luxury"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 760, h: 980 }, duration: 4, maxDuration: 8,
  maxChars: 36, bg: true, pad: 70, covers: true,
  fields: ["text", "text2", "items", "images", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: false }, { key: "images", type: "images", required: false }, { key: "text", type: "text", required: false }],
  defaults: { bg: PAPER, color: INK, accent: ACCENT, text: "Storyboard", text2: "Scene plan" },
  sample: { text: "Storyboard", text2: "Scene plan", items: ["Hook: ang tanong", "Proof: ang resulta", "CTA: i-follow"] },
}, (c) => {
  const { p } = c;
  const page = mk("div", { width: "760px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "18px", padding: "40px 44px 36px", boxShadow: SOFT, fontFamily: inter.fontFamily }, null, c.root);
  const top = mk("div", { display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `2px solid ${p.color}`, paddingBottom: "12px", marginBottom: "20px" }, null, page);
  const title = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", fontSize: "54px", whiteSpace: "nowrap" }, plainText(p.text), top);
  c.fit(title, { maxW: 470, maxH: 70, max: 56, min: 28, lines: 1 });
  mk("div", { fontSize: "22px", fontWeight: "800", letterSpacing: "0.24em", textTransform: "uppercase", color: p.accent, whiteSpace: "nowrap" }, plainText(p.text2), top);
  const n = Math.max(1, Math.min(3, Math.max(p.items.length, p.images.length) || 3));
  const panels = [];
  for (let i = 0; i < n; i++) {
    const row = mk("div", { display: "flex", gap: "22px", alignItems: "center", padding: "14px 0", borderBottom: `1px dashed ${rgba(p.color, 0.25)}` }, null, page);
    const frame = picture(row, p.images[i] || "", { width: "250px", height: "180px", borderRadius: "10px", border: `2px solid ${rgba(p.color, 0.2)}`, flex: "none", boxSizing: "border-box" }, { label: String(i + 1) });
    const col = mk("div", { flex: "1", minWidth: "0" }, null, row);
    mk("div", { fontFamily: mono.fontFamily, fontSize: "20px", color: rgba(p.color, 0.5), marginBottom: "8px" }, `SCENE ${String(i + 1).padStart(2, "0")}`, col);
    const cap = mk("div", { fontSize: "32px", fontWeight: "600", lineHeight: "1.2" }, plainText(p.items[i] || ""), col);
    c.fit(cap, { maxW: 380, maxH: 120, max: 34, min: 22 });
    panels.push({ row, frame });
  }
  const { w, h } = dims(page);
  const times = cueTimes(p, panels.length, c.dur, { from: 0.6, to: Math.min(c.dur * 0.7, 0.6 + panels.length * 0.6) });
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.55, 0.4);
      const k = ease.out(e.i);
      page.style.opacity = String(c01(e.i * 1.6) * (1 - ease.inOut(e.o)));
      setT(page, { y: (1 - k) * 160, r: lerp(-4, -1.2, k), s: lerp(0.94, 1, k) });
      panels.forEach((pn, i) => {
        const a = arrive(t, times[i], 0.45);
        pn.row.style.opacity = String(lerp(0.15, 1, a));
        setT(pn.frame, { s: lerp(0.85, 1, a) });
      });
    },
  };
});

// ---------------------------------------------------------------- 12. phone mockup (generic)
defineTemplate({
  id: "phone-mockup", name: "Floating phone (generic)", tl: "Lumulutang na phone", category: "card", styles: ONLY,
  moods: ["tech", "money", "playful", "hype", "luxury"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 520, h: 1000 }, duration: 3.6, maxDuration: 8,
  maxChars: 32, bg: true, pad: 80, covers: true,
  fields: ["text", "image", "color", "accent", "bg", "size", "intensity"],
  inputs: [{ key: "image", type: "image", required: false }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#16171b", color: "#ffffff", accent: ACCENT },
  sample: { text: "Sa app mismo" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "22px", width: "520px" }, null, c.root);
  const body = mk("div", { position: "relative", width: "430px", height: "880px", borderRadius: "68px", background: p.bg, boxShadow: `${SOFT},inset 0 0 0 3px rgba(255,255,255,.08)`, padding: "18px", boxSizing: "border-box" }, null, wrap);
  for (const [top, hgt] of [[190, 80], [290, 110]]) mk("div", { position: "absolute", left: "-6px", top: `${top}px`, width: "6px", height: `${hgt}px`, borderRadius: "3px 0 0 3px", background: mix(p.bg, "#ffffff", 0.15) }, null, body);
  mk("div", { position: "absolute", right: "-6px", top: "240px", width: "6px", height: "130px", borderRadius: "0 3px 3px 0", background: mix(p.bg, "#ffffff", 0.15) }, null, body);
  const screen = picture(body, p.image, { width: "100%", height: "100%", borderRadius: "52px" }, { label: "" });
  mk("div", { position: "absolute", left: "50%", top: "34px", width: "120px", height: "34px", marginLeft: "-60px", borderRadius: "17px", background: "#0b0b0d" }, null, body);
  const glare = mk("div", { position: "absolute", inset: "18px", borderRadius: "52px", background: "linear-gradient(115deg,rgba(255,255,255,.18) 0%,rgba(255,255,255,0) 38%)", pointerEvents: "none" }, null, body);
  const label = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", fontStyle: "italic", color: p.color, textShadow: "0 4px 18px rgba(0,0,0,.5)", whiteSpace: "nowrap" }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 700, maxH: 80, max: 56, min: 28, lines: 1 }); else label.style.display = "none";
  const { w, h } = dims(wrap);
  return {
    w: Math.max(w, 520), h,
    update(t, dur) {
      const e = envelope(t, dur, 0.6, 0.4);
      const k = ease.out(e.i);
      wrap.style.opacity = String(c01(e.i * 1.6) * (1 - ease.inOut(e.o)));
      setT(body, { y: (1 - k) * 220 + Math.sin(t * 1.1) * 8, r: lerp(9, -2.5, k) + Math.sin(t * 0.8) * 0.6, s: lerp(0.88, 1, k) });
      glare.style.opacity = String(0.6 + 0.4 * Math.sin(t * 0.9));
      setT(screen, { s: 1 + 0.02 * c01(t / dur) });
      label.style.opacity = String(arrive(t, 0.5));
    },
  };
});

// ---------------------------------------------------------------- 13. logo badge (the user's own logo)
defineTemplate({
  id: "logo-badge", name: "Logo badge (your logo)", tl: "Logo badge (sariling logo)", category: "card", styles: ONLY,
  moods: ["tech", "money", "luxury", "serious", "news", "playful"], zone: "upper", anchor: { x: 0.5, y: 0.2 }, box: { w: 560, h: 170 }, duration: 2.8, maxDuration: 8,
  maxChars: 28, bg: true, pad: 60,
  fields: ["text", "text2", "image", "color", "accent", "bg", "size", "intensity"],
  inputs: [{ key: "image", type: "image", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT },
  sample: { text: "Your Brand", text2: "Official partner", image: "" },
}, (c) => {
  const { p } = c;
  const pill = mk("div", { display: "inline-flex", alignItems: "center", gap: "22px", background: p.bg, color: p.color, borderRadius: "40px", padding: "18px 34px 18px 18px", boxShadow: SOFT, fontFamily: inter.fontFamily, maxWidth: "560px", boxSizing: "border-box" }, null, c.root);
  const tile = picture(pill, p.image, { width: "112px", height: "112px", borderRadius: "28px", background: "#ffffff", flex: "none", boxShadow: "inset 0 0 0 1px rgba(0,0,0,.08)" }, { fit: "contain" });
  const col = mk("div", { minWidth: "0" }, null, pill);
  const name = mk("div", { fontSize: "40px", fontWeight: "800", whiteSpace: "nowrap" }, plainText(p.text), col);
  c.fit(name, { maxW: 360, maxH: 56, max: 42, min: 24, lines: 1 });
  const sub = mk("div", { fontSize: "24px", fontWeight: "600", color: rgba(p.color, 0.55), whiteSpace: "nowrap", marginTop: "4px" }, plainText(p.text2), col);
  if (!p.text2) sub.style.display = "none";
  if (!p.text && !p.text2) col.style.display = "none";
  const { w, h } = dims(pill);
  return {
    w, h,
    update(t, dur) {
      settle(pill, t, dur, { tin: 0.45, from: 0.9, rise: 18 });
      setT(tile, { s: lerp(0.6, 1, ease.back(prog(t, 0.05, 0.5), 1.5)), r: lerp(-12, 0, ease.out(prog(t, 0.05, 0.5))) });
      col.style.opacity = String(arrive(t, 0.25));
    },
  };
});

// ---------------------------------------------------------------- 14. screenshot montage
defineTemplate({
  id: "screenshot-montage", name: "Screenshot montage", tl: "Montage ng screenshots", category: "card", styles: ONLY,
  moods: ["tech", "money", "news", "serious", "hype"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 820, h: 700 }, duration: 4, maxDuration: 10,
  maxChars: 36, bg: true, pad: 70, covers: true,
  fields: ["text", "images", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "images", type: "images", required: false }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT },
  sample: { text: "Isa-isa nating tingnan" },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "820px", boxSizing: "border-box", background: p.bg, borderRadius: "30px", padding: "16px", boxShadow: SOFT }, null, c.root);
  const viewport = mk("div", { position: "relative", width: "788px", height: "560px", borderRadius: "20px", overflow: "hidden", background: "#e9e4da" }, null, card);
  const pics = (p.images.length ? p.images : ["", "", ""]).slice(0, 6);
  const slides = pics.map((src, i) => picture(viewport, src, { position: "absolute", left: "0", top: "0", width: "788px", height: "560px" }, { label: String(i + 1) }));
  const foot = mk("div", { display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px", padding: "18px 10px 6px" }, null, card);
  const cap = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", color: p.color, whiteSpace: "nowrap" }, plainText(p.text), foot);
  if (p.text) c.fit(cap, { maxW: 560, maxH: 60, max: 44, min: 24, lines: 1 }); else cap.style.visibility = "hidden";
  const dotsBox = mk("div", { display: "flex", gap: "10px" }, null, foot);
  const dots = pics.map(() => mk("div", { width: "14px", height: "14px", borderRadius: "7px", background: rgba(p.color, 0.18) }, null, dotsBox));
  const { w, h } = dims(card);
  const times = cueTimes(p, slides.length, c.dur, { from: 0, to: c.dur * 0.82, spread: true });
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur, { tin: 0.4, from: 0.95, rise: 26 });
      let cur = 0;
      times.forEach((tm, i) => { if (t >= tm) cur = i; });
      slides.forEach((s, i) => {
        const inK = i === 0 ? 1 : ease.inOut(prog(t, times[i], times[i] + 0.45));
        const next = i + 1 < slides.length ? ease.inOut(prog(t, times[i + 1], times[i + 1] + 0.45)) : 0;
        s.style.opacity = i <= cur + 1 ? "1" : "0";
        setT(s, { x: (1 - inK) * 788 - next * 160, s: 1 + 0.03 * c01((t - times[i]) / 2) });
        s.style.zIndex = String(i);
      });
      dots.forEach((d, i) => { d.style.background = i === cur ? p.accent : rgba(p.color, 0.18); d.style.width = i === cur ? "34px" : "14px"; });
    },
  };
});

// ---------------------------------------------------------------- 15. colour palette card
defineTemplate({
  id: "palette-card", name: "Colour palette", tl: "Palette ng kulay", category: "data", styles: ONLY,
  moods: ["luxury", "calm", "playful", "emotion", "tech"], zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 800, h: 520 }, duration: 3.4, maxDuration: 8,
  maxChars: 32, bg: true, pad: 70,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: PAPER, color: INK, accent: ACCENT },
  sample: { text: "Ang palette", items: ["#1f2a44", "#c8553d", "#f2c46d", "#e8dcc8", "#6b8f71"] },
}, (c) => {
  const { p } = c;
  const HEXRE = /^#[0-9a-fA-F]{6}$/;
  const colours = p.items.map((x) => String(x).trim()).filter((x) => HEXRE.test(x)).slice(0, 6);
  if (!colours.length) colours.push("#1f2a44", "#c8553d", "#e8dcc8");
  const card = mk("div", { width: "800px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "28px", padding: "32px 36px", boxShadow: SOFT }, null, c.root);
  const title = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", fontSize: "48px", whiteSpace: "nowrap", marginBottom: "22px" }, plainText(p.text), card);
  if (p.text) c.fit(title, { maxW: 728, maxH: 64, max: 50, min: 26, lines: 1 }); else title.style.display = "none";
  const row = mk("div", { display: "flex", gap: "14px", alignItems: "flex-end", height: "300px" }, null, card);
  const sw = colours.map((col) => {
    const cell = mk("div", { flex: "1", display: "flex", flexDirection: "column", gap: "12px" }, null, row);
    const bar = mk("div", { height: "250px", borderRadius: "18px", background: col, boxShadow: "inset 0 0 0 1px rgba(0,0,0,.08)", transformOrigin: "50% 100%" }, null, cell);
    mk("div", { fontFamily: mono.fontFamily, fontSize: colours.length > 4 ? "18px" : "22px", textAlign: "center", color: rgba(p.color, 0.75), whiteSpace: "nowrap" }, col.toUpperCase(), cell);
    return { cell, bar };
  });
  const { w, h } = dims(card);
  const times = cueTimes(p, sw.length, c.dur, { from: 0.35, to: Math.min(c.dur * 0.55, 0.35 + sw.length * 0.14) });
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur);
      sw.forEach((s, i) => {
        const k = ease.back(prog(t, times[i], times[i] + 0.5), 1.1);
        s.cell.style.opacity = String(c01(k * 2));
        s.bar.style.transform = `scaleY(${lerp(0.15, 1, k)})`;
      });
    },
  };
});

// ---------------------------------------------------------------- 16. social profile card
defineTemplate({
  id: "profile-card", name: "Social profile card", tl: "Profile card", category: "card", styles: ONLY,
  moods: ["playful", "hype", "tech", "money", "emotion", "calm"], zone: "any", anchor: { x: 0.5, y: 0.3 }, box: { w: 720, h: 240 }, duration: 3, maxDuration: 8,
  maxChars: 28, bg: true, pad: 70,
  fields: ["text", "text2", "image", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }, { key: "image", type: "image", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT, text2: "@yourhandle" },
  sample: { text: "Your Name", text2: "@yourhandle", items: ["12.4K followers"] },
}, (c) => {
  const { p } = c;
  const card = mk("div", { display: "flex", alignItems: "center", gap: "26px", width: "720px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "34px", padding: "26px 30px", boxShadow: SOFT, fontFamily: inter.fontFamily }, null, c.root);
  const initials = plainText(p.text).split(/\s+/).filter(Boolean).slice(0, 2).map((x) => [...x][0].toUpperCase()).join("");
  const avatar = p.image
    ? picture(card, p.image, { width: "130px", height: "130px", borderRadius: "50%", flex: "none", boxShadow: `0 0 0 5px ${p.bg},0 0 0 8px ${p.accent}` })
    : mk("div", { width: "130px", height: "130px", borderRadius: "50%", flex: "none", background: p.accent, color: readableOn(p.accent), display: "grid", placeItems: "center", fontSize: "52px", fontWeight: "800", boxShadow: `0 0 0 5px ${p.bg},0 0 0 8px ${mix(p.accent, "#ffffff", 0.5)}` }, initials, card);
  const col = mk("div", { flex: "1", minWidth: "0" }, null, card);
  const name = mk("div", { fontSize: "42px", fontWeight: "800", whiteSpace: "nowrap" }, plainText(p.text), col);
  c.fit(name, { maxW: 330, maxH: 56, max: 44, min: 24, lines: 1 });
  mk("div", { fontSize: "28px", fontWeight: "600", color: rgba(p.color, 0.55), whiteSpace: "nowrap", marginTop: "4px" }, plainText(p.text2), col);
  if (p.items[0]) mk("div", { fontSize: "24px", fontWeight: "700", color: rgba(p.color, 0.75), whiteSpace: "nowrap", marginTop: "8px" }, plainText(p.items[0]), col);
  const btn = mk("div", { position: "relative", flex: "none", width: "170px", height: "68px", borderRadius: "34px", background: p.accent, color: readableOn(p.accent), display: "grid", placeItems: "center", fontSize: "28px", fontWeight: "800" }, null, card);
  const follow = mk("div", { position: "absolute" }, "Follow", btn);
  const following = mk("div", { position: "absolute", opacity: "0" }, "Following", btn);
  const { w, h } = dims(card);
  const press = cueTimes(p, 1, c.dur, { from: c.dur * 0.55, to: c.dur * 0.55 })[0];
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur, { tin: 0.45, from: 0.92, rise: 24 });
      setT(avatar, { s: lerp(0.7, 1, ease.back(prog(t, 0.1, 0.55), 1.4)) });
      const k = ease.inOut(prog(t, press, press + 0.3));
      btn.style.background = mix(p.accent, mix(p.bg, "#000000", 0.08), k);
      btn.style.color = k > 0.5 ? p.color : readableOn(p.accent);
      follow.style.opacity = String(1 - c01(k * 2));         // one label at a time
      following.style.opacity = String(c01(k * 2 - 1));
      setT(btn, { s: 1 - 0.08 * Math.sin(Math.PI * c01((t - press) / 0.3)) });
    },
  };
});

// ---------------------------------------------------------------- 17. app tile (a platform you name)
defineTemplate({
  id: "app-tile", name: "App tile (a platform you name)", tl: "App tile", category: "card", styles: ONLY,
  moods: ["tech", "playful", "hype", "money", "calm"], zone: "upper", anchor: { x: 0.5, y: 0.2 }, box: { w: 260, h: 300 }, duration: 2.6, maxDuration: 8,
  maxChars: 14, bg: true, pad: 60,
  fields: ["text", "image", "color", "accent", "bg", "size", "intensity"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "image", type: "image", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT },
  sample: { text: "Your app" },
}, (c) => {
  // Your own logo file when you gave one; otherwise the name, set in type (never a made-up logo).
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "14px", width: "260px" }, null, c.root);
  const tile = p.image
    ? picture(wrap, p.image, { width: "200px", height: "200px", borderRadius: "48px", background: "#ffffff", boxShadow: SOFT }, { fit: "contain" })
    : mk("div", { width: "200px", height: "200px", borderRadius: "48px", background: p.bg, color: p.color, boxShadow: SOFT, display: "grid", placeItems: "center", boxSizing: "border-box", padding: "18px", fontFamily: serif.fontFamily, fontWeight: "800", textAlign: "center", lineHeight: "1.05" }, plainText(p.text), wrap);
  if (!p.image) c.fit(tile, { maxW: 164, maxH: 150, max: 60, min: 22 });
  const label = mk("div", { fontFamily: inter.fontFamily, fontWeight: "700", fontSize: "30px", color: "#ffffff", textShadow: "0 3px 12px rgba(0,0,0,.55)", whiteSpace: "nowrap" }, plainText(p.text), wrap);
  c.fit(label, { maxW: 260, maxH: 44, max: 30, min: 18, lines: 1 });
  if (!p.image) label.style.visibility = "hidden";   // the tile already shows the name
  const { h } = dims(wrap);
  return {
    w: 260, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.45, 0.35);
      const k = ease.back(c01(e.i), 1.6);
      wrap.style.opacity = String(c01(e.i * 2) * (1 - ease.inOut(e.o)));
      setT(tile, { s: lerp(0.4, 1, k) * (1 - 0.1 * ease.in(e.o)), r: lerp(-14, 0, ease.out(c01(e.i))) + Math.sin(t * 1.3) * 1.5, y: Math.sin(t * 1.7) * 6 });
      label.style.opacity = String(arrive(t, 0.25));
    },
  };
});

// ---------------------------------------------------------------- 18. stat cards (numbers you say)
defineTemplate({
  id: "stat-cards", name: "Number cards", tl: "Mga numero", category: "data", styles: ONLY,
  moods: ["money", "hype", "serious", "news", "tech"], zone: "any", anchor: { x: 0.5, y: 0.3 }, box: { w: 860, h: 300 }, duration: 3.4, maxDuration: 8,
  maxChars: 32, bg: true, pad: 70,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: CREAM, color: INK, accent: ACCENT },
  sample: { items: ["0", "1,000 followers", "30 araw"] },
}, (c) => {
  // Each item is "<number> <what it counts>", as said; each card counts up on its own word.
  const { p } = c;
  const parsed = p.items.slice(0, 4).map((raw) => {
    const m = String(raw).match(/^([₱$€]?)(\d[\d,.]*)(%?)\s*(.*)$/);
    return m ? { pre: m[1], value: Number(m[2].replace(/,/g, "")), suf: m[3], label: m[4], raw: m[2] } : { pre: "", value: NaN, suf: "", label: String(raw), raw: String(raw) };
  });
  const row = mk("div", { display: "flex", gap: "18px", alignItems: "stretch" }, null, c.root);
  const cards = parsed.map((it, i) => {
    const card = mk("div", { width: `${Math.floor((860 - 18 * (parsed.length - 1)) / parsed.length)}px`, boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "26px", padding: "24px 18px 22px", boxShadow: SOFT, textAlign: "center", fontFamily: inter.fontFamily }, null, row);
    const num = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", fontSize: "96px", lineHeight: "1", color: i === parsed.length - 1 ? p.accent : p.color, whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }, `${it.pre}${it.raw}${it.suf}`, card);
    c.fit(num, { maxW: parseInt(card.style.width) - 36, maxH: 110, max: 96, min: 36, lines: 1 });
    const lab = mk("div", { fontSize: "28px", fontWeight: "700", letterSpacing: "0.06em", textTransform: "uppercase", color: rgba(p.color, 0.6), marginTop: "12px", whiteSpace: "nowrap", minHeight: "34px" }, plainText(it.label), card);
    c.fit(lab, { maxW: parseInt(card.style.width) - 36, maxH: 40, max: 28, min: 16, lines: 1 });
    return { card, num, it };
  });
  const { w, h } = dims(row);
  const times = cueTimes(p, cards.length, c.dur, { from: 0.3, to: Math.min(c.dur * 0.6, 0.3 + cards.length * 0.5) });
  const show = (it, k) => {
    if (!Number.isFinite(it.value)) return `${it.pre}${it.raw}${it.suf}`;
    const v = it.value * k;
    const dec = (it.raw.split(".")[1] || "").length;
    return `${it.pre}${v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec })}${it.suf}`;
  };
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.4);
      row.style.opacity = String(1 - ease.inOut(e.o));
      cards.forEach((cd, i) => {
        const a = arrive(t, times[i], 0.45);
        cd.card.style.opacity = String(a);
        setT(cd.card, { y: (1 - a) * 40, s: lerp(0.9, 1, a) });
        cd.num.textContent = show(cd.it, ease.out(prog(t, times[i], times[i] + 0.8)));
      });
    },
  };
});

// ---------------------------------------------------------------- 19. magazine cover
defineTemplate({
  id: "magazine-cover", name: "Magazine cover", tl: "Pabalat ng magasin", category: "text", styles: ONLY,
  moods: ["luxury", "hype", "serious", "news", "emotion"], zone: "any", anchor: { x: 0.5, y: 0.42 }, box: { w: 840, h: 1080 }, duration: 3.4, maxDuration: 8,
  maxChars: 18, bg: false, pad: 60, covers: true,
  fields: ["text", "text2", "items", "number", "color", "accent", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }, { key: "items", type: "list", required: false }],
  defaults: { color: "#f4efe6", accent: ACCENT, number: 1 },
  sample: { text: "SIKRETO", text2: "Tatlong sikreto ng viral na video", items: ["Disiplina", "Paano kumita online", "30 araw"], number: 1 },
}, (c) => {
  // The words are yours (the masthead, the line under it, the cover lines); only the frame is design.
  const { p } = c;
  const page = mk("div", { position: "relative", width: "840px", height: "1080px", boxSizing: "border-box", border: `2px solid ${rgba(p.color, 0.55)}`, padding: "34px 40px", color: p.color, fontFamily: inter.fontFamily }, null, c.root);
  const top = mk("div", { display: "flex", justifyContent: "space-between", fontSize: "22px", fontWeight: "700", letterSpacing: "0.3em", textTransform: "uppercase", opacity: "0.85" }, null, page);
  mk("div", {}, `No. ${String(Math.max(1, Math.round(p.number || 1))).padStart(2, "0")}`, top);
  const mast = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", lineHeight: "0.9", letterSpacing: "-0.02em", textAlign: "center", marginTop: "18px", whiteSpace: "nowrap", textShadow: "0 8px 30px rgba(0,0,0,.35)" }, plainText(p.text).toUpperCase(), page);
  c.fit(mast, { maxW: 760, maxH: 200, max: 200, min: 70, lines: 1 });
  const kicker = mk("div", { fontFamily: serif.fontFamily, fontStyle: "italic", fontSize: "40px", textAlign: "center", marginTop: "14px", color: p.color }, plainText(p.text2), page);
  if (p.text2) c.fit(kicker, { maxW: 740, maxH: 110, max: 44, min: 24 }); else kicker.style.display = "none";
  const lines = mk("div", { position: "absolute", left: "40px", bottom: "160px", width: "420px", display: "flex", flexDirection: "column", gap: "18px" }, null, page);
  const cover = p.items.slice(0, 3).map((t) => {
    const row = mk("div", { borderLeft: `6px solid ${p.accent}`, paddingLeft: "16px", fontFamily: serif.fontFamily, fontWeight: "700", fontSize: "38px", lineHeight: "1.1", textShadow: "0 4px 16px rgba(0,0,0,.45)" }, plainText(t), lines);
    c.fit(row, { maxW: 390, maxH: 92, max: 40, min: 22 });
    return row;
  });
  const code = mk("div", { position: "absolute", left: "40px", bottom: "40px", width: "150px", height: "110px", background: "#ffffff", padding: "10px", boxSizing: "border-box", display: "flex", gap: "3px", alignItems: "stretch" }, null, page);
  for (let i = 0; i < 26; i++) mk("div", { flex: "none", width: `${[2, 4, 2, 6, 3][i % 5]}px`, background: "#111" }, null, code);
  const { w, h } = { w: 840, h: 1080 };
  const times = cueTimes(p, cover.length + 1, c.dur, { from: 0.25, to: Math.min(c.dur * 0.6, 0.25 + (cover.length + 1) * 0.45) });
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.5, 0.45);
      page.style.opacity = String(c01(e.i * 1.8) * (1 - ease.inOut(e.o)));
      const k = arrive(t, times[0], 0.7);
      mast.style.opacity = String(k);
      setT(mast, { s: lerp(1.12, 1, ease.out(k)), y: (1 - k) * -30 });
      setT(page, { s: 1 + 0.015 * c01(t / Math.max(dur, 0.1)) });
      kicker.style.opacity = String(arrive(t, times[0] + 0.35));
      cover.forEach((row, i) => { const a = arrive(t, times[i + 1], 0.5); row.style.opacity = String(a); setT(row, { x: (1 - a) * -40 }); });
      code.style.opacity = String(arrive(t, times[0] + 0.6));
    },
  };
});

// ---------------------------------------------------------------- 20. strikethrough text
defineTemplate({
  id: "strike-text", name: "Struck-out words", tl: "Binurang salita", category: "text", styles: ONLY,
  moods: ["serious", "emotion", "hype", "luxury", "calm"], zone: "upper", anchor: { x: 0.5, y: 0.2 }, box: { w: 900, h: 420 }, duration: 3, maxDuration: 8,
  words: true, maxChars: 48, bg: false, pad: 70,
  fields: ["text", "text2", "color", "accent", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: true }],
  defaults: { color: "#ffffff", accent: ACCENT },
  sample: { text: "wala akong follower", text2: "ito na ako" },
}, (c) => {
  // `text` (what was) is struck out on the first cue; `text2` (what is now) arrives big on the second.
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "8px", width: "900px", color: p.color, textAlign: "center" }, null, c.root);
  const oldRow = mk("div", { position: "relative", display: "inline-block", fontFamily: serif.fontFamily, fontSize: "44px", fontStyle: "italic", opacity: "0.85", textShadow: "0 3px 14px rgba(0,0,0,.5)" }, plainText(p.text), wrap);
  c.fit(oldRow, { maxW: 800, maxH: 110, max: 46, min: 24 });
  const line = mk("div", { position: "absolute", left: "-4%", top: "54%", width: "108%", height: "4px", background: p.accent, transformOrigin: "0 50%" }, null, oldRow);
  const now = mk("div", { fontFamily: serif.fontFamily, fontWeight: "800", lineHeight: "0.95", letterSpacing: "-0.02em", whiteSpace: "nowrap", textShadow: "0 8px 30px rgba(0,0,0,.45)" }, plainText(p.text2).toUpperCase(), wrap);
  c.fit(now, { maxW: 880, maxH: 200, max: 180, min: 50, lines: 1 });
  const { h } = dims(wrap);
  const [strikeAt, nowAt] = cueTimes(p, 2, c.dur, { from: 0.5, to: Math.min(c.dur * 0.6, 1.3) });
  return {
    w: 900, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.4);
      wrap.style.opacity = String(c01(e.i * 2) * (1 - ease.inOut(e.o)));
      line.style.transform = `scaleX(${arrive(t, strikeAt, 0.35)})`;
      oldRow.style.opacity = String(lerp(0.9, 0.45, arrive(t, nowAt, 0.4)));
      const k = arrive(t, nowAt, 0.55);
      now.style.opacity = String(k);
      setT(now, { s: lerp(1.25, 1, ease.out(k)), y: (1 - k) * 20 });
    },
  };
});

// ---------------------------------------------------------------- 21. text-tile mosaic
const TILE_COLOURS = ["#17140f", "#c8553d", "#1f2a44", "#e9dfcf", "#d9a5a5", "#6d5a8c", "#2f4f3e", "#f2c46d"];
defineTemplate({
  id: "tile-mosaic", name: "Mosaic of word tiles", tl: "Mosaic ng salita", category: "card", styles: ONLY,
  moods: ["hype", "playful", "luxury", "tech", "money"], zone: "any", anchor: { x: 0.5, y: 0.47 }, box: { w: 864, h: 1044 }, duration: 3.2, maxDuration: 8,
  maxChars: 32, bg: true, pad: 30, covers: true,
  fields: ["items", "color", "accent", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: true }],
  defaults: { color: "#ffffff", accent: ACCENT },
  sample: { items: ["Disiplina", "Paano kumita online", "TikTok", "30 araw", "Hook", "Kwento", "Call to action", "1,000 followers"] },
}, (c) => {
  // 3 x 3 tiles of your words around a window in the middle (your video shows through it).
  const { p } = c;
  const grid = mk("div", { display: "grid", gridTemplateColumns: "repeat(3, 280px)", gridTemplateRows: "repeat(3, 340px)", gap: "12px", width: "864px" }, null, c.root);
  const words = p.items.slice(0, 8);
  const tiles = [];
  let k = 0;
  for (let i = 0; i < 9; i++) {
    if (i === 4 || k >= words.length) { mk("div", {}, null, grid); continue; }  // the window
    const bg = TILE_COLOURS[k % TILE_COLOURS.length];
    const tile = mk("div", { width: "280px", height: "340px", background: bg, color: readableOn(bg), borderRadius: "20px", padding: "22px", boxSizing: "border-box", display: "flex", alignItems: "flex-end", boxShadow: SOFT }, null, grid);
    const words1 = mk("div", { width: "236px", fontFamily: k % 2 ? serif.fontFamily : inter.fontFamily, fontWeight: "800", textTransform: k % 2 ? "none" : "uppercase", lineHeight: "1.02", overflowWrap: "normal", wordBreak: "keep-all" }, plainText(words[k]), tile);
    c.fit(words1, { maxW: 236, maxH: 200, max: 56, min: 22 });
    tiles.push(tile);
    k++;
  }
  const times = cueTimes(p, tiles.length, c.dur, { from: 0.15, to: Math.min(c.dur * 0.5, 0.15 + tiles.length * 0.12) });
  return {
    w: 864, h: 3 * 340 + 24,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.4);
      grid.style.opacity = String(1 - ease.inOut(e.o));
      tiles.forEach((tile, i) => { const a = ease.back(prog(t, times[i], times[i] + 0.45), 1.2); tile.style.opacity = String(c01(a * 2)); setT(tile, { s: lerp(0.7, 1, a) }); });
    },
  };
});

// ---------------------------------------------------------------- 22. timeline card
defineTemplate({
  id: "timeline-card", name: "Timeline card", tl: "Timeline card", category: "card", styles: ONLY,
  moods: ["tech", "calm", "serious", "playful", "hype"], zone: "upper", anchor: { x: 0.5, y: 0.22 }, box: { w: 880, h: 420 }, duration: 3.2, maxDuration: 8,
  maxChars: 30, bg: true, pad: 60,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "text", type: "text", required: false }, { key: "items", type: "list", required: false }],
  defaults: { bg: "#efe6d8", color: INK, accent: ACCENT },
  sample: { text: "Araw-araw", items: ["hook", "kwento", "call to action"] },
}, (c) => {
  // An editing timeline: your words as the track names; coloured clips; a playhead sweeping across.
  const { p } = c;
  const card = mk("div", { width: "880px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "22px", padding: "22px 26px", boxShadow: SOFT, fontFamily: inter.fontFamily }, null, c.root);
  const head = mk("div", { display: "flex", justifyContent: "space-between", fontSize: "24px", fontWeight: "700", marginBottom: "14px" }, null, card);
  mk("div", {}, plainText(p.text) || "Timeline", head);
  const clock = mk("div", { fontFamily: mono.fontFamily, color: p.accent }, "00:00:00", head);
  const area = mk("div", { position: "relative" }, null, card);
  const tracks = (p.items.length ? p.items : ["", "", ""]).slice(0, 4);
  const palette = [p.accent, "#2c2c2c", "#b9a27e", "#d68a8a", "#7b6aa0"];
  const clips = [];
  tracks.forEach((name, r) => {
    const row = mk("div", { display: "flex", alignItems: "center", gap: "10px", height: "48px", marginBottom: "10px" }, null, area);
    const lab = mk("div", { width: "170px", fontSize: "20px", fontWeight: "600", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: rgba(p.color, 0.7) }, plainText(name), row);
    if (!name) lab.textContent = `V${r + 1}`;
    const lane = mk("div", { position: "relative", flex: "1", height: "34px" }, null, row);
    let x = (r * 7) % 12;
    for (let i = 0; i < 6 && x < 96; i++) {
      const wdt = 8 + ((r * 5 + i * 7) % 14);
      clips.push(mk("div", { position: "absolute", left: `${x}%`, width: `${Math.min(wdt, 98 - x)}%`, top: "0", height: "100%", borderRadius: "6px", background: palette[(r + i) % palette.length], transformOrigin: "0 50%" }, null, lane));
      x += wdt + 2;
    }
  });
  const head2 = mk("div", { position: "absolute", top: "-6px", bottom: "0", width: "3px", background: p.accent, left: "180px" }, null, area);
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      settle(card, t, dur);
      clips.forEach((cl, i) => { cl.style.transform = `scaleX(${arrive(t, 0.2 + i * 0.03, 0.4)})`; });
      const run = prog(t, 0.4, Math.max(0.8, dur - 0.4));
      head2.style.left = `${180 + run * 640}px`;
      const secs = Math.floor(run * 59);
      clock.textContent = `00:00:${String(secs).padStart(2, "0")}`;
    },
  };
});

// ---------------------------------------------------------------- 23. chat cards
defineTemplate({
  id: "chat-cards", name: "Chat messages", tl: "Mga mensahe", category: "card", styles: ONLY,
  moods: ["playful", "tech", "calm", "emotion", "hype"], zone: "upper", anchor: { x: 0.5, y: 0.2 }, box: { w: 860, h: 200 }, duration: 3.2, maxDuration: 8,
  maxChars: 80, bg: true, pad: 60,
  fields: ["text", "items", "image", "color", "accent", "bg", "size", "intensity", "cues"],
  inputs: [{ key: "items", type: "list", required: true }, { key: "text", type: "text", required: false }, { key: "image", type: "image", required: false }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT },
  sample: { text: "@yourhandle", items: ["Comment mo ang salitang GUIDE"] },
}, (c) => {
  // Message cards: who (`text`: your handle or name, as you gave it) and what was said (`items`),
  // typed in, one card per cue.
  const { p } = c;
  const col = mk("div", { display: "flex", flexDirection: "column", gap: "14px", width: "860px" }, null, c.root);
  const who = plainText(p.text);
  const initials = who.replace(/^@/, "").slice(0, 1).toUpperCase() || "•";
  const cards = p.items.slice(0, 3).map((msg, i) => {
    const card = mk("div", { display: "flex", gap: "16px", alignItems: "flex-start", background: p.bg, color: p.color, borderRadius: "22px", padding: "18px 22px", boxShadow: SOFT, fontFamily: inter.fontFamily }, null, col);
    const av = p.image && i === 0
      ? picture(card, p.image, { width: "54px", height: "54px", borderRadius: "50%", flex: "none" })
      : mk("div", { width: "54px", height: "54px", borderRadius: "50%", flex: "none", background: i % 2 ? "#d68a8a" : p.accent, color: "#fff", display: "grid", placeItems: "center", fontWeight: "800", fontSize: "26px" }, initials, card);
    void av;
    const body = mk("div", { minWidth: "0", flex: "1" }, null, card);
    if (who) mk("div", { fontWeight: "800", fontSize: "24px", marginBottom: "4px" }, who, body);
    const text = mk("div", { fontSize: "30px", lineHeight: "1.25" }, "", body);
    return { card, text, msg: plainText(msg) };
  });
  // measure with the full text, then type it
  cards.forEach((cd) => { cd.text.textContent = cd.msg; });
  const { w, h } = dims(col);
  const times = cueTimes(p, cards.length, c.dur, { from: 0.2, to: Math.min(c.dur * 0.6, 0.2 + cards.length * 0.8) });
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.4);
      col.style.opacity = String(1 - ease.inOut(e.o));
      cards.forEach((cd, i) => {
        const a = arrive(t, times[i], 0.4);
        cd.card.style.opacity = String(a);
        setT(cd.card, { y: (1 - a) * 30 });
        const n = Math.round(c01((t - times[i] - 0.15) / Math.max(0.4, cd.msg.length * 0.035)) * cd.msg.length);
        cd.text.textContent = cd.msg.slice(0, n);
      });
    },
  };
});

// ---------------------------------------------------------------- 24. label pill (under a PiP)
defineTemplate({
  id: "label-pill", name: "Label pill", tl: "Label", category: "pill", styles: ONLY,
  moods: ["calm", "tech", "playful", "money", "hype", "serious"], zone: "any", anchor: { x: 0.5, y: 0.3 }, box: { w: 520, h: 90 }, duration: 2.6, maxDuration: 8,
  maxChars: 32, bg: true, pad: 40,
  fields: ["text", "color", "accent", "bg", "size", "intensity"],
  inputs: [{ key: "text", type: "text", required: true }],
  defaults: { bg: "#ffffff", color: INK, accent: ACCENT },
  sample: { text: "ang resulta ko" },
}, (c) => {
  const { p } = c;
  const pill = mk("div", { display: "inline-flex", alignItems: "center", gap: "10px", background: p.bg, color: p.color, borderRadius: "999px", padding: "12px 26px", boxShadow: SOFT, fontFamily: inter.fontFamily, fontWeight: "800", fontSize: "32px", whiteSpace: "nowrap" }, null, c.root);
  mk("div", { width: "14px", height: "14px", borderRadius: "50%", background: p.accent, flex: "none" }, null, pill);
  const label = mk("div", {}, plainText(p.text), pill);
  c.fit(label, { maxW: 440, maxH: 44, max: 34, min: 18, lines: 1 });
  const { w, h } = dims(pill);
  return { w, h, update(t, dur) { settle(pill, t, dur, { tin: 0.35, from: 0.85, rise: 14 }); } };
});
