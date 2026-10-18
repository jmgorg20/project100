// Cards and pills: floating UI-style graphics (prompt card, notifications, polaroid, lower thirds).
import {
  defineTemplate, mk, icon, ease, prog, c01, lerp, envelope, readableOn, rgba, setT, plainText, mix, ICON_KEYS, rng,
  fontCss, legible, svgEl,
} from "../engine.js";

const sh = "0 18px 40px rgba(0,0,0,.38),0 2px 6px rgba(0,0,0,.25)";
const dims = (el) => { const r = el.getBoundingClientRect(); return { w: Math.ceil(r.width), h: Math.ceil(r.height) }; };
const inter = fontCss("inter");
const pop = (e) => ease.back(e.i, 1.4);

// ---- chat / prompt card with typing
defineTemplate({
  id: "prompt-card", name: "Prompt card (typing)", tl: "Prompt card na nagta-type", category: "card", moods: ["tech", "hype", "calm"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 800, h: 239 }, duration: 3.6, maxChars: 90, bg: true, pad: 70,
  fields: ["text", "text2", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#1f2430", accent: "#6c5ce7", text2: "Ask anything" }, sample: { text: "Make me a video that goes viral", text2: "Ask anything" },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "800px", background: p.bg, color: p.color, borderRadius: "34px", padding: "28px 32px 24px", boxShadow: sh, fontFamily: inter.fontFamily, boxSizing: "border-box" }, null, c.root);
  const head = mk("div", { display: "flex", alignItems: "center", gap: "14px", marginBottom: "16px" }, null, card);
  const av = mk("div", { width: "46px", height: "46px", borderRadius: "50%", background: p.accent, display: "grid", placeItems: "center" }, null, head);
  icon("star", 26, readableOn(p.accent), av, { fill: true, stroke: 1 });
  mk("div", { fontSize: "28px", fontWeight: "700", opacity: "0.65" }, plainText(p.text2), head);
  const body = mk("div", { fontSize: "42px", fontWeight: "600", lineHeight: "1.25", minHeight: "1.25em", position: "relative" }, null, card);
  const ghost = mk("div", { visibility: "hidden" }, plainText(p.text), body);
  const live = mk("div", { position: "absolute", left: "0", top: "0", right: "0" }, null, body);
  const typed = mk("span", {}, null, live);
  const caret = mk("span", { display: "inline-block", width: "3px", height: "1.05em", background: p.accent, verticalAlign: "-0.15em", marginLeft: "2px" }, null, live);
  c.fit(ghost, { maxW: 736, maxH: 220, max: 44, min: 26 });
  live.style.fontSize = ghost.style.fontSize;
  const foot = mk("div", { display: "flex", justifyContent: "flex-end", marginTop: "14px" }, null, card);
  const send = mk("div", { width: "56px", height: "56px", borderRadius: "50%", background: p.accent, display: "grid", placeItems: "center" }, null, foot);
  svgEl("path", { d: "M12 19V6M6 11l6-6 6 6", stroke: readableOn(p.accent), "stroke-width": 3, fill: "none", "stroke-linecap": "round", "stroke-linejoin": "round" }, svgEl("svg", { viewBox: "0 0 24 24", width: 30, height: 30 }, send));
  const chars = [...plainText(p.text)];
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.3);
      const n = Math.floor(chars.length * ease.lin(c01((t - 0.5) / Math.max(0.5, dur * 0.5))));
      typed.textContent = chars.slice(0, n).join("");
      caret.style.opacity = String(Math.floor(t * 2.5) % 2 === 0 || n < chars.length ? 1 : 0);
      card.style.opacity = String(c01(e.i * 2) * (1 - e.o));
      setT(card, { s: lerp(0.86, 1, pop(e)) * (1 - 0.06 * e.o), y: (1 - ease.out(e.i)) * 40 });
      const clicked = t > 0.5 + dur * 0.5 + 0.1;
      setT(send, { s: clicked ? 1 + 0.25 * Math.sin(Math.PI * c01((t - 0.6 - dur * 0.5) / 0.3)) : 1 });
      void ghost;
    },
  };
});

