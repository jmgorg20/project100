// Emoji and attention graphics: pops, bursts, warnings, hearts, quotes, before/after labels, stickers.
import {
  defineTemplate, mk, icon, ease, prog, c01, lerp, envelope, readableOn, rgba, setT, plainText, mix, legible, svgEl, rng, fontCss,
} from "../engine.js";

const sh = "0 18px 40px rgba(0,0,0,.38),0 2px 6px rgba(0,0,0,.25)";
const dims = (el) => { const r = el.getBoundingClientRect(); return { w: Math.ceil(r.width), h: Math.ceil(r.height) }; };
const emojiFont = fontCss("inter").fontFamily;

// ---- big emoji pop
defineTemplate({
  id: "emoji-pop", name: "Emoji pop", tl: "Emoji pop", category: "emoji", moods: ["funny", "playful", "hype", "emotion", "money"],
  zone: "any", anchor: { x: 0.5, y: 0.4 }, box: { w: 300, h: 300 }, duration: 1.6, maxChars: 4, pad: 90,
  fields: ["emoji", "size", "intensity"], inputs: [{ key: "emoji", type: "text", required: true }],
  defaults: { emoji: "🔥" }, sample: { emoji: "🔥" },
}, (c) => {
  const { p } = c;
  const S = 260;
  const wrap = mk("div", { width: `${S}px`, height: `${S}px`, position: "relative", display: "grid", placeItems: "center" }, null, c.root);
  const em = mk("div", { fontSize: "220px", lineHeight: "1", fontFamily: emojiFont, filter: "drop-shadow(0 12px 18px rgba(0,0,0,.4))" }, p.emoji || "🔥", wrap);
  const rnd = rng(3);
  const sparks = Array.from({ length: 6 }, (_, i) => ({ a: (i / 6) * Math.PI * 2 + rnd() * 0.5, d: 150 + rnd() * 50, el: mk("div", { position: "absolute", left: `${S / 2 - 8}px`, top: `${S / 2 - 8}px`, width: "16px", height: "16px", borderRadius: "50%", background: i % 2 ? "#ffd23f" : "#ffffff" }, null, wrap) }));
  return {
    w: S, h: S,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.3);
      const k = ease.elastic(prog(t, 0, 0.55));
      em.style.opacity = String(c01(t * 8) * (1 - e.o));
      setT(em, { s: lerp(0.1, 1, k) * (1 + 0.05 * p.intensity * Math.sin(t * 8) * (t > 0.5 ? 1 : 0)) * (1 - 0.3 * e.o), r: (1 - k) * -40 + Math.sin(t * 5) * 3 });
      sparks.forEach((s) => {
        const kk = ease.out(prog(t, 0.05, 0.6));
        s.el.style.opacity = String(kk > 0 ? (1 - prog(t, 0.35, 0.8)) * p.intensity : 0);
        setT(s.el, { x: Math.cos(s.a) * s.d * kk, y: Math.sin(s.a) * s.d * kk, s: 1 - 0.5 * kk });
      });
    },
  };
});

// ---- emoji burst
defineTemplate({
  id: "emoji-burst", name: "Emoji burst", tl: "Sabog na emoji", category: "emoji", moods: ["funny", "playful", "hype", "money", "emotion"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 600, h: 600 }, duration: 2, maxChars: 6, pad: 80,
  fields: ["emoji", "size", "intensity"], inputs: [{ key: "emoji", type: "text", required: true }],
  defaults: { emoji: "💸" }, sample: { emoji: "💸" },
}, (c) => {
  const { p } = c;
  const S = 600;
  const wrap = mk("div", { width: `${S}px`, height: `${S}px`, position: "relative" }, null, c.root);
  const rnd = rng(21);
  const n = 5 + Math.round(5 * p.intensity);
  const items = Array.from({ length: n }, (_, i) => ({
    a: -Math.PI / 2 + (rnd() - 0.5) * 2.2, v: 170 + rnd() * 170, sz: 80 + rnd() * 70, rot: (rnd() - 0.5) * 120, delay: rnd() * 0.12,
    el: mk("div", { position: "absolute", left: `${S / 2 - 50}px`, top: `${S / 2 - 30}px`, fontSize: "100px", lineHeight: "1", fontFamily: emojiFont }, p.emoji || "💸", wrap),
  }));
  items.forEach((it) => { it.el.style.fontSize = `${it.sz}px`; });
  return {
    w: S, h: S,
    update(t, dur) {
      const e = envelope(t, dur, 0.1, 0.4);
      items.forEach((it) => {
        const u = Math.max(0, t - it.delay);
        const x = Math.cos(it.a) * it.v * u, y = Math.sin(it.a) * it.v * u + 0.5 * 420 * u * u;
        it.el.style.opacity = String(c01(u * 10) * (1 - e.o));
        setT(it.el, { x, y, r: it.rot * u, s: 1 - 0.2 * u });
      });
    },
  };
});

