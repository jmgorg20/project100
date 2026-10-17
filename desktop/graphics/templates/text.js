// Kinetic text: the words themselves pop, slide, glow, stamp or type in.
import {
  defineTemplate, mk, wordSpans, letterSpans, emphasis, plainText, ease, prog, c01, lerp, envelope, readableOn, rgba,
  legible, rng, setT, fontCss, mix,
} from "../engine.js";

const shadow = (q = 1) => legible(q);

/** A block of fitted text. Returns the node; `c.fit` has recorded the font size. */
function block(c, { maxW = 840, maxH = 360, max = 150, css = {}, lines = 0 } = {}) {
  const { p } = c;
  const node = mk("div", {
    textAlign: p.align, lineHeight: "1.04", width: `${maxW}px`, color: p.color, position: "relative",
    textShadow: shadow(), ...css,
  }, null, c.root);
  return { node, fit: () => c.fit(node, { maxW, maxH, max, lines }), maxW };
}
const size = (node) => ({ w: Math.ceil(node.getBoundingClientRect().width), h: Math.ceil(node.getBoundingClientRect().height) });

// ---- 1. heavy uppercase pop, word by word
defineTemplate({
  id: "pop-heavy", name: "Heavy pop", tl: "Malaking pop", category: "text", moods: ["hype", "urgent", "money", "serious"],
  zone: "center", anchor: { x: 0.5, y: 0.42 }, box: { w: 840, h: 240 }, duration: 1.8, words: true, maxChars: 44,
  defaults: { font: "impact", case: "upper", accent: "#ffd23f" }, sample: { text: "DOUBLE YOUR *SALES* TODAY" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 170 });
  const spans = wordSpans(b.node, p.text);
  const em = emphasis(spans);
  em.forEach((s) => { s.style.color = p.accent; });
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.2, 0.2);
      spans.forEach((s, i) => {
        const k = ease.back(prog(t, i * 0.09, i * 0.09 + 0.28), 1.2 + 2 * p.intensity);
        const isEm = em.includes(s);
        const sc = lerp(0.3, 1, k) * (isEm ? 1 + 0.08 * p.intensity * Math.sin(t * 9) * (1 - e.o) : 1);
        s.style.opacity = String(c01(k * 1.6) * (1 - e.o));
        setT(s, { s: sc * (1 + 0.12 * e.o), y: (1 - c01(k)) * 20 });
      });
    },
  };
});

// ---- 2. thin, letter-spaced
defineTemplate({
  id: "thin-spaced", name: "Thin spaced", tl: "Manipis na may espasyo", category: "text", moods: ["calm", "luxury", "serious", "emotion"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 800, h: 140 }, duration: 2.4, maxChars: 40,
  defaults: { font: "thin", case: "upper" }, sample: { text: "take a deep breath" },
}, (c) => {
  const { p } = c;
  const b = block(c, { maxW: 800, maxH: 220, max: 84, css: { letterSpacing: "0.34em", paddingLeft: "0.34em" } });
  b.node.textContent = plainText(p.text);
  b.fit();
  const line = mk("div", { height: "2px", background: p.accent, margin: "18px auto 0", width: "0px" }, null, c.root);
  const { w, h } = size(b.node);
  return {
    w, h: h + 20,
    update(t, dur) {
      const e = envelope(t, dur, 0.9, 0.5);
      b.node.style.opacity = String(ease.out(e.i) * (1 - e.o));
      setT(b.node, { s: lerp(1.12, 1, ease.out(e.i)) });
      line.style.width = `${Math.round(w * 0.35 * ease.inOut(e.i) * (1 - e.o))}px`;
    },
  };
});

// ---- 3. glow / blur-in
defineTemplate({
  id: "glow-blur-in", name: "Glow blur-in", tl: "Kumikinang na lumilitaw", category: "text", moods: ["tech", "hype", "emotion", "calm"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 840, h: 200 }, duration: 2.2, maxChars: 40, pad: 90,
  defaults: { font: "black", accent: "#7aa8ff" }, sample: { text: "The *future* is here" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 120 });
  const spans = wordSpans(b.node, p.text);
  const em = emphasis(spans);
  em.forEach((s) => { s.style.color = p.accent; });
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.7, 0.4);
      spans.forEach((s, i) => {
        const k = ease.out(prog(t, i * 0.12, i * 0.12 + 0.5));
        const glow = (0.5 + 0.5 * Math.sin(t * 4 + i)) * p.intensity;
        s.style.opacity = String(k * (1 - e.o));
        s.style.filter = `blur(${c.blur((1 - k) * 22 + e.o * 14)}px)`;
        s.style.textShadow = `0 0 ${12 + 16 * glow}px ${rgba(p.accent, 0.5 + 0.4 * glow)},0 2px 8px rgba(0,0,0,.5)`;
        setT(s, { s: lerp(1.25, 1, k) });
      });
    },
  };
});

