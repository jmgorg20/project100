// Numbers and lists: counters, bars, price tags, checklists, ratings.
import {
  defineTemplate, mk, icon, ease, prog, c01, lerp, envelope, readableOn, rgba, setT, plainText, mix, legible, svgEl, fontCss,
} from "../engine.js";

const sh = "0 18px 40px rgba(0,0,0,.38),0 2px 6px rgba(0,0,0,.25)";
const dims = (el) => { const r = el.getBoundingClientRect(); return { w: Math.ceil(r.width), h: Math.ceil(r.height) }; };
const fmt = (n, decimals) => Number(n).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
const decimalsOf = (n) => (Number.isInteger(n) ? 0 : Math.min(2, String(n).split(".")[1]?.length || 0));

// ---- counter
defineTemplate({
  id: "counter-number", name: "Number counter", tl: "Nagbibilang na numero", category: "data", moods: ["money", "hype", "serious", "tech", "news"],
  zone: "center", anchor: { x: 0.5, y: 0.42 }, box: { w: 760, h: 300 }, duration: 2.6, maxChars: 28, pad: 80,
  fields: ["text", "number", "prefix", "suffix", "font", "color", "accent", "size", "intensity"],
  inputs: [{ key: "number", type: "number", required: true }, { key: "text", type: "text", required: false }],
  defaults: { font: "impact", color: "#ffffff", accent: "#35e08a", number: 1000000, prefix: "", suffix: "" }, sample: { number: 250000, prefix: "₱", suffix: "", text: "earned this month" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "6px" }, null, c.root);
  const num = mk("div", { lineHeight: "1", whiteSpace: "nowrap", color: p.color, textShadow: legible(), fontVariantNumeric: "tabular-nums" }, null, wrap);
  const dec = decimalsOf(p.number);
  const finalText = `${p.prefix}${fmt(p.number, dec)}${p.suffix}`;
  num.textContent = finalText;
  c.fit(num, { maxW: 860, maxH: 240, max: 190, min: 50, lines: 1 });
  num.style.width = "auto";
  const bar = mk("div", { height: "8px", width: "120px", background: p.accent, borderRadius: "4px", boxShadow: `0 0 18px ${rgba(p.accent, 0.8)}` }, null, wrap);
  const label = mk("div", { fontSize: "44px", fontWeight: "700", color: p.color, opacity: "0.92", textShadow: legible(), textAlign: "center", fontFamily: fontCss("inter").fontFamily }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 800, maxH: 120, max: 48, min: 24 }); else label.style.display = "none";
  const { w, h } = dims(wrap);
  // keep the digits from jittering: the box has the final width, digits are tabular
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.25, 0.3);
      const k = ease.out(prog(t, 0.1, Math.min(dur - 0.5, 1.6)));
      num.textContent = `${p.prefix}${fmt(p.number * k, dec)}${p.suffix}`;
      const done = k >= 1;
      wrap.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(num, { s: done ? 1 + 0.06 * p.intensity * Math.sin(Math.PI * c01((t - 1.7) / 0.35)) : lerp(0.9, 1, k) });
      bar.style.transform = `scaleX(${ease.out(prog(t, 0.2, 0.9))})`;
      label.style.opacity = String(ease.out(prog(t, 0.5, 1)));
    },
  };
});