// ---- stacked notifications
defineTemplate({
  id: "notification-stack", name: "Notification stack", tl: "Mga notification", category: "card", moods: ["tech", "hype", "money", "playful"],
  zone: "upper", anchor: { x: 0.5, y: 0.2 }, box: { w: 780, h: 354 }, duration: 3.4, maxChars: 40, bg: true, pad: 60,
  fields: ["text", "items", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "items", type: "list", required: false }],
  defaults: { bg: "#ffffff", color: "#1d2433", accent: "#34c759", icon: "bell" }, sample: { text: "New order!", items: ["Payment received", "5 new followers"] },
}, (c) => {
  const { p } = c;
  const lines = [p.text, ...p.items].filter(Boolean).slice(0, 4).map(plainText);
  const names = ["bell", "money", "user", "heart"];
  const gap = 112;
  const wrap = mk("div", { position: "relative", width: "780px", height: `${gap * (lines.length - 1) + 130}px` }, null, c.root);
  const cards = lines.map((line, i) => {
    const el = mk("div", {
      position: "absolute", left: "0", top: `${i * gap}px`, width: "780px", height: "130px", boxSizing: "border-box", background: rgba(p.bg, 0.97), color: p.color,
      borderRadius: "30px", boxShadow: sh, display: "flex", alignItems: "center", gap: "22px", padding: "0 28px", fontFamily: inter.fontFamily,
    }, null, wrap);
    const chip = mk("div", { width: "74px", height: "74px", borderRadius: "20px", background: i === 0 ? p.accent : mix(p.accent, "#5b6cff", 0.5 * i), display: "grid", placeItems: "center", flex: "none" }, null, el);
    icon(i === 0 && ICON_KEYS.includes(p.icon) ? p.icon : names[i % names.length], 40, readableOn(p.accent), chip);
    const col = mk("div", { minWidth: "0", flex: "1" }, null, el);
    const title = mk("div", { fontWeight: "800", lineHeight: "1.1", whiteSpace: "nowrap" }, line, col);
    c.fit(title, { maxW: 600, maxH: 60, max: 44, min: 22, lines: 1 });
    mk("div", { fontSize: "24px", opacity: "0.55", marginTop: "4px" }, i === 0 ? "now" : `${i + 1}m ago`, col);
    return el;
  });
  return {
    w: 780, h: gap * (lines.length - 1) + 130,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.3);
      cards.forEach((el, i) => {
        const k = ease.back(prog(t, i * 0.32, i * 0.32 + 0.45), 1.3);
        el.style.opacity = String(c01(k * 3) * (1 - e.o));
        setT(el, { y: (1 - k) * -130 + e.o * -40, s: 1 - (cards.length - 1 - i) * 0.0 });
        el.style.zIndex = String(cards.length - i);
      });
    },
  };
});