// ---- 4. bounce words
defineTemplate({
  id: "bounce-words", name: "Bounce words", tl: "Tumatalbog na salita", category: "text", moods: ["funny", "playful", "hype"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 840, h: 220 }, duration: 2, words: true, maxChars: 44, pad: 110,
  defaults: { font: "comic", accent: "#ff5c8a", case: "upper" }, sample: { text: "Wait for *it*" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 150, css: { WebkitTextStroke: "0px", paintOrder: "stroke fill" } });
  const spans = wordSpans(b.node, p.text);
  const em = emphasis(spans);
  em.forEach((s) => { s.style.color = p.accent; });
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h: h + 40,
    update(t, dur) {
      const e = envelope(t, dur, 0.2, 0.25);
      spans.forEach((s, i) => {
        const k = prog(t, i * 0.11, i * 0.11 + 0.55);
        const drop = (1 - ease.bounce(k)) * -90 * (0.5 + p.intensity);
        s.style.opacity = String(c01(k * 5) * (1 - e.o));
        setT(s, { y: drop + e.o * 40, r: (i % 2 ? 1 : -1) * 4 * (1 - k) });
      });
    },
  };
});

// ---- 5. slide up out of a mask
defineTemplate({
  id: "slide-up", name: "Slide up", tl: "Pasulong na pataas", category: "text", moods: ["calm", "serious", "news", "tech", "luxury"],
  zone: "lower", anchor: { x: 0.5, y: 0.7 }, box: { w: 840, h: 200 }, duration: 2.2, words: true, maxChars: 56,
  defaults: { font: "inter", accent: "#58c8ff" }, sample: { text: "Three steps to *finish faster*" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 96 });
  const spans = wordSpans(b.node, p.text);
  emphasis(spans).forEach((s) => { s.style.color = p.accent; });
  // each word sits in a clip window so it rises out of nothing
  const wraps = spans.map((s) => {
    const w = mk("span", { display: "inline-block", overflow: "hidden", verticalAlign: "bottom", padding: "0 0.08em" });
    s.parentNode.insertBefore(w, s);
    w.appendChild(s);
    return w;
  });
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.2, 0.3);
      spans.forEach((s, i) => {
        const k = ease.out(prog(t, i * 0.07, i * 0.07 + 0.4));
        const o = ease.in(prog(t, dur - 0.3 + i * 0.03, dur - 0.05 + i * 0.03));
        setT(s, { y: (1 - k) * 110 + o * -110 });
        s.style.textShadow = "none";
      });
      b.node.style.textShadow = "none";
      void e;
    },
  };
});

// ---- 6. word with a drawn underline
defineTemplate({
  id: "underline-draw", name: "Drawn underline", tl: "Guhit sa ilalim", category: "text", moods: ["serious", "hype", "money", "tech"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 840, h: 200 }, duration: 2, words: true, maxChars: 44, pad: 40,
  defaults: { font: "black", accent: "#ffd23f" }, sample: { text: "This is the *secret*" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 120 });
  const spans = wordSpans(b.node, p.text);
  const em = emphasis(spans);
  const bars = em.map((s) => {
    s.style.position = "relative";
    return mk("span", {
      position: "absolute", left: "0", bottom: "-0.08em", height: "0.12em", width: "100%", background: p.accent,
      borderRadius: "0.06em", transformOrigin: "0 50%", transform: "scaleX(0)",
    }, null, s);
  });
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h: h + 16,
    update(t, dur) {
      const e = envelope(t, dur, 0.25, 0.25);
      spans.forEach((s, i) => { const k = ease.out(prog(t, i * 0.08, i * 0.08 + 0.3)); s.style.opacity = String(k * (1 - e.o)); setT(s, { y: (1 - k) * 16 }); });
      bars.forEach((bar, i) => { bar.style.transform = `scaleX(${ease.inOut(prog(t, 0.35 + i * 0.1, 0.8 + i * 0.1))})`; });
    },
  };
});