// ---- warning banner
defineTemplate({
  id: "warning-banner", name: "Warning banner", tl: "Babala", category: "banner", moods: ["warning", "urgent", "serious", "funny"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 900, h: 220 }, duration: 2.2, maxChars: 30, bg: true, pad: 60,
  fields: ["text", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }],
  defaults: { bg: "#111111", color: "#ffd400", accent: "#ffd400", font: "impact", case: "upper" }, sample: { text: "Warning: Don't skip this" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { width: "900px", position: "relative", background: p.bg, borderRadius: "10px", boxShadow: sh, overflow: "hidden", color: p.color }, null, c.root);
  const stripe = () => mk("div", { height: "28px", backgroundImage: `repeating-linear-gradient(-45deg,${p.accent} 0 28px,#111111 28px 56px)`, backgroundSize: "80px 28px" }, null, wrap);
  stripe();
  const body = mk("div", { padding: "22px 36px", textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: "20px" }, null, wrap);
  const ic = mk("div", { flex: "none" }, null, body);
  icon("warning", 84, p.accent, ic, { stroke: 2 });
  const label = mk("div", { lineHeight: "1.05", letterSpacing: "0.03em", whiteSpace: "nowrap" }, plainText(p.text), body);
  c.fit(label, { maxW: 660, maxH: 110, max: 84, min: 30, lines: 1 });
  label.style.width = "auto";
  stripe();
  const { w, h } = dims(wrap);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.25, 0.25);
      wrap.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(wrap, { s: lerp(0.8, 1, ease.back(e.i, 1.3)) });
      const blink = Math.floor(t * 4) % 2 === 0 || t < 0.4 ? 1 : 0.55 + 0.45 * (1 - p.intensity);
      ic.style.opacity = String(blink);
    },
  };
});

// ---- like / hearts
defineTemplate({
  id: "heart-like", name: "Hearts", tl: "Mga puso", category: "emoji", moods: ["emotion", "playful", "calm", "hype"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 400, h: 400 }, duration: 2.2, maxChars: 14, pad: 80,
  fields: ["text", "accent", "color", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }],
  defaults: { accent: "#ff3b6b", color: "#ffffff" }, sample: { text: "1.2K" },
}, (c) => {
  const { p } = c;
  const S = 400;
  const wrap = mk("div", { width: `${S}px`, height: `${S}px`, position: "relative" }, null, c.root);
  const rnd = rng(8);
  const little = Array.from({ length: 5 }, () => ({ x: 120 + rnd() * 160, drift: (rnd() - 0.5) * 120, s: 38 + rnd() * 34, d: rnd() * 0.5, el: mk("div", { position: "absolute", left: "0", top: "0" }, null, wrap) }));
  little.forEach((l) => icon("heart", l.s, p.accent, l.el, { fill: true, stroke: 1 }));
  const big = mk("div", { position: "absolute", left: `${S / 2 - 90}px`, top: `${S / 2 - 100}px`, filter: `drop-shadow(0 10px 18px ${rgba(p.accent, 0.6)})` }, null, wrap);
  icon("heart", 180, p.accent, big, { fill: true, stroke: 1 });
  const label = mk("div", { position: "absolute", left: "0", right: "0", top: `${S / 2 + 98}px`, textAlign: "center", fontSize: "54px", fontWeight: "900", color: p.color, textShadow: legible(), fontFamily: fontCss("inter").fontFamily }, plainText(p.text), wrap);
  return {
    w: S, h: S,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.3);
      const beat = 1 + 0.12 * p.intensity * Math.max(0, Math.sin(t * 7)) * (t > 0.4 ? 1 : 0);
      big.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(big, { s: lerp(0.2, 1, ease.elastic(e.i)) * beat });
      label.style.opacity = String(ease.out(prog(t, 0.3, 0.7)) * (1 - e.o));
      little.forEach((l) => {
        const u = prog(t, 0.3 + l.d, 1.9 + l.d);
        l.el.style.opacity = String(u > 0 ? Math.sin(Math.PI * u) : 0);
        setT(l.el, { x: l.x + Math.sin(u * 5) * 18 + l.drift * u, y: S / 2 - 40 - 260 * u, s: 0.6 + 0.5 * u });
      });
    },
  };
});