// ---- polaroid
defineTemplate({
  id: "polaroid-card", name: "Polaroid", tl: "Polaroid", category: "card", moods: ["emotion", "playful", "calm", "funny"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 520, h: 640 }, duration: 2.8, maxChars: 28, bg: true, pad: 80,
  fields: ["text", "image", "color", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }, { key: "image", type: "image", required: false }],
  defaults: { bg: "#fbfaf5", color: "#2b2b2b", font: "hand", accent: "#ff7a90", emoji: "📸" }, sample: { text: "best day ever", emoji: "🌴" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { position: "relative", width: "520px", height: "640px" }, null, c.root);
  const mkCard = () => mk("div", { position: "absolute", left: "0", top: "0", width: "520px", height: "640px", background: p.bg, borderRadius: "10px", boxShadow: sh, boxSizing: "border-box", padding: "30px 30px 0" }, null, wrap);
  const back = mkCard();
  const front = mkCard();
  const photo = mk("div", { width: "460px", height: "460px", background: `linear-gradient(135deg,${p.accent},${mix(p.accent, "#5b6cff", 0.6)})`, display: "grid", placeItems: "center", fontSize: "190px", overflow: "hidden", backgroundSize: "cover", backgroundPosition: "center" }, null, front);
  if (p.image) photo.style.backgroundImage = `url("${p.image}")`;
  else mk("div", { fontFamily: fontCss("inter").fontFamily, lineHeight: "1" }, p.emoji || "📸", photo);
  const cap = mk("div", { color: p.color, textAlign: "center", marginTop: "14px", lineHeight: "1.05", fontWeight: "700" }, plainText(p.text), front);
  c.fit(cap, { maxW: 450, maxH: 110, max: 80, min: 34, lines: 2 });
  return {
    w: 520, h: 640,
    update(t, dur) {
      const e = envelope(t, dur, 0.5, 0.35);
      const k = ease.back(e.i, 1.1);
      wrap.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(front, { r: lerp(14, -4, k) + Math.sin(t * 1.6) * 0.8, s: lerp(0.5, 1, k), y: (1 - k) * -120 });
      setT(back, { r: lerp(24, 7, k), s: lerp(0.5, 0.97, k), x: lerp(0, 22, k) });
    },
  };
});

// ---- icon badge
defineTemplate({
  id: "icon-badge", name: "Icon badge", tl: "Icon badge", category: "card", moods: ["tech", "hype", "playful", "money", "serious"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 436, h: 271 }, duration: 2, maxChars: 22, bg: true, pad: 70,
  fields: ["text", "icon", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }],
  defaults: { icon: "bolt", accent: "#ff7a1a", color: "#ffffff" }, sample: { text: "Fast results", icon: "bolt" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "18px", minWidth: "200px" }, null, c.root);
  const sq = mk("div", { width: "190px", height: "190px", borderRadius: "48px", background: `linear-gradient(145deg,${mix(p.accent, "#ffffff", 0.25)},${p.accent})`, display: "grid", placeItems: "center", boxShadow: `0 16px 34px ${rgba(p.accent, 0.5)}` }, null, wrap);
  icon(ICON_KEYS.includes(p.icon) ? p.icon : "bolt", 112, readableOn(p.accent), sq, { stroke: 2 });
  const label = mk("div", { fontSize: "46px", fontWeight: "800", color: p.color, textShadow: legible(), whiteSpace: "nowrap", textAlign: "center" }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 560, maxH: 70, max: 52, min: 26, lines: 1 }); else label.style.display = "none";
  const { w, h } = dims(wrap);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.25);
      const k = ease.elastic(e.i);
      wrap.style.opacity = String(c01(e.i * 4) * (1 - e.o));
      setT(sq, { s: lerp(0.2, 1, k) * (1 + 0.04 * p.intensity * Math.sin(t * 6)), r: (1 - k) * -25 });
      setT(label, { y: (1 - ease.out(prog(t, 0.15, 0.5))) * 20 });
    },
  };
});

