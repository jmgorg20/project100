// Draws tracked effects (glow, sparks, aura, energy rings) over the preview picture. This is
// a lighter, browser-drawn approximation of what the engine draws for the export: the position
// and fading follow the same rules; the look is similar, not pixel-identical ("Exact frame"
// shows the real thing).
import { useEffect, useRef } from "react";
import type { Project } from "../../shared/types";
import { CANVAS } from "../lib/timeline";
import { trackfxAt, type PreviewFx } from "../lib/trackfxPreview";

const DEFAULT_COLORS: Record<string, string> = { glow: "#ffe08a", spark: "#ffb347", aura: "#58c8ff", energy: "#7aa8ff", clip: "#ffffff" };

function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

const rgba = (c: [number, number, number], a: number) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;

function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const hashId = (s: string) => [...s].reduce((h, ch) => (Math.imul(h, 31) + ch.charCodeAt(0)) >>> 0, 7);
const smoothstep = (x: number) => {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
};

function blob(ctx: CanvasRenderingContext2D, x: number, y: number, sigma: number, color: [number, number, number], amount: number) {
  if (amount <= 0.002 || sigma < 1) return;
  const r = sigma * 3;
  const g = ctx.createRadialGradient(x, y, 0, x, y, r);
  for (const [stop, k] of [[0, 1], [0.25, 0.78], [0.5, 0.37], [0.75, 0.11], [1, 0]] as const) g.addColorStop(stop, rgba(color, amount * k));
  ctx.fillStyle = g;
  ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
}

/** Draw one effect for its current frame. */
export function drawFx(ctx: CanvasRenderingContext2D, fx: PreviewFx, fps: number): void {
  const { clip, k, n, paths } = fx;
  const effect = clip.effect as string;
  const intensity = clip.intensity ?? 0.8;
  const size = clip.size ?? 1;
  const color = rgb(clip.color ?? DEFAULT_COLORS[effect] ?? "#ffffff");
  const fi = clip.fade_in ?? 0.15;
  const fo = clip.fade_out ?? 0.2;
  let env = 1;
  if (fi > 0) env = Math.min(env, (k + 0.5) / (fi * fps));
  if (fo > 0) env = Math.min(env, (n - k - 0.5) / (fo * fps));
  env = smoothstep(env);
  const t = clip.start + k / fps;
  const seed = hashId(clip.id);
  ctx.globalCompositeOperation = "lighter";
  for (const path of paths) {
    const p = path[k];
    if (!p) continue;
    const a = p.alpha * env * intensity;
    if (a <= 0.002) continue;
    if (effect === "glow") {
      const flicker = 1 + 0.07 * Math.sin(2 * Math.PI * 7 * t + (seed % 7)) + 0.04 * Math.sin(2 * Math.PI * 13 * t);
      const r = 46 * size * (0.7 + 0.5 * intensity) * flicker;
      const hot: [number, number, number] = color.map((c) => c * 0.55 + 255 * 0.45) as [number, number, number];
      blob(ctx, p.x, p.y, r * 2.6, color, 0.42 * a);
      blob(ctx, p.x, p.y, r * 1.2, color, 0.8 * a);
      blob(ctx, p.x, p.y, r * 0.45, hot, a);
    } else if (effect === "energy") {
      const r = 40 * size;
      blob(ctx, p.x, p.y, r * 1.4, color, 0.55 * a);
      blob(ctx, p.x, p.y, r * 0.5, color.map((c) => c * 0.5 + 127) as [number, number, number], 0.95 * a);
      for (let i = 0; i < 3; i++) {
        const phase = (t / 0.9 + i / 3) % 1;
        ctx.strokeStyle = rgba(color, 0.85 * a * Math.pow(1 - phase, 1.5));
        ctx.lineWidth = Math.max(2, r * 0.18);
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * (0.6 + 3.2 * phase), 0, Math.PI * 2);
        ctx.stroke();
      }
    } else if (effect === "aura") {
      const rx = Math.max(40, 0.58 * (p.size || 300) * size);
      const ry = rx * (clip.point === "body" ? 1.45 : 1.2);
      ctx.save();
      ctx.shadowColor = rgba(color, a);
      ctx.shadowBlur = rx * 0.3;
      ctx.strokeStyle = rgba(color, 0.9 * a);
      ctx.lineWidth = rx * 0.22;
      ctx.beginPath();
      ctx.ellipse(p.x, p.y, rx, ry, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
      const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, Math.max(rx, ry));
      g.addColorStop(0, rgba(color, 0.1 * a));
      g.addColorStop(1, rgba(color, 0));
      ctx.fillStyle = g;
      ctx.fillRect(p.x - rx * 1.5, p.y - ry * 1.5, rx * 3, ry * 3);
    } else if (effect === "spark") {
      const life = 0.55;
      const lifeFrames = Math.floor(life * fps);
      const perSecond = 70 + 170 * intensity;
      for (let e = Math.max(0, k - lifeFrames); e <= k; e++) {
        const q = path[e];
        if (!q || q.alpha * env <= 0.01) continue;
        const rng = mulberry(seed * 1000003 + e * 31);
        const want = (perSecond * q.alpha * env) / fps;
        const count = Math.floor(want) + (rng() < want - Math.floor(want) ? 1 : 0);
        for (let j = 0; j < count; j++) {
          const angle = rng() * Math.PI * 2;
          const speed = (160 + rng() * 360) * size;
          const age = (k - e) / fps;
          const lf = (0.6 + rng() * 0.4) * life;
          if (age >= lf) continue;
          const fade = Math.pow(1 - age / lf, 1.6);
          blob(ctx, q.x + Math.cos(angle) * speed * age, q.y + Math.sin(angle) * speed * age - 40 * age, (1.2 + rng() * 1.4) * 2 * Math.max(0.6, size), color, Math.min(1, 1.15 * q.alpha * env * fade));
        }
      }
    } else if (effect === "clip") {
      // Your own clip is drawn by the engine; here, a ring with its place and size.
      ctx.setLineDash([10, 8]);
      ctx.strokeStyle = rgba(color, 0.9 * a);
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 0.35 * CANVAS.width * size * 0.5, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
  ctx.globalCompositeOperation = "source-over";
}

export function TrackFxLayer({ project, time }: { project: Project; time: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const items = trackfxAt(project, time);
  const fps = project.settings.fps;
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(0.5, 0, 0, 0.5, 0, 0);
    for (const fx of items) drawFx(ctx, fx, fps);
    // items is rebuilt each render; the inputs that change it are listed here
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, time]);
  if (!items.length) return null;
  return (
    <canvas
      ref={ref}
      className="trackfx-layer"
      width={CANVAS.width / 2}
      height={CANVAS.height / 2}
      data-testid="trackfx-layer"
      data-effects={items.map((i) => i.clip.effect).join(",")}
      aria-hidden="true"
    />
  );
}
