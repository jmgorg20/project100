// Templates the video formats use: numbered list items, ranking numbers, A-vs-B headers,
// explainer callouts and framed screenshots.
import { defineTemplate, mk, icon, ease, prog, c01, lerp, envelope, readableOn, rgba, setT, plainText, mix, legible, fontCss, ICON_KEYS } from "../engine.js";

const sh = "0 18px 40px rgba(0,0,0,.38),0 2px 6px rgba(0,0,0,.25)";
const dims = (el) => { const r = el.getBoundingClientRect(); return { w: Math.ceil(r.width), h: Math.ceil(r.height) }; };
const inter = fontCss("inter");

// ---- a numbered list item (listicles)
defineTemplate({
  id: "list-item", name: "List item", tl: "Item sa listahan", category: "data", moods: ["serious", "tech", "calm", "hype", "news", "money"],
  zone: "any", anchor: { x: 0.5, y: 0.6 }, box: { w: 820, h: 150 }, duration: 3, maxChars: 44, bg: true, pad: 60,
  fields: ["text", "number", "color", "accent", "bg", "font", "size", "intensity"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "number", type: "number", required: false }],
  defaults: { bg: "#ffffff", color: "#151a24", accent: "#2f6bff", number: 1, font: "inter" }, sample: { text: "Hook them in 3 seconds", number: 1 },
}, (c) => {
  const { p } = c;
  const row = mk("div", { display: "inline-flex", alignItems: "center", gap: "22px", background: p.bg, color: p.color, borderRadius: "30px", padding: "18px 34px 18px 18px", boxShadow: sh, maxWidth: "860px" }, null, c.root);
  const badge = mk("div", { width: "100px", height: "100px", flex: "none", borderRadius: "26px", background: p.accent, color: readableOn(p.accent), display: "grid", placeItems: "center", fontSize: "60px", fontWeight: "900", fontFamily: fontCss("black").fontFamily }, String(Math.round(p.number) || 1), row);
  const label = mk("div", { fontWeight: "800", lineHeight: "1.12" }, plainText(p.text), row);
  c.fit(label, { maxW: 660, maxH: 130, max: 54, min: 26 });
  const { w, h } = dims(row);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.45, 0.3);
      row.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(row, { x: (1 - ease.out(e.i)) * -160 + e.o * 120 });
      setT(badge, { s: lerp(0.3, 1, ease.back(prog(t, 0.1, 0.5), 2)), r: (1 - ease.out(prog(t, 0.1, 0.5))) * -40 });
      label.style.clipPath = `inset(0 ${100 - ease.out(prog(t, 0.25, 0.75)) * 100}% 0 0)`;
    },
  };
});

// ---- a ranking / countdown number
defineTemplate({
  id: "rank-number", name: "Ranking number", tl: "Numero ng ranking", category: "data", moods: ["hype", "funny", "playful", "news", "money"],
  zone: "upper", anchor: { x: 0.5, y: 0.2 }, box: { w: 560, h: 360 }, duration: 2.4, maxChars: 30, pad: 90,
  fields: ["text", "number", "color", "accent", "font", "size", "intensity"],
  inputs: [{ key: "number", type: "number", required: true }, { key: "text", type: "text", required: false }],
  defaults: { color: "#ffffff", accent: "#ffd23f", number: 1, font: "impact" }, sample: { number: 3, text: "Cheapest option" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center" }, null, c.root);
  const num = mk("div", { fontSize: "230px", lineHeight: "0.95", color: p.accent, textShadow: `0 0 30px ${rgba(p.accent, 0.6)},0 6px 0 rgba(0,0,0,.35)`, whiteSpace: "nowrap" }, `#${Math.round(p.number) || 1}`, wrap);
  const label = mk("div", { fontSize: "54px", color: p.color, textShadow: legible(), textAlign: "center", fontFamily: inter.fontFamily, fontWeight: "800", whiteSpace: "nowrap" }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 800, maxH: 80, max: 56, min: 28, lines: 1 }); else label.style.display = "none";
  const { w, h } = dims(wrap);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.3);
      const k = ease.elastic(prog(t, 0, 0.6));
      wrap.style.opacity = String(c01(t * 6) * (1 - e.o));
      // flips in like a scoreboard card, then breathes
      num.style.transform = `perspective(600px) rotateX(${(1 - ease.out(prog(t, 0, 0.35))) * 90}deg) scale(${lerp(0.4, 1, k) * (1 + 0.04 * p.intensity * Math.sin(t * 6))})`;
      setT(label, { y: (1 - ease.out(prog(t, 0.25, 0.6))) * 30 });
      label.style.opacity = String(ease.out(prog(t, 0.25, 0.6)));
    },
  };
});