// ---- 7. highlighter box behind the key word
defineTemplate({
  id: "highlight-box", name: "Highlight box", tl: "Naka-highlight na kahon", category: "text", moods: ["hype", "serious", "tech", "money", "news"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 840, h: 220 }, duration: 2, words: true, maxChars: 44, bg: true,
  defaults: { font: "black", accent: "#ffd23f", color: "#ffffff" }, sample: { text: "Save more with *this trick*" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 110 });
  const spans = wordSpans(b.node, p.text);
  const em = emphasis(spans);
  const boxes = em.map((s) => {
    s.style.position = "relative";
    s.style.color = readableOn(p.accent);
    s.style.textShadow = "none";
    s.style.padding = "0 0.18em";
    s.style.zIndex = "1";
    return mk("span", {
      position: "absolute", inset: "0.04em 0", background: p.accent, borderRadius: "0.14em", zIndex: "-1",
      transformOrigin: "0 50%", transform: "scaleX(0)",
    }, null, s);
  });
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.2, 0.25);
      spans.forEach((s, i) => { const k = ease.out(prog(t, i * 0.07, i * 0.07 + 0.3)); s.style.opacity = String(k * (1 - e.o)); });
      boxes.forEach((bx, i) => { bx.style.transform = `scaleX(${ease.out(prog(t, 0.3 + i * 0.1, 0.6 + i * 0.1))})`; });
    },
  };
});

// ---- 8. stamp slam
defineTemplate({
  id: "stamp", name: "Stamp", tl: "Tatak", category: "text", moods: ["urgent", "warning", "hype", "serious"],
  zone: "center", anchor: { x: 0.5, y: 0.45 }, box: { w: 700, h: 200 }, duration: 1.8, maxChars: 24, bg: false, pad: 70,
  defaults: { font: "impact", case: "upper", color: "#ff3b3b" }, sample: { text: "Approved" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", {
    display: "inline-block", border: `12px solid ${p.color}`, borderRadius: "18px", padding: "14px 36px", color: p.color,
    transformOrigin: "50% 50%", textAlign: "center", boxShadow: `inset 0 0 0 4px ${rgba(p.color, 0.35)}`,
  }, null, c.root);
  const node = mk("div", { lineHeight: "1.05", letterSpacing: "0.06em", color: p.color }, plainText(p.text), wrap);
  c.fit(node, { maxW: 600, maxH: 150, max: 130, lines: 1 });
  const { w, h } = size(wrap);
  const rnd = rng(11);
  const jit = [rnd(), rnd(), rnd(), rnd()];
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.18, 0.3);
      const slam = ease.out(prog(t, 0, 0.18));
      const shake = Math.max(0, 1 - prog(t, 0.18, 0.5)) * (t > 0.18 ? 1 : 0) * p.intensity * 10;
      wrap.style.opacity = String(c01(slam * 3) * (1 - e.o));
      setT(wrap, { s: lerp(2.6, 1, slam), r: -7, x: Math.sin(t * 90 + jit[0]) * shake, y: Math.cos(t * 80 + jit[1]) * shake });
    },
  };
});

// ---- 9. typewriter
defineTemplate({
  id: "typewriter", name: "Typewriter", tl: "Tinatype", category: "text", moods: ["tech", "serious", "calm", "news"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 820, h: 200 }, duration: 2.6, maxChars: 60,
  defaults: { font: "mono", accent: "#6dff9e", color: "#e8fff0" }, sample: { text: "loading your results..." },
}, (c) => {
  const { p } = c;
  const text = plainText(p.text);
  const b = block(c, { maxW: 820, maxH: 300, max: 80, css: { textAlign: "left", fontWeight: "700", textShadow: shadow(0.8) } });
  const ghost = mk("span", { visibility: "hidden" }, text, b.node); // reserves the final size
  const live = mk("span", { position: "absolute", left: "0", top: "0", right: "0", color: p.color }, null, b.node);
  const typed = mk("span", {}, null, live);
  const caret = mk("span", { display: "inline-block", width: "0.55em", height: "1em", background: p.accent, verticalAlign: "-0.12em", marginLeft: "0.05em" }, null, live);
  b.fit();
  const chars = [...text];
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.1, 0.3);
      const n = Math.floor(chars.length * c01((t - 0.15) / Math.max(0.4, dur * 0.55)));
      typed.textContent = chars.slice(0, n).join("");
      caret.style.opacity = String((Math.floor(t * 3) % 2 === 0 || n < chars.length ? 1 : 0) * (1 - e.o));
      live.style.opacity = String(1 - e.o);
      void ghost;
    },
  };
});