// ---- quote card
defineTemplate({
  id: "quote-card", name: "Quote card", tl: "Quote card", category: "card", moods: ["serious", "emotion", "calm", "luxury"],
  zone: "center", anchor: { x: 0.5, y: 0.46 }, box: { w: 820, h: 420 }, duration: 3.4, maxChars: 90, bg: true, pad: 60,
  fields: ["text", "text2", "font", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#14161d", color: "#ffffff", accent: "#ffd23f", font: "serif" }, sample: { text: "Small steps every day beat big plans someday", text2: "— my rule" },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "820px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "36px", padding: "54px 56px 44px", boxShadow: sh, position: "relative" }, null, c.root);
  mk("div", { position: "absolute", left: "34px", top: "-6px", fontSize: "200px", lineHeight: "1", color: p.accent, fontFamily: fontCss("serif").fontFamily, fontWeight: "900", opacity: "0.95" }, "“", card);
  const q = mk("div", { lineHeight: "1.18", marginTop: "56px", fontWeight: "700" }, plainText(p.text), card);
  c.fit(q, { maxW: 708, maxH: 300, max: 66, min: 30 });
  if (p.text2) mk("div", { marginTop: "22px", fontSize: "32px", color: p.accent, letterSpacing: "0.06em", fontFamily: fontCss("inter").fontFamily, fontWeight: "700" }, plainText(p.text2), card);
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.5, 0.35);
      card.style.opacity = String(ease.out(e.i) * (1 - e.o));
      setT(card, { y: (1 - ease.out(e.i)) * 50, s: lerp(0.94, 1, ease.out(e.i)) });
      q.style.clipPath = `inset(0 ${100 - ease.out(prog(t, 0.3, 1.1)) * 100}% 0 0)`;
    },
  };
});

// ---- before / after labels (pairs with the Before/after wipe effect)
defineTemplate({
  id: "before-after-tag", name: "Before / After tags", tl: "Before / After", category: "banner", moods: ["hype", "tech", "serious", "playful", "luxury"],
  zone: "upper", anchor: { x: 0.5, y: 0.12 }, box: { w: 900, h: 90 }, duration: 3, maxChars: 14, bg: true, pad: 50,
  fields: ["text", "text2", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#111111", color: "#ffffff", accent: "#ffd23f", font: "black", text: "BEFORE", text2: "AFTER", case: "upper" }, sample: { text: "BEFORE", text2: "AFTER" },
}, (c) => {
  const { p } = c;
  const row = mk("div", { width: "900px", display: "flex", justifyContent: "space-between", alignItems: "center" }, null, c.root);
  const mkTag = (txt, bg, fg) => {
    const el = mk("div", { background: bg, color: fg, borderRadius: "999px", padding: "12px 42px", fontSize: "44px", letterSpacing: "0.12em", fontWeight: "900", boxShadow: sh, whiteSpace: "nowrap" }, plainText(txt), row);
    c.fit(el, { maxW: 340, maxH: 80, max: 44, min: 22, lines: 1 });
    el.style.width = "auto";
    return el;
  };
  const a = mkTag(p.text || "BEFORE", p.bg, p.color);
  const b = mkTag(p.text2 || "AFTER", p.accent, readableOn(p.accent));
  const { w, h } = dims(row);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.3);
      a.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      b.style.opacity = String(ease.out(prog(t, 0.6, 1)) * (1 - e.o));
      setT(a, { x: (1 - ease.out(e.i)) * -80 });
      setT(b, { x: (1 - ease.out(prog(t, 0.6, 1))) * 80 });
    },
  };
});

// ---- sticker
defineTemplate({
  id: "sticker-label", name: "Sticker", tl: "Sticker", category: "banner", moods: ["funny", "playful", "hype", "urgent", "money"],
  zone: "any", anchor: { x: 0.7, y: 0.3 }, box: { w: 420, h: 420 }, duration: 2, maxChars: 14, bg: true, pad: 70,
  fields: ["text", "color", "accent", "font", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }],
  defaults: { accent: "#ff3b6b", color: "#ffffff", font: "comic", case: "upper" }, sample: { text: "New!" },
}, (c) => {
  const { p } = c;
  const S = 380;
  const wrap = mk("div", { width: `${S}px`, height: `${S}px`, position: "relative", display: "grid", placeItems: "center" }, null, c.root);
  const svg = svgEl("svg", { viewBox: "-100 -100 200 200", width: S, height: S }, wrap);
  Object.assign(svg.style, { position: "absolute", inset: "0", filter: "drop-shadow(0 12px 16px rgba(0,0,0,.4))" });
  const pts = [];
  for (let i = 0; i < 32; i++) { const r = i % 2 ? 78 : 96; const a = (i / 32) * Math.PI * 2; pts.push(`${(Math.cos(a) * r).toFixed(1)},${(Math.sin(a) * r).toFixed(1)}`); }
  svgEl("polygon", { points: pts.join(" "), fill: p.accent, stroke: "#ffffff", "stroke-width": 6, "stroke-linejoin": "round" }, svg);
  const label = mk("div", { position: "relative", color: p.color, lineHeight: "1", textAlign: "center", textShadow: "0 4px 0 rgba(0,0,0,.35)", fontWeight: "700" }, plainText(p.text), wrap);
  c.fit(label, { maxW: 250, maxH: 160, max: 96, min: 26 });
  return {
    w: S, h: S,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.3);
      const k = ease.elastic(e.i);
      wrap.style.opacity = String(c01(e.i * 4) * (1 - e.o));
      setT(wrap, { s: lerp(0.2, 1, k) * (1 + 0.04 * p.intensity * Math.sin(t * 7)), r: lerp(-30, -10, k) + Math.sin(t * 3) * 2 });
    },
  };
});
void mk; void mix; void rgba;
