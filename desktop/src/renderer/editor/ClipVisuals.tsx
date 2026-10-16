// What a clip shows on the timeline: a filmstrip of small pictures and/or its sound waveform.
import { memo, useEffect, useRef } from "react";
import type { Peaks, Thumbs } from "../../shared/api";

/** The highest peak for each pixel column of a clip that plays source [from, to). */
export function peakColumns(peaks: Peaks, from: number, to: number, columns: number): number[] {
  const out: number[] = [];
  if (!peaks.peaks.length || columns <= 0 || to <= from) return out;
  const per = peaks.per_second;
  for (let x = 0; x < columns; x++) {
    const a = Math.floor((from + ((to - from) * x) / columns) * per);
    const b = Math.max(a + 1, Math.floor((from + ((to - from) * (x + 1)) / columns) * per));
    let m = 0;
    for (let i = Math.max(0, a); i < Math.min(b, peaks.peaks.length); i++) m = Math.max(m, peaks.peaks[i]);
    out.push(m / 255);
  }
  return out;
}

const MAX_CANVAS = 4096; // wider clips are drawn at this size and stretched

export const Waveform = memo(function Waveform({ peaks, from, to, width, height }: { peaks: Peaks; from: number; to: number; width: number; height: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.min(MAX_CANVAS, Math.round(width * ratio)));
    const h = Math.max(1, Math.round(height * ratio));
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = getComputedStyle(canvas).color || "#fff";
    const cols = peakColumns(peaks, from, to, w);
    cols.forEach((v, x) => {
      const bar = Math.max(1, v * h);
      ctx.fillRect(x, (h - bar) / 2, 1, bar);
    });
  }, [peaks, from, to, width, height]);
  return <canvas ref={ref} className="waveform" style={{ width, height }} data-testid="waveform" aria-hidden="true" />;
});

/** Small pictures across a video clip, each showing the source at that point. */
export const Filmstrip = memo(function Filmstrip({
  thumbs, from, to, width, height, url,
}: { thumbs: Thumbs; from: number; to: number; width: number; height: number; url: (p: string) => string }) {
  if (!thumbs.files.length || width <= 0) return null;
  const tile = Math.max(16, Math.round((height * 9) / 16));
  const count = Math.min(400, Math.ceil(width / tile));
  const tiles = [];
  for (let i = 0; i < count; i++) {
    const t = from + ((to - from) * (i + 0.5) * tile) / width;
    const index = thumbs.every > 0 ? Math.min(thumbs.files.length - 1, Math.max(0, Math.floor(t / thumbs.every))) : 0;
    tiles.push(<img key={i} src={url(thumbs.files[index])} alt="" draggable={false} style={{ width: tile, height }} />);
  }
  return (
    <div className="filmstrip" aria-hidden="true" data-testid="filmstrip">
      {tiles}
    </div>
  );
});