// ---- clock
defineTemplate({
  id: "clock-timer", name: "Clock", tl: "Orasan", category: "card", moods: ["urgent", "serious", "money", "tech"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 536, h: 388 }, duration: 2.6, maxChars: 24, bg: true, pad: 60,
  fields: ["text", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#ffffff", accent: "#ff4d4d", font: "black" }, sample: { text: "24 hours left" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "20px" }, null, c.root);
  const face = mk("div", { width: "300px", height: "300px", position: "relative", borderRadius: "50%", background: p.bg, boxShadow: sh, border: `10px solid ${p.accent}`, boxSizing: "border-box" }, null, wrap);
  for (let i = 0; i < 12; i++) mk("div", { position: "absolute", left: "50%", top: "50%", width: "6px", height: i % 3 ? "14px" : "24px", marginLeft: "-3px", marginTop: i % 3 ? "-128px" : "-128px", background: "#2b2f3a", borderRadius: "3px", transformOrigin: `50% ${i % 3 ? 128 : 128}px`, transform: `rotate(${i * 30}deg)` }, null, face);
  const hand = (len, wd, col) => mk("div", { position: "absolute", left: "50%", top: "50%", width: `${wd}px`, height: `${len}px`, marginLeft: `${-wd / 2}px`, marginTop: `${-len + 10}px`, background: col, borderRadius: `${wd}px`, transformOrigin: `50% ${len - 10}px` }, null, face);
  const minute = hand(100, 10, "#2b2f3a");
  const second = hand(116, 5, p.accent);
  mk("div", { position: "absolute", left: "50%", top: "50%", width: "22px", height: "22px", marginLeft: "-11px", marginTop: "-11px", borderRadius: "50%", background: "#2b2f3a" }, null, face);
  const label = mk("div", { fontSize: "50px", color: p.color, textShadow: legible(), whiteSpace: "nowrap", textAlign: "center", fontWeight: "900" }, plainText(p.text), wrap);
  if (p.text) c.fit(label, { maxW: 700, maxH: 70, max: 56, min: 26, lines: 1 }); else label.style.display = "none";
  const { w, h } = dims(wrap);
  return {
    w: Math.max(w, 300), h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.25);
      wrap.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(face, { s: lerp(0.5, 1, ease.back(e.i, 1.2)) });
      const spin = ease.inOut(prog(t, 0.2, dur - 0.3));
      minute.style.transform = `rotate(${spin * 360 * 1}deg)`;
      second.style.transform = `rotate(${spin * 360 * 6}deg)`;
    },
  };
});

// ---- lower-third pill
defineTemplate({
  id: "lower-third-pill", name: "Lower-third pill", tl: "Pill sa ibaba", category: "pill", moods: ["serious", "tech", "news", "calm", "hype"],
  zone: "lower", anchor: { x: 0.5, y: 0.76 }, box: { w: 568, h: 90 }, duration: 2.8, maxChars: 40, bg: true, pad: 50,
  fields: ["text", "text2", "icon", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#161a24", accent: "#2f6bff", icon: "check" }, sample: { text: "Revision #11 check", text2: "" },
}, (c) => {
  const { p } = c;
  const pill = mk("div", { display: "inline-flex", alignItems: "center", gap: "18px", background: p.bg, color: p.color, borderRadius: "999px", padding: "16px 36px 16px 18px", boxShadow: sh, maxWidth: "880px", boxSizing: "border-box" }, null, c.root);
  const dot = mk("div", { width: "58px", height: "58px", borderRadius: "50%", background: p.accent, display: "grid", placeItems: "center", flex: "none" }, null, pill);
  icon(ICON_KEYS.includes(p.icon) ? p.icon : "check", 34, readableOn(p.accent), dot, { stroke: 3 });
  const col = mk("div", { minWidth: "0" }, null, pill);
  const t1 = mk("div", { fontWeight: "800", whiteSpace: "nowrap", lineHeight: "1.1" }, plainText(p.text), col);
  c.fit(t1, { maxW: 740, maxH: 60, max: 48, min: 24, lines: 1 });
  t1.style.width = "auto";
  if (p.text2) mk("div", { fontSize: "26px", opacity: "0.6", marginTop: "2px", whiteSpace: "nowrap" }, plainText(p.text2), col);
  const { w, h } = dims(pill);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.3);
      pill.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(pill, { x: (1 - ease.out(e.i)) * -120 + e.o * 60, s: lerp(0.92, 1, ease.out(e.i)) });
      dot.style.transform = `scale(${1 + 0.1 * Math.sin(Math.PI * c01((t - 0.35) / 0.35))})`;
    },
  };
});

