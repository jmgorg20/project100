// Pointers: arrows, circles and scribbles. The Director sets x / y (and angle) so they land on
// the thing they point at; `tip` in the meta says where the point of the shape is.
import { defineTemplate, mk, ease, prog, c01, lerp, envelope, setT, plainText, svgEl, legible, rgba, rng, fontCss } from "../engine.js";

const wobble = (id, n, amp) => { const r = rng(id); return Array.from({ length: n }, () => (r() - 0.5) * 2 * amp); };

// ---- hand-drawn arrow
defineTemplate({
  id: "arrow-point", name: "Pointing arrow", tl: "Arrow na nakaturo", category: "pointer", moods: ["hype", "playful", "serious", "tech", "money", "funny"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 360, h: 200 }, duration: 1.8, maxChars: 24, pad: 70, tip: { dist: 158 },
  fields: ["text", "color", "accent", "angle", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }],
  defaults: { color: "#ffffff", accent: "#ffd23f", angle: 0, font: "hand" }, sample: { text: "look here", angle: 20 },
}, (c) => {
  const { p } = c;
  const W = 360, H = 200;
  const wrap = mk("div", { position: "relative", width: `${W}px`, height: `${H}px` }, null, c.root);
  // the arrow is drawn pointing right, then the whole box is turned by `angle`
  const turn = mk("div", { position: "absolute", inset: "0", transformOrigin: "50% 50%", transform: `rotate(${p.angle}deg)` }, null, wrap);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H }, turn);
  svg.style.overflow = "visible";
  const w = wobble(5, 4, 10);
  const d = `M 24 ${130 + w[0]} C 110 ${40 + w[1]}, 210 ${40 + w[2]}, ${W - 40} ${H / 2 + w[3] * 0.3}`;
  const shadowPath = svgEl("path", { d, fill: "none", stroke: "rgba(0,0,0,.45)", "stroke-width": 14, "stroke-linecap": "round" }, svg);
  const path = svgEl("path", { d, fill: "none", stroke: p.accent, "stroke-width": 10, "stroke-linecap": "round" }, svg);
  const head = svgEl("path", { d: `M ${W - 86} ${H / 2 - 48} L ${W - 22} ${H / 2} L ${W - 88} ${H / 2 + 44}`, fill: "none", stroke: p.accent, "stroke-width": 10, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
  const headShadow = svgEl("path", { d: head.getAttribute("d"), fill: "none", stroke: "rgba(0,0,0,.45)", "stroke-width": 14, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg);
  svg.insertBefore(headShadow, path);
  const len = path.getTotalLength();
  for (const el of [path, shadowPath]) el.setAttribute("stroke-dasharray", `${len + 4}`);
  const label = mk("div", { position: "absolute", left: "0", top: "0", fontSize: "50px", color: p.color, fontFamily: fontCss("hand").fontFamily, fontWeight: "700", textShadow: legible(), whiteSpace: "nowrap", transformOrigin: "0 100%", transform: "translate(0,-52px) rotate(-6deg)" }, plainText(p.text), wrap);
  if (!p.text) label.style.display = "none";
  return {
    w: W, h: H,
    update(t, dur) {
      const e = envelope(t, dur, 0.1, 0.25);
      const k = ease.inOut(prog(t, 0, 0.55));
      for (const el of [path, shadowPath]) el.setAttribute("stroke-dashoffset", String((len + 4) * (1 - k)));
      const hk = ease.out(prog(t, 0.42, 0.62));
      for (const el of [head, headShadow]) el.style.opacity = String(hk);
      wrap.style.opacity = String(1 - e.o);
      const nudge = Math.sin(t * 7) * 6 * p.intensity * (t > 0.6 ? 1 : 0);
      turn.style.transform = `rotate(${p.angle}deg) translate(${nudge}px,0)`;
      label.style.opacity = String(ease.out(prog(t, 0.3, 0.7)));
    },
  };
});

// ---- circle drawn around something
defineTemplate({
  id: "circle-ring", name: "Circle around it", tl: "Bilog sa paligid", category: "pointer", moods: ["hype", "serious", "playful", "warning", "tech", "money"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 360, h: 260 }, duration: 1.8, maxChars: 24, pad: 60, tip: { dist: 0 },
  fields: ["text", "accent", "color", "size", "intensity"], inputs: [{ key: "text", type: "text", required: false }],
  defaults: { accent: "#ff3b3b", color: "#ffffff" }, sample: { text: "" },
}, (c) => {
  const { p } = c;
  const W = 360, H = 260;
  const wrap = mk("div", { position: "relative", width: `${W}px`, height: `${H}px` }, null, c.root);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H }, wrap);
  svg.style.overflow = "visible";
  const w = wobble(9, 6, 7);
  // an almost-closed, slightly wobbly loop that overshoots its start, like a pen circling
  const d = `M ${40 + w[0]} ${70 + w[1]} C ${60 + w[2]} ${8}, ${W - 70} ${4 + w[3]}, ${W - 24} ${H / 2 - 20 + w[4]} C ${W - 8} ${H - 40}, ${W - 120} ${H - 6}, ${W / 2} ${H - 10 + w[5]} C 70 ${H - 14}, 8 ${H - 70}, 18 ${H / 2 - 10} C 26 ${50}, 110 ${14}, 170 ${24}`;
  const back = svgEl("path", { d, fill: "none", stroke: "rgba(0,0,0,.4)", "stroke-width": 15, "stroke-linecap": "round" }, svg);
  const path = svgEl("path", { d, fill: "none", stroke: p.accent, "stroke-width": 10, "stroke-linecap": "round" }, svg);
  const len = path.getTotalLength();
  for (const el of [path, back]) el.setAttribute("stroke-dasharray", `${len + 4}`);
  const label = mk("div", { position: "absolute", left: "50%", top: "100%", marginTop: "10px", transform: "translateX(-50%)", fontSize: "44px", fontWeight: "800", color: p.color, textShadow: legible(), whiteSpace: "nowrap", fontFamily: fontCss("inter").fontFamily }, plainText(p.text), wrap);
  if (!p.text) label.style.display = "none";
  return {
    w: W, h: H,
    update(t, dur) {
      const e = envelope(t, dur, 0.1, 0.25);
      const k = ease.inOut(prog(t, 0, 0.6));
      for (const el of [path, back]) el.setAttribute("stroke-dashoffset", String((len + 4) * (1 - k)));
      wrap.style.opacity = String(1 - e.o);
      setT(wrap, { s: 1 + 0.03 * p.intensity * Math.sin(t * 6) * (t > 0.6 ? 1 : 0) });
      label.style.opacity = String(ease.out(prog(t, 0.4, 0.8)));
    },
  };
});