// ---- A vs B
defineTemplate({
  id: "versus-split", name: "A vs B", tl: "A laban sa B", category: "banner", moods: ["hype", "serious", "news", "tech", "money", "funny"],
  zone: "center", anchor: { x: 0.5, y: 0.5 }, box: { w: 900, h: 170 }, duration: 2.6, maxChars: 18, bg: true, pad: 70,
  fields: ["text", "text2", "color", "accent", "bg", "size", "intensity"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: true }],
  defaults: { color: "#ffffff", accent: "#ff3b6b", bg: "#2f6bff", font: "black", case: "upper" }, sample: { text: "iPhone", text2: "Android" },
}, (c) => {
  const { p } = c;
  const row = mk("div", { width: "900px", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }, null, c.root);
  const side = (txt, bg, align) => {
    const el = mk("div", { flex: "1", background: bg, color: readableOn(bg), padding: align === "right" ? "26px 84px 26px 30px" : "26px 30px 26px 84px", textAlign: align, fontSize: "60px", lineHeight: "1.05", borderRadius: align === "right" ? "28px 0 0 28px" : "0 28px 28px 0", boxShadow: sh, whiteSpace: "nowrap", overflow: "hidden" }, plainText(txt).toLocaleUpperCase("fil"), row);
    c.fit(el, { maxW: 300, maxH: 120, max: 64, min: 26, lines: 1 });
    el.style.width = "auto";
    return el;
  };
  const a = side(p.text, p.bg, "right");
  const b = side(p.text2 || "B", mix(p.bg, "#ff3b6b", 0.85), "left");
  const vs = mk("div", { position: "absolute", left: "50%", top: "50%", width: "120px", height: "120px", margin: "-60px 0 0 -60px", borderRadius: "50%", background: p.accent, color: readableOn(p.accent), display: "grid", placeItems: "center", fontSize: "52px", fontFamily: fontCss("impact").fontFamily, border: "6px solid #fff", boxShadow: sh }, "VS", row);
  const { w, h } = dims(row);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.3);
      row.style.opacity = String(1 - e.o);
      setT(a, { x: (1 - ease.out(e.i)) * -520 });
      setT(b, { x: (1 - ease.out(e.i)) * 520 });
      const k = ease.elastic(prog(t, 0.3, 0.9));
      vs.style.opacity = String(c01((t - 0.3) * 6));
      vs.style.transform = `scale(${lerp(2.5, 1, k)}) rotate(${(1 - k) * -40 + Math.sin(t * 5) * 3 * p.intensity}deg)`;
    },
  };
});