// ---- "Comment EDIT" pill with a click
defineTemplate({
  id: "comment-pill", name: "Comment keyword", tl: "Comment keyword", category: "pill", moods: ["hype", "playful", "tech", "money"],
  zone: "lower", anchor: { x: 0.5, y: 0.74 }, box: { w: 455, h: 98 }, duration: 2.6, maxChars: 16, bg: true, pad: 70,
  fields: ["text", "text2", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#161a24", accent: "#ff3d71", text2: "Comment", case: "upper" }, sample: { text: "EDIT", text2: "Comment" },
}, (c) => {
  const { p } = c;
  const pill = mk("div", { display: "inline-flex", alignItems: "center", gap: "16px", background: p.bg, color: p.color, borderRadius: "999px", padding: "14px 18px 14px 36px", boxShadow: sh, position: "relative" }, null, c.root);
  mk("div", { fontWeight: "600", fontSize: "46px", whiteSpace: "nowrap" }, plainText(p.text2) || "Comment", pill);
  const chip = mk("div", { background: p.accent, color: readableOn(p.accent), borderRadius: "999px", padding: "8px 30px", fontWeight: "900", fontSize: "46px", letterSpacing: "0.04em", whiteSpace: "nowrap" }, plainText(p.text), pill);
  c.fit(chip, { maxW: 360, maxH: 70, max: 46, min: 26, lines: 1 });
  chip.style.width = "auto";
  const ripple = mk("div", { position: "absolute", width: "40px", height: "40px", borderRadius: "50%", border: `4px solid ${p.accent}`, left: "0", top: "0", opacity: "0", pointerEvents: "none" }, null, pill);
  const cursor = mk("div", { position: "absolute", left: "0", top: "0" }, null, pill);
  const cur = svgEl("svg", { viewBox: "0 0 24 24", width: 56, height: 56 }, cursor);
  svgEl("path", { d: "M5 3l14 8-6 1.5L10 19z", fill: "#ffffff", stroke: "#111", "stroke-width": 1.6, "stroke-linejoin": "round" }, cur);
  const { w, h } = dims(pill);
  const tx = w - 90, ty = h * 0.55;
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.35, 0.3);
      pill.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(pill, { s: lerp(0.85, 1, ease.back(e.i, 1.3)) });
      const k = ease.inOut(prog(t, 0.55, 1.2));
      cursor.style.opacity = String(c01((t - 0.45) * 5) * (1 - e.o));
      setT(cursor, { x: lerp(w * 0.9, tx, k), y: lerp(h * 1.6, ty, k) + (t > 1.2 ? 4 : 0) });
      const rk = prog(t, 1.2, 1.7);
      ripple.style.opacity = String(rk > 0 ? 1 - rk : 0);
      ripple.style.left = `${tx - 20}px`;
      ripple.style.top = `${ty - 18}px`;
      setT(ripple, { s: 1 + rk * 2.2 });
      chip.style.transform = `scale(${t > 1.2 ? 1 + 0.08 * Math.sin(Math.PI * c01((t - 1.2) / 0.3)) : 1})`;
    },
  };
});