// ---- scribble underline
defineTemplate({
  id: "scribble-underline", name: "Scribble underline", tl: "Guhit-guhit", category: "pointer", moods: ["playful", "funny", "hype", "emotion"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 393, h: 160 }, duration: 1.8, maxChars: 28, pad: 50,
  fields: ["text", "color", "accent", "font", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }],
  defaults: { color: "#ffffff", accent: "#ff5c8a", font: "hand" }, sample: { text: "this part!" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { display: "inline-block", position: "relative", paddingBottom: "34px" }, null, c.root);
  const txt = mk("div", { color: p.color, textShadow: legible(), whiteSpace: "nowrap", fontWeight: "700", lineHeight: "1.05" }, plainText(p.text), wrap);
  c.fit(txt, { maxW: 840, maxH: 140, max: 120, min: 40, lines: 1 });
  txt.style.width = "auto";
  const width = Math.ceil(txt.getBoundingClientRect().width);
  const svg = svgEl("svg", { viewBox: `0 0 ${width} 34`, width, height: 34 }, wrap);
  Object.assign(svg.style, { position: "absolute", left: "0", bottom: "0", overflow: "visible" });
  let d = `M 4 22`;
  const steps = Math.max(6, Math.round(width / 38));
  for (let i = 1; i <= steps; i++) d += ` Q ${(i - 0.5) * (width / steps)} ${i % 2 ? 2 : 32}, ${i * (width / steps) - 4} ${i % 2 ? 22 : 12}`;
  const back = svgEl("path", { d, fill: "none", stroke: "rgba(0,0,0,.4)", "stroke-width": 11, "stroke-linecap": "round" }, svg);
  const path = svgEl("path", { d, fill: "none", stroke: p.accent, "stroke-width": 7, "stroke-linecap": "round" }, svg);
  const len = path.getTotalLength();
  for (const el of [path, back]) el.setAttribute("stroke-dasharray", `${len + 4}`);
  const r = wrap.getBoundingClientRect();
  return {
    w: Math.ceil(r.width), h: Math.ceil(r.height),
    update(t, dur) {
      const e = envelope(t, dur, 0.25, 0.25);
      txt.style.opacity = String(ease.out(e.i) * (1 - e.o));
      const k = ease.inOut(prog(t, 0.3, 0.9));
      for (const el of [path, back]) el.setAttribute("stroke-dashoffset", String((len + 4) * (1 - k)));
      svg.style.opacity = String(1 - e.o);
    },
  };
});
void rgba; void lerp; void c01;