// ---- 10. glitch
defineTemplate({
  id: "glitch-text", name: "Glitch", tl: "Glitch", category: "text", moods: ["tech", "urgent", "hype", "warning"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 840, h: 200 }, duration: 1.8, maxChars: 32,
  defaults: { font: "display", case: "upper", accent: "#00e5ff", bg: "#ff2e63" }, sample: { text: "System error" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 130, css: { textShadow: "none" } });
  b.node.textContent = plainText(p.text);
  b.fit();
  const { w, h } = size(b.node);
  const clone = (color) => {
    const n = b.node.cloneNode(true);
    Object.assign(n.style, { position: "absolute", left: "0", top: "0", color, mixBlendMode: "screen" });
    c.root.appendChild(n);
    return n;
  };
  const cyan = clone(p.accent), pink = clone(p.bg);
  b.node.style.position = "relative";
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.1, 0.25);
      const burst = (Math.sin(t * 37) + Math.sin(t * 23.3) > 0.9 ? 1 : 0) + (t < 0.35 ? 1 : 0);
      const off = (burst ? 10 + 14 * p.intensity : 2 + 2 * p.intensity) * (1 - e.o);
      setT(cyan, { x: -off, y: burst ? off * 0.3 : 0 });
      setT(pink, { x: off, y: burst ? -off * 0.3 : 0 });
      b.node.style.clipPath = burst ? `inset(${Math.floor((Math.sin(t * 91) * 0.5 + 0.5) * 40)}% 0 ${Math.floor((Math.cos(t * 53) * 0.5 + 0.5) * 30)}% 0)` : "none";
      for (const n of [b.node, cyan, pink]) n.style.opacity = String(c01(e.i * 4) * (1 - e.o));
    },
  };
});

// ---- 11. outline that fills
defineTemplate({
  id: "outline-fill", name: "Outline fill", tl: "Balangkas na pinupunan", category: "text", moods: ["hype", "luxury", "tech", "playful"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 840, h: 220 }, duration: 2, maxChars: 30,
  defaults: { font: "condensed", case: "upper", accent: "#ffffff" }, sample: { text: "No limits" },
}, (c) => {
  const { p } = c;
  const mkLayer = (extra) => {
    const b = block(c, { max: 190, css: { letterSpacing: "0.03em", textShadow: "none", ...extra } });
    b.node.textContent = plainText(p.text);
    return b;
  };
  const outline = mkLayer({ color: "transparent", WebkitTextStroke: `3px ${p.accent}` });
  outline.fit();
  const fill = mkLayer({ color: p.color, position: "absolute", left: "0", top: "0" });
  fill.node.style.fontSize = outline.node.style.fontSize;
  fill.node.style.width = outline.node.style.width;
  const { w, h } = size(outline.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.3, 0.3);
      const f = ease.inOut(prog(t, 0.25, 0.9));
      outline.node.style.opacity = String(ease.out(e.i) * (1 - e.o));
      fill.node.style.opacity = String(1 - e.o);
      fill.node.style.clipPath = `inset(0 ${100 - f * 100}% 0 0)`;
      setT(outline.node, { s: lerp(0.9, 1, ease.out(e.i)) });
      setT(fill.node, { s: lerp(0.9, 1, ease.out(e.i)) });
    },
  };
});

// ---- 12. gradient with a shine sweep
defineTemplate({
  id: "gradient-shine", name: "Gradient shine", tl: "Gradient na kumikintab", category: "text", moods: ["luxury", "money", "hype", "tech"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 840, h: 200 }, duration: 2.2, maxChars: 36,
  defaults: { font: "black", color: "#fff3b0", accent: "#ff9d00" }, sample: { text: "Premium quality" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 120, css: { textShadow: "none", filter: "drop-shadow(0 4px 8px rgba(0,0,0,.5))" } });
  b.node.textContent = plainText(p.text);
  b.fit();
  b.node.style.backgroundClip = "text";
  b.node.style.webkitBackgroundClip = "text";
  b.node.style.color = "transparent";
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.3);
      const sweep = lerp(-40, 140, prog(t, 0.5, 1.3));
      b.node.style.backgroundImage = `linear-gradient(105deg,${p.accent} 0%,${p.color} ${sweep - 14}%,#ffffff ${sweep}%,${p.color} ${sweep + 14}%,${p.accent} 100%)`;
      b.node.style.opacity = String(ease.out(e.i) * (1 - e.o));
      setT(b.node, { s: lerp(0.94, 1, ease.out(e.i)) });
    },
  };
});