// ---- progress bar
defineTemplate({
  id: "stat-bar", name: "Percent bar", tl: "Percent bar", category: "data", moods: ["tech", "serious", "money", "news", "calm"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 800, h: 190 }, duration: 2.8, maxChars: 34, bg: true, pad: 60,
  fields: ["text", "number", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "number", type: "number", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#10131c", color: "#ffffff", accent: "#35e08a", number: 80 }, sample: { number: 87, text: "Customers love it" },
}, (c) => {
  const { p } = c;
  const pct = Math.max(0, Math.min(100, p.number));
  const card = mk("div", { width: "800px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "34px", padding: "30px 38px", boxShadow: sh, fontFamily: fontCss("inter").fontFamily }, null, c.root);
  const top = mk("div", { display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "20px" }, null, card);
  const label = mk("div", { fontWeight: "800", lineHeight: "1.1", whiteSpace: "nowrap" }, plainText(p.text), top);
  c.fit(label, { maxW: 520, maxH: 60, max: 44, min: 24, lines: 1 });
  label.style.width = "auto";
  const val = mk("div", { fontWeight: "900", fontSize: "60px", color: p.accent, fontVariantNumeric: "tabular-nums" }, "0%", top);
  const track = mk("div", { height: "26px", borderRadius: "13px", background: rgba("#ffffff", 0.14), marginTop: "18px", overflow: "hidden" }, null, card);
  const fill = mk("div", { height: "100%", width: "0%", borderRadius: "13px", background: `linear-gradient(90deg,${mix(p.accent, "#000000", 0.2)},${p.accent})` }, null, track);
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.3);
      const k = ease.out(prog(t, 0.3, Math.min(dur - 0.4, 1.6)));
      fill.style.width = `${pct * k}%`;
      val.textContent = `${Math.round(pct * k)}%`;
      card.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(card, { y: (1 - ease.out(e.i)) * 40 });
    },
  };
});

// ---- price tag
defineTemplate({
  id: "price-tag", name: "Price tag", tl: "Price tag", category: "data", moods: ["money", "hype", "playful", "urgent"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 520, h: 300 }, duration: 2.4, maxChars: 20, bg: true, pad: 80,
  fields: ["text", "number", "prefix", "suffix", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "number", type: "number", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#ffd23f", color: "#1b1b1b", accent: "#ff3b3b", font: "black", number: 499, prefix: "₱" }, sample: { number: 499, prefix: "₱", text: "ONLY" },
}, (c) => {
  const { p } = c;
  const tag = mk("div", { position: "relative", display: "inline-flex", flexDirection: "column", alignItems: "center", background: p.bg, color: p.color, borderRadius: "34px", padding: "20px 64px 26px 90px", boxShadow: sh, transformOrigin: "10% 50%" }, null, c.root);
  mk("div", { position: "absolute", left: "26px", top: "50%", width: "30px", height: "30px", marginTop: "-15px", borderRadius: "50%", background: "rgba(0,0,0,.35)", boxShadow: "inset 0 2px 4px rgba(0,0,0,.45)" }, null, tag);
  if (p.text) mk("div", { fontSize: "30px", letterSpacing: "0.25em", fontWeight: "800", color: p.accent }, plainText(p.text), tag);
  const price = mk("div", { lineHeight: "1", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }, `${p.prefix}${fmt(p.number, decimalsOf(p.number))}${p.suffix}`, tag);
  c.fit(price, { maxW: 640, maxH: 150, max: 130, min: 44, lines: 1 });
  price.style.width = "auto";
  const { w, h } = dims(tag);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.5, 0.3);
      const k = ease.elastic(e.i);
      tag.style.opacity = String(c01(e.i * 4) * (1 - e.o));
      setT(tag, { r: lerp(-35, -6, k) + Math.sin(t * 2.2) * 1.2, s: lerp(0.3, 1, k) });
    },
  };
});

