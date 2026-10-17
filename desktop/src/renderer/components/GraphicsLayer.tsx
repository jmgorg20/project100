// Motion graphics on the preview: the same HTML templates the export draws, live in the page
// (quality "preview": lighter blur), so what you see is placed and timed like the export.
import { useEffect, useLayoutEffect, useRef } from "react";
import "../../../graphics/fonts.css";
import "../../../graphics/templates/index.js";
import { instantiate, type GraphicInstance } from "../../../graphics/index.js";
import { graphicsAt, wipeAt } from "../../shared/graphicsEdit";
import type { Clip, Media, Project } from "../../shared/types";
import { CANVAS, gradeCss } from "../lib/timeline";

function GraphicView({ clip, time, imageUrl, selected, onSelect }: { clip: Clip; time: number; imageUrl?: string; selected: boolean; onSelect?: (id: string) => void }) {
  const host = useRef<HTMLDivElement>(null);
  const inst = useRef<GraphicInstance | null>(null);
  const params = JSON.stringify({ ...(clip.params ?? {}), image: imageUrl ?? undefined });
  useLayoutEffect(() => {
    const el = host.current;
    if (!el) return;
    let made: GraphicInstance | null = null;
    try {
      made = instantiate(clip.template ?? "", JSON.parse(params), { duration: clip.duration, quality: "preview" });
      el.appendChild(made.tile);
      inst.current = made;
    } catch {
      inst.current = null;
    }
    return () => {
      made?.destroy();
      inst.current = null;
    };
  }, [clip.template, params, clip.duration]);
  useLayoutEffect(() => {
    const g = inst.current;
    const el = host.current;
    if (!g || !el) return;
    g.update(time - clip.start);
    const tw = g.w + 2 * g.pad;
    const th = g.h + 2 * g.pad;
    el.style.left = `${Math.round((clip.x ?? 0.5) * CANVAS.width - tw / 2)}px`;
    el.style.top = `${Math.round((clip.y ?? 0.5) * CANVAS.height - th / 2)}px`;
    el.style.width = `${tw}px`;
    el.style.height = `${th}px`;
  });
  return (
    <div
      ref={host}
      className={`graphic${selected ? " selected" : ""}`}
      data-testid={`graphic-${clip.id}`}
      data-template={clip.template}
      onClick={onSelect ? () => onSelect(clip.id) : undefined}
    />
  );
}

export function GraphicsLayer({ project, time, media, mediaUrl, selection, onSelect }: {
  project: Project;
  time: number;
  media: Map<string, Media>;
  mediaUrl: (p: string) => string;
  selection?: string[];
  onSelect?: (id: string) => void;
}) {
  const clips = graphicsAt(project, time);
  return (
    <div className="graphics-layer" data-testid="graphics-layer">
      {clips.map((c) => {
        const m = c.params?.image ? media.get(c.params.image) : undefined;
        return <GraphicView key={c.id} clip={c} time={time} imageUrl={m ? mediaUrl(m.path) : undefined} selected={Boolean(selection?.includes(c.id))} onSelect={onSelect} />;
      })}
    </div>
  );
}

/** The before/after wipe on the preview: the graded side through a backdrop filter, and the divider. */
export function WipeLayer({ project, time }: { project: Project; time: number }) {
  const w = wipeAt(project, time);
  useEffect(() => undefined, []);
  if (!w || w.pos <= 0.001) return null;
  const { clip, pos } = w;
  const dir = clip.direction ?? "right";
  const pct = `${(pos * 100).toFixed(2)}%`;
  const side: React.CSSProperties =
    dir === "right" ? { left: 0, top: 0, bottom: 0, width: pct } :
    dir === "left" ? { right: 0, top: 0, bottom: 0, width: pct } :
    dir === "down" ? { left: 0, right: 0, top: 0, height: pct } : { left: 0, right: 0, bottom: 0, height: pct };
  const line: React.CSSProperties =
    dir === "right" ? { left: pct, top: 0, bottom: 0, width: 5, marginLeft: -2.5 } :
    dir === "left" ? { right: pct, top: 0, bottom: 0, width: 5, marginRight: -2.5 } :
    dir === "down" ? { top: pct, left: 0, right: 0, height: 5, marginTop: -2.5 } : { bottom: pct, left: 0, right: 0, height: 5, marginBottom: -2.5 };
  const filter = gradeCss(clip.grade ?? "none", clip.intensity ?? 1);
  return (
    <div className="wipe-layer" data-testid="wipe-layer">
      <div className="wipe-side" style={{ ...side, backdropFilter: filter === "none" ? undefined : filter }} />
      {clip.divider !== false && <div className="wipe-line" style={line} />}
    </div>
  );
}