// ---- 13. letters rise one by one
defineTemplate({
  id: "split-reveal", name: "Letter reveal", tl: "Titik-titik na lumilitaw", category: "text", moods: ["calm", "luxury", "emotion", "tech"],
  zone: "any", anchor: { x: 0.5, y: 0.45 }, box: { w: 840, h: 200 }, duration: 2.2, maxChars: 28,
  defaults: { font: "display", accent: "#ff8fb1" }, sample: { text: "Believe it" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 130 });
  const letters = letterSpans(b.node, p.text);
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.1, 0.3);
      letters.forEach((l, i) => {
        const k = ease.out(prog(t, i * 0.035, i * 0.035 + 0.4));
        l.style.opacity = String(k * (1 - e.o));
        l.style.filter = `blur(${c.blur((1 - k) * 8)}px)`;
        l.style.color = k < 1 ? mix(p.color, p.accent, 1 - k) : p.color;
        setT(l, { y: (1 - k) * 60 });
      });
    },
  };
});

// ---- 14. elegant serif with fine lines
defineTemplate({
  id: "serif-elegant", name: "Elegant serif", tl: "Eleganteng serif", category: "text", moods: ["luxury", "calm", "emotion", "serious"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 800, h: 260 }, duration: 2.6, maxChars: 48,
  defaults: { font: "serif", accent: "#d8b56a", color: "#fff8ea" }, sample: { text: "Timeless *elegance*", text2: "the collection" },
}, (c) => {
  const { p } = c;
  const line = () => mk("div", { height: "2px", background: p.accent, margin: "0 auto", width: "0px" }, null, c.root);
  const top = line();
  const b = block(c, { maxW: 780, maxH: 240, max: 96, css: { margin: "20px 0", fontWeight: "700", textShadow: shadow(0.8) } });
  const spans = wordSpans(b.node, p.text);
  emphasis(spans).forEach((s) => { s.style.color = p.accent; s.style.fontStyle = "italic"; });
  b.fit();
  const sub = mk("div", { textAlign: "center", fontSize: "30px", letterSpacing: "0.3em", textTransform: "uppercase", color: p.accent, opacity: "0", fontFamily: fontCss("inter").fontFamily, fontWeight: "400", textShadow: shadow(0.8) }, p.text2, c.root);
  const bottom = line();
  bottom.style.marginTop = "18px";
  const { w, h } = size(c.root);
  return {
    w: Math.max(w, 780), h: Math.max(h, 220),
    update(t, dur) {
      const e = envelope(t, dur, 0.9, 0.5);
      const grow = ease.inOut(e.i) * (1 - e.o);
      top.style.width = bottom.style.width = `${Math.round(360 * grow)}px`;
      b.node.style.opacity = String(ease.out(prog(t, 0.2, 0.9)) * (1 - e.o));
      sub.style.opacity = String(ease.out(prog(t, 0.6, 1.2)) * (1 - e.o));
      setT(b.node, { y: (1 - ease.out(prog(t, 0.2, 0.9))) * 14 });
    },
  };
});

// ---- 15. handwriting
defineTemplate({
  id: "handwritten", name: "Handwritten", tl: "Sulat-kamay", category: "text", moods: ["emotion", "funny", "playful", "calm"],
  zone: "any", anchor: { x: 0.5, y: 0.5 }, box: { w: 800, h: 180 }, duration: 2.2, maxChars: 36,
  defaults: { font: "hand", accent: "#ff6b6b" }, sample: { text: "thank you!!" },
}, (c) => {
  const { p } = c;
  const b = block(c, { max: 150 });
  b.node.textContent = plainText(p.text);
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.9, 0.3);
      b.node.style.clipPath = `inset(-20% ${100 - ease.inOut(e.i) * 100}% -20% 0)`;
      b.node.style.opacity = String(1 - e.o);
      setT(b.node, { r: -3 });
    },
  };
});