// ---- follow pill with a button state change
defineTemplate({
  id: "follow-pill", name: "Follow / Following", tl: "Follow / Following", category: "pill", moods: ["playful", "hype", "tech", "calm"],
  zone: "lower", anchor: { x: 0.5, y: 0.72 }, box: { w: 715, h: 104 }, duration: 3, maxChars: 24, bg: true, pad: 60,
  fields: ["text", "text2", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { bg: "#ffffff", color: "#161a24", accent: "#2f6bff", text2: "Follow", items: ["Following"] }, sample: { text: "@yourhandle", text2: "Follow", items: ["Following"] },
}, (c) => {
  const { p } = c;
  const pill = mk("div", { display: "inline-flex", alignItems: "center", gap: "22px", background: p.bg, color: p.color, borderRadius: "999px", padding: "14px 18px 14px 18px", boxShadow: sh }, null, c.root);
  const letter = ([...plainText(p.text).replace(/^@/, "")][0] || "A").toLocaleUpperCase("fil");
  const av = mk("div", { width: "76px", height: "76px", borderRadius: "50%", background: `linear-gradient(140deg,${p.accent},${mix(p.accent, "#ff4fa3", 0.7)})`, color: "#fff", display: "grid", placeItems: "center", fontWeight: "900", fontSize: "40px" }, letter, pill);
  const name = mk("div", { fontWeight: "800", whiteSpace: "nowrap" }, plainText(p.text), pill);
  c.fit(name, { maxW: 420, maxH: 56, max: 46, min: 24, lines: 1 });
  name.style.width = "auto";
  const a = plainText(p.text2) || "Follow", b = plainText(p.items[0] || "Following");
  const btn = mk("div", { position: "relative", borderRadius: "999px", padding: "14px 34px", fontWeight: "800", fontSize: "38px", whiteSpace: "nowrap", minWidth: "200px", textAlign: "center", marginLeft: "10px", transformOrigin: "50% 50%" }, null, pill);
  const sizer = mk("div", { visibility: "hidden", height: "0", overflow: "hidden", fontWeight: "800" }, a.length > b.length ? a : b, btn);
  const label = mk("div", { position: "absolute", inset: "14px 0 0 0", textAlign: "center" }, a, btn);
  const { w, h } = dims(pill);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.3);
      pill.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(pill, { y: (1 - ease.out(e.i)) * 50, s: lerp(0.9, 1, ease.out(e.i)) });
      const on = t > dur * 0.45;
      label.textContent = on ? b : a;
      btn.style.background = on ? "#e9ecf2" : p.accent;
      label.style.color = on ? "#2b2f3a" : readableOn(p.accent);
      btn.style.transform = `scale(${1 + 0.12 * Math.sin(Math.PI * c01((t - dur * 0.45) / 0.3))})`;
      void sizer;
    },
  };
});

// ---- title card with chips
defineTemplate({
  id: "title-chips", name: "Title with chips", tl: "Title na may chips", category: "card", moods: ["tech", "serious", "calm", "news", "hype"],
  zone: "center", anchor: { x: 0.5, y: 0.45 }, box: { w: 800, h: 311 }, duration: 3.2, maxChars: 40, bg: true, pad: 60,
  fields: ["text", "text2", "items", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "items", type: "list", required: false }],
  defaults: { bg: "#10131c", color: "#ffffff", accent: "#7c5cff", font: "black", items: ["Tips", "Tricks", "Guide"] }, sample: { text: "Editing basics", text2: "Part 1", items: ["Cuts", "Captions", "Music"] },
}, (c) => {
  const { p } = c;
  const card = mk("div", { width: "800px", boxSizing: "border-box", background: p.bg, color: p.color, borderRadius: "40px", padding: "40px 44px", boxShadow: sh, border: `2px solid ${rgba("#ffffff", 0.08)}` }, null, c.root);
  if (p.text2) mk("div", { fontSize: "28px", letterSpacing: "0.2em", textTransform: "uppercase", color: p.accent, fontWeight: "800", marginBottom: "10px" }, plainText(p.text2), card);
  const title = mk("div", { lineHeight: "1.05" }, plainText(p.text), card);
  c.fit(title, { maxW: 712, maxH: 220, max: 92, min: 36 });
  const row = mk("div", { display: "flex", flexWrap: "wrap", gap: "14px", marginTop: "26px" }, null, card);
  const chips = (p.items.length ? p.items : []).slice(0, 5).map((it) => mk("div", { padding: "10px 26px", borderRadius: "999px", background: rgba(p.accent, 0.22), border: `2px solid ${p.accent}`, fontSize: "30px", fontWeight: "700", whiteSpace: "nowrap", fontFamily: inter.fontFamily }, plainText(it), row));
  if (!chips.length) row.style.display = "none";
  const { w, h } = dims(card);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.3);
      card.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(card, { s: lerp(0.88, 1, ease.back(e.i, 1.2)) });
      chips.forEach((ch, i) => { const k = ease.back(prog(t, 0.45 + i * 0.12, 0.8 + i * 0.12), 1.6); ch.style.opacity = String(c01(k * 2)); setT(ch, { s: lerp(0.4, 1, k) }); });
    },
  };
});
void rng;