// ---- an explainer callout
defineTemplate({
  id: "callout-box", name: "Callout", tl: "Paliwanag na kahon", category: "card", moods: ["serious", "tech", "calm", "news", "warning"],
  zone: "any", anchor: { x: 0.5, y: 0.6 }, box: { w: 760, h: 220 }, duration: 3.2, maxChars: 80, bg: true, pad: 60,
  fields: ["text", "text2", "icon", "color", "accent", "bg", "size", "intensity", "dir"],
  inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#151a24", accent: "#ff9d00", icon: "bolt", text2: "TIP", dir: "down" }, sample: { text: "Save your project before you export", text2: "TIP", icon: "check" },
}, (c) => {
  const { p } = c;
  const box = mk("div", { width: "760px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "30px", padding: "24px 30px", boxShadow: sh, borderLeft: `14px solid ${p.accent}`, position: "relative", fontFamily: inter.fontFamily }, null, c.root);
  const head = mk("div", { display: "flex", alignItems: "center", gap: "12px", marginBottom: "8px" }, null, box);
  const chip = mk("div", { width: "52px", height: "52px", borderRadius: "14px", background: p.accent, display: "grid", placeItems: "center" }, null, head);
  icon(ICON_KEYS.includes(p.icon) ? p.icon : "bolt", 32, readableOn(p.accent), chip, { stroke: 2.6 });
  mk("div", { fontSize: "30px", fontWeight: "900", letterSpacing: "0.14em", color: p.accent }, plainText(p.text2 || "NOTE").toLocaleUpperCase("fil"), head);
  const body = mk("div", { fontWeight: "700", lineHeight: "1.2" }, plainText(p.text), box);
  c.fit(body, { maxW: 670, maxH: 170, max: 48, min: 26 });
  // a small tail pointing at what it explains
  const tail = mk("div", { position: "absolute", width: "0", height: "0", borderLeft: "22px solid transparent", borderRight: "22px solid transparent" }, null, box);
  if (p.dir === "up") Object.assign(tail.style, { top: "-22px", left: "80px", borderBottom: `22px solid ${p.bg}` });
  else Object.assign(tail.style, { bottom: "-22px", left: "80px", borderTop: `22px solid ${p.bg}` });
  const { w, h } = dims(box);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.45, 0.3);
      box.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(box, { y: (1 - ease.out(e.i)) * 50, s: lerp(0.9, 1, ease.back(e.i, 1.2)) });
      body.style.clipPath = `inset(0 ${100 - ease.out(prog(t, 0.3, 1.0)) * 100}% 0 0)`;
    },
  };
});

// ---- a screenshot in a browser frame
defineTemplate({
  id: "screenshot-frame", covers: true, name: "Screenshot frame", tl: "Screenshot", category: "card", moods: ["tech", "serious", "news", "calm"],
  zone: "any", anchor: { x: 0.5, y: 0.55 }, box: { w: 820, h: 640 }, duration: 3.5, maxChars: 40, bg: true, pad: 60,
  fields: ["text", "image", "color", "accent", "bg", "size", "intensity"],
  inputs: [{ key: "image", type: "image", required: false }, { key: "text", type: "text", required: false }],
  defaults: { bg: "#1b1f2a", color: "#ffffff", accent: "#ffd23f" }, sample: { text: "Step 2: click Export" },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "820px", boxSizing: "border-box", background: p.bg, borderRadius: "22px", overflow: "hidden", boxShadow: sh }, null, c.root);
  const bar = mk("div", { height: "44px", display: "flex", alignItems: "center", gap: "10px", padding: "0 18px", background: mix(p.bg, "#ffffff", 0.08) }, null, card);
  for (const col of ["#ff5f57", "#febc2e", "#28c840"]) mk("div", { width: "16px", height: "16px", borderRadius: "50%", background: col }, null, bar);
  const shot = mk("div", { width: "820px", height: "500px", backgroundColor: mix(p.bg, "#5b6cff", 0.4), backgroundSize: "cover", backgroundPosition: "center top" }, null, card);
  if (p.image) shot.style.backgroundImage = `url("${p.image}")`;
  const cap = mk("div", { padding: "16px 22px", color: p.color, fontWeight: "800", fontFamily: inter.fontFamily, borderTop: `4px solid ${p.accent}` }, plainText(p.text), card);
  if (p.text) {
    c.fit(cap, { maxW: 776, maxH: 70, max: 40, min: 24, lines: 1 });
    cap.style.width = "auto";
  } else cap.style.display = "none";
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.5, 0.35);
      card.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(card, { s: lerp(0.85, 1, ease.out(e.i)), y: (1 - ease.out(e.i)) * 60 });
      // a slow push-in on the screenshot (Ken Burns), as if pointing at it
      shot.style.backgroundSize = `${100 + 10 * p.intensity * ease.inOut(prog(t, 0.5, dur))}%`;
    },
  };
});