// ---- 16. news banner
defineTemplate({
  id: "news-banner", name: "News banner", tl: "Balita banner", category: "text", moods: ["news", "serious", "urgent"],
  zone: "lower", anchor: { x: 0.5, y: 0.78 }, box: { w: 900, h: 170 }, duration: 3, maxChars: 60, bg: true,
  fields: ["text", "text2", "font", "color", "accent", "bg", "size", "intensity"], inputs: [{ key: "text", type: "text", required: true }, { key: "text2", type: "text", required: false }],
  defaults: { font: "heavy", accent: "#d90429", bg: "#101828", color: "#ffffff", text2: "BREAKING" }, sample: { text: "Local prices are going down", text2: "BREAKING" },
}, (c) => {
  const { p } = c;
  const wrap = mk("div", { width: "900px", position: "relative", overflow: "hidden", borderRadius: "10px", boxShadow: "0 10px 30px rgba(0,0,0,.45)" }, null, c.root);
  const tag = mk("div", { background: p.accent, color: readableOn(p.accent), padding: "8px 22px", display: "inline-block", fontSize: "30px", letterSpacing: "0.12em", fontWeight: "700", textTransform: "uppercase", whiteSpace: "nowrap" }, plainText(p.text2) || "NEWS", wrap);
  const body = mk("div", { background: p.bg, color: p.color, padding: "16px 24px", lineHeight: "1.1" }, plainText(p.text), wrap);
  c.fit(body, { maxW: 852, maxH: 110, max: 62 });
  const { w, h } = size(wrap);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.4, 0.35);
      wrap.style.clipPath = `inset(0 ${100 - ease.out(e.i) * 100}% 0 0 round 10px)`;
      setT(wrap, { x: (1 - ease.out(e.i)) * -80 + e.o * -60 });
      wrap.style.opacity = String(1 - e.o);
    },
  };
});

// ---- 17. meme caption
defineTemplate({
  id: "meme-caption", name: "Meme caption", tl: "Meme caption", category: "text", moods: ["funny", "playful", "hype"],
  zone: "upper", anchor: { x: 0.5, y: 0.14 }, box: { w: 880, h: 220 }, duration: 2, maxChars: 50,
  defaults: { font: "impact", case: "upper", color: "#ffffff" }, sample: { text: "When the wifi finally works" },
}, (c) => {
  const { p } = c;
  const b = block(c, { maxW: 880, maxH: 300, max: 110, css: { WebkitTextStroke: "8px #000", paintOrder: "stroke fill", textShadow: "0 5px 0 #000", letterSpacing: "0.01em" } });
  b.node.textContent = plainText(p.text);
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.15, 0.2);
      b.node.style.opacity = String(c01(e.i * 3) * (1 - e.o));
      setT(b.node, { s: lerp(1.5, 1, ease.out(e.i)) * (1 + 0.02 * Math.sin(t * 8) * p.intensity) });
    },
  };
});

// ---- 18. karaoke highlight
defineTemplate({
  id: "karaoke-line", name: "Karaoke line", tl: "Karaoke", category: "text", moods: ["playful", "hype", "emotion", "funny"],
  zone: "lower", anchor: { x: 0.5, y: 0.66 }, box: { w: 840, h: 200 }, duration: 2.6, words: true, maxChars: 56,
  defaults: { font: "heavy", accent: "#ffe14d", color: "#ffffff" }, sample: { text: "Sing it with me now" },
}, (c) => {
  const { p } = c;
  const dim = mix(p.color, "#8890a0", 0.55);
  const b = block(c, { max: 100, css: { color: dim } });
  const spans = wordSpans(b.node, p.text);
  b.fit();
  const { w, h } = size(b.node);
  return {
    w, h,
    update(t, dur) {
      const e = envelope(t, dur, 0.25, 0.3);
      const per = Math.max(0.15, (dur - 0.7) / spans.length);
      spans.forEach((s, i) => {
        const on = c01((t - 0.3 - i * per) / 0.12);
        s.style.color = mix(dim, p.accent, on);
        setT(s, { s: 1 + 0.16 * Math.sin(Math.PI * c01((t - 0.3 - i * per) / (per * 1.4))) * on });
      });
      b.node.style.opacity = String(ease.out(e.i) * (1 - e.o));
    },
  };
});