// ---- checklist
defineTemplate({
  id: "checklist", name: "Checklist", tl: "Checklist", category: "data", moods: ["serious", "tech", "calm", "money", "news"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 780, h: 420 }, duration: 3.6, maxChars: 30, bg: true, pad: 60,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "items", type: "list", required: true }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#1b2230", accent: "#22c55e", items: ["Hook", "Value", "Call to action"] }, sample: { text: "Do this", items: ["Hook first", "Show the result", "Ask for the follow"] },
}, (c) => {
  const { p } = c;
  const rows = (p.items.length ? p.items : [p.text]).slice(0, 5);
  const card = mk("div", { width: "780px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "36px", padding: "30px 38px", boxShadow: sh, fontFamily: fontCss("inter").fontFamily }, null, c.root);
  if (p.text && p.items.length) mk("div", { fontSize: "34px", fontWeight: "900", letterSpacing: "0.12em", textTransform: "uppercase", opacity: "0.55", marginBottom: "10px" }, plainText(p.text), card);
  const els = rows.map((r) => {
    const row = mk("div", { display: "flex", alignItems: "center", gap: "22px", padding: "10px 0" }, null, card);
    const box = mk("div", { width: "60px", height: "60px", borderRadius: "16px", border: `5px solid ${p.accent}`, flex: "none", display: "grid", placeItems: "center", boxSizing: "border-box" }, null, row);
    const tick = icon("check", 40, p.accent, box, { stroke: 3.4 });
    const path = tick.querySelector("path");
    path.setAttribute("stroke-dasharray", "20");
    const label = mk("div", { fontWeight: "700", whiteSpace: "nowrap", lineHeight: "1.15" }, plainText(r), row);
    c.fit(label, { maxW: 600, maxH: 60, max: 46, min: 24, lines: 1 });
    label.style.width = "auto";
    return { row, path, box };
  });
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.3);
      card.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(card, { s: lerp(0.9, 1, ease.out(e.i)) });
      els.forEach((r, i) => {
        const k = prog(t, 0.55 + i * 0.5, 0.85 + i * 0.5);
        r.path.setAttribute("stroke-dashoffset", String(20 * (1 - ease.out(k))));
        r.box.style.background = k > 0.2 ? rgba(p.accent, 0.18) : "transparent";
        setT(r.row, { x: (1 - ease.out(prog(t, 0.3 + i * 0.12, 0.6 + i * 0.12))) * -40 });
        r.row.style.opacity = String(ease.out(prog(t, 0.3 + i * 0.12, 0.6 + i * 0.12)));
      });
    },
  };
});

// ---- star rating
defineTemplate({
  id: "rating-stars", name: "Star rating", tl: "Star rating", category: "data", moods: ["money", "hype", "emotion", "playful", "luxury"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 620, h: 230 }, duration: 2.6, maxChars: 30, pad: 70,
  fields: ["text", "number", "color", "accent", "size", "intensity"], inputs: [{ key: "number", type: "number", required: true }, { key: "text", type: "text", required: false }],
  defaults: { color: "#ffffff", accent: "#ffc531", number: 5 }, sample: { number: 4.8, text: "Loved by customers" },
}, (c) => {
  const { p } = c;
  const rating = Math.max(0, Math.min(5, p.number));
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "14px" }, null, c.root);
  const row = mk("div", { display: "flex", gap: "10px" }, null, wrap);
  const stars = [0, 1, 2, 3, 4].map((i) => {
    const cell = mk("div", { position: "relative", width: "104px", height: "104px" }, null, row);
    const back = icon("star", 104, rgba("#ffffff", 0.35), cell, { fill: true, stroke: 1 });
    const front = mk("div", { position: "absolute", left: "0", top: "0", width: "104px", height: "104px", overflow: "hidden", filter: `drop-shadow(0 0 10px ${rgba(p.accent, 0.8)})` }, null, cell);
    icon("star", 104, p.accent, front, { fill: true, stroke: 1 });
    void back;
    return { cell, front, amount: Math.max(0, Math.min(1, rating - i)) };
  });
  const label = mk("div", { fontSize: "44px", fontWeight: "800", color: p.color, textShadow: legible(), textAlign: "center", whiteSpace: "nowrap", fontFamily: fontCss("inter").fontFamily }, plainText(p.text) || `${fmt(rating, 1)} / 5`, wrap);
  c.fit(label, { maxW: 800, maxH: 70, max: 48, min: 24, lines: 1 });
  const { w, h } = dims(wrap);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.2, 0.3);
      wrap.style.opacity = String(1 - e.o);
      stars.forEach((s, i) => {
        const k = ease.back(prog(t, i * 0.16, i * 0.16 + 0.4), 2);
        s.front.style.width = `${104 * s.amount * c01(k * 1.2)}px`;
        s.front.style.opacity = String(c01(k * 3));
        setT(s.cell, { s: lerp(0.2, 1, k) });
      });
      label.style.opacity = String(ease.out(prog(t, 0.7, 1.2)));
    },
  };
});
void svgEl; void readableOn;
