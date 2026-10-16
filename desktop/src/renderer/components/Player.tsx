// The preview player. Two modes:
//  - a finished video (or the original) plays as is;
//  - a Project plays live: the source video jumps over the cuts, and captions, photos,
//    zoom and colour are drawn on top (an approximation; "Exact frame" asks the engine).
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { Clip, Project, Word } from "../../shared/types";
import {
  CANVAS, GRADE_CSS, captionAt, captionPlacement, displayText, duration, gradeAt, overlaysAt, popOpacity, popScale,
  segmentAt, segments, sourceTime, zoomAt, type CaptionFrame,
} from "../lib/timeline";

// libass sizes text so that ascent + descent equals the style size; Inter's is 1.211 em.
const INTER_LINE = 1.211;
const WEIGHT: Record<string, number> = { regular: 400, bold: 700, heavy: 900 };

export function mmss(t: number): string {
  const s = Math.max(0, t);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, "0")}`;
}

function rgba(hex: string, alpha255 = 0): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${(1 - alpha255 / 255).toFixed(3)})`;
}

function useStageSize(): [React.RefObject<HTMLDivElement | null>, { width: number; height: number }] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 270, height: 480 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      const h = Math.max(160, Math.min(el.clientHeight - 16, ((el.clientWidth - 16) * CANVAS.height) / CANVAS.width));
      setSize({ width: (h * CANVAS.width) / CANVAS.height, height: h });
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

function CaptionView({ frame }: { frame: CaptionFrame }) {
  const { style, lines, active } = frame;
  const place = captionPlacement(style, lines.length);
  const fontSize = style.size / INTER_LINE;
  const base: CSSProperties = {
    top: place.top,
    left: place.x,
    transform: place.left ? undefined : "translateX(-50%)",
    textAlign: place.left ? "left" : "center",
    fontFamily: "Inter",
    fontWeight: WEIGHT[style.font] ?? 700,
    fontSize,
    lineHeight: `${style.size}px`,
    color: style.color,
    WebkitTextStroke: style.outline && !style.box ? `${style.outline * 2}px ${style.outline_color}` : undefined,
    textShadow: style.shadow ? `${style.shadow}px ${style.shadow}px 0 ${rgba(style.shadow_color, style.shadow_alpha)}` : undefined,
  };
  let index = 0;
  return (
    <div className="caption" style={base} data-testid="caption">
      {lines.map((line: Word[], row) => (
        <div key={row} style={style.box ? { background: style.box_color, padding: `0 ${style.box_padding}px`, display: "table", margin: "0 auto" } : undefined}>
          {line.map((word, i) => {
            const n = index++;
            const hidden = (style.mode === "typewriter" || style.mode === "pop") && n > active;
            let color = style.color;
            if (word.highlight && style.keyword_color) color = style.keyword_color;
            if (n === active && style.active_color) color = style.active_color;
            const wordStyle: CSSProperties = { color, visibility: hidden ? "hidden" : "visible" };
            if (n === active && style.active_scale !== 100) {
              wordStyle.display = "inline-block";
              wordStyle.transform = `scale(${style.active_scale / 100})`;
            }
            if (n === active && style.active_box) {
              Object.assign(wordStyle, { background: style.active_box, borderRadius: style.size * 0.18, padding: `0 ${style.box_padding}px`, WebkitTextStroke: "0" });
            }
            return (
              <span key={i}>
                {i > 0 ? " " : ""}
                <span style={wordStyle} data-active={n === active || undefined}>{displayText(word, style)}</span>
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function OverlayView({ clip, t, url }: { clip: Clip; t: number; url: string }) {
  const local = t - clip.start;
  const pop = clip.animation === "pop";
  const scale = pop ? popScale(local, clip.duration) : 1;
  const opacity = (pop ? popOpacity(local, clip.duration) : 1) * (clip.opacity ?? 1);
  return (
    <img
      className="overlay-photo"
      src={url}
      alt=""
      data-testid="overlay"
      style={{
        left: (clip.x ?? 540) - (clip.width ?? 0) / 2,
        top: (clip.y ?? 960) - (clip.height ?? 0) / 2,
        width: clip.width,
        height: clip.height,
        transform: `scale(${scale})`,
        opacity,
      }}
    />
  );
}

interface PlayerProps {
  project: Project | null;
  /** A finished or original video to play as is (used when there is no project). */
  videoPath: string | null;
  mediaUrl: (path: string) => string;
  onExactFrame?: (seconds: number) => void;
  emptyText?: string;
}

export function Player({ project, videoPath, mediaUrl, onExactFrame, emptyText }: PlayerProps) {
  const [wrapRef, size] = useStageSize();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [plainDuration, setPlainDuration] = useState(0);
  const timeRef = useRef(0);
  const segIndex = useRef(0);

  const segs = useMemo(() => (project ? segments(project) : []), [project]);
  const media = useMemo(() => new Map((project?.media ?? []).map((m) => [m.id, m])), [project]);
  const total = project ? duration(project) : plainDuration;
  const fps = project?.settings.fps ?? 30;

  /** Show the timeline at time t: pick the segment and point the video at the right spot. */
  const seekTimeline = useCallback(
    (t: number) => {
      const video = videoRef.current;
      const clamped = Math.max(0, Math.min(t, Math.max(0, total - 1e-3)));
      timeRef.current = clamped;
      setTime(clamped);
      if (!project) {
        if (video) video.currentTime = clamped;
        return;
      }
      const i = segmentAt(segs, clamped);
      segIndex.current = i;
      const seg = segs[i];
      if (video && seg?.clip?.type === "video" && seg.clip.media) {
        const url = mediaUrl(media.get(seg.clip.media)?.path ?? "");
        if (video.dataset.src !== url) {
          video.dataset.src = url;
          video.src = url;
        }
        video.currentTime = sourceTime(seg, clamped);
        video.volume = Math.min(1, volume * (seg.clip.volume ?? 1));
      }
    },
    [project, segs, media, mediaUrl, total, volume],
  );

  // New project or video: start from the beginning.
  useEffect(() => {
    setPlaying(false);
    seekTimeline(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, videoPath]);

  // The play loop.
  useEffect(() => {
    const video = videoRef.current;
    if (!playing) {
      video?.pause();
      return;
    }
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      if (!project) {
        if (video) {
          timeRef.current = video.currentTime;
          setTime(video.currentTime);
          if (video.ended) setPlaying(false);
        }
      } else {
        const seg = segs[segIndex.current];
        let t = timeRef.current;
        if (seg?.clip?.type === "video" && video) {
          if (video.paused) video.play().catch(() => {});
          t = seg.start + (video.currentTime - (seg.clip.in ?? 0));
        } else {
          video?.pause();
          t += dt;
        }
        if (seg && t >= seg.end - 0.5 / fps) {
          if (segIndex.current >= segs.length - 1) {
            setPlaying(false);
            t = total;
          } else {
            const next = segs[segIndex.current + 1];
            seekTimeline(next.start);
            t = next.start;
          }
        }
        timeRef.current = t;
        setTime(t);
      }
      raf = requestAnimationFrame(tick);
    };
    if (!project) video?.play().catch(() => setPlaying(false));
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, project, segs, seekTimeline, fps, total]);

  useEffect(() => {
    if (videoRef.current && !project) videoRef.current.volume = volume;
  }, [volume, project]);

  const step = (frames: number) => {
    setPlaying(false);
    seekTimeline(Math.floor(timeRef.current * fps + 1e-6) / fps + frames / fps);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement && e.target.type !== "range") return;
    if (e.key === " ") {
      e.preventDefault();
      setPlaying((p) => !p);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      step(e.shiftKey ? fps : 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      step(e.shiftKey ? -fps : -1);
    }
  };

  const scale = size.height / CANVAS.height;
  const seg = project ? segs[segmentAt(segs, time)] : null;
  const showVideo = !project || seg?.clip?.type === "video";
  const still = project && seg?.clip?.type === "image" ? media.get(seg.clip.media ?? "") : null;
  const zoom = project ? zoomAt(project, time) : { amount: 1, anchorY: 0.4 };
  const grade = project ? GRADE_CSS[gradeAt(project, time)] ?? "none" : "none";
  const caption = project ? captionAt(project, time) : null;
  const overlays = project ? overlaysAt(project, time) : [];
  const hasSomething = Boolean(project || videoPath);

  return (
    <div className="center" onKeyDown={onKey}>
      <div className="stage-wrap" ref={wrapRef}>
        {hasSomething ? (
          <div className="stage" style={{ width: size.width, height: size.height }} data-testid="stage">
            <div className="canvas" style={{ transform: `scale(${scale})` }}>
              <video
                ref={videoRef}
                src={!project && videoPath ? mediaUrl(videoPath) : undefined}
                className={!project || seg?.clip?.fit === "blur" ? "contain" : undefined}
                style={{
                  visibility: showVideo ? "visible" : "hidden",
                  transform: zoom.amount > 1 ? `scale(${zoom.amount})` : undefined,
                  transformOrigin: `50% ${zoom.anchorY * 100}%`,
                  filter: grade,
                }}
                onLoadedMetadata={(e) => !project && setPlainDuration(e.currentTarget.duration || 0)}
                playsInline
                preload="auto"
              />
              {still && <img className={`still${seg?.clip?.fit === "blur" ? " contain" : ""}`} src={mediaUrl(still.path)} alt="" style={{ filter: grade }} />}
              {overlays.map((clip) => {
                const m = media.get(clip.media ?? "");
                return m && m.kind === "image" ? <OverlayView key={clip.id} clip={clip} t={time} url={mediaUrl(m.path)} /> : null;
              })}
              {caption && <CaptionView frame={caption} />}
            </div>
          </div>
        ) : (
          <div className="empty-stage">{emptyText ?? "Add a video to start."}</div>
        )}
      </div>
      <div className="controls">
        <button className="btn small" onClick={() => setPlaying((p) => !p)} disabled={!hasSomething} aria-label={playing ? "Pause" : "Play"}>
          {playing ? "Pause" : "Play"}
        </button>
        <button className="btn small ghost" onClick={() => step(-1)} disabled={!hasSomething} aria-label="Previous frame">‹</button>
        <button className="btn small ghost" onClick={() => step(1)} disabled={!hasSomething} aria-label="Next frame">›</button>
        <input
          type="range"
          min={0}
          max={Math.max(total, 0.01)}
          step={1 / fps}
          value={Math.min(time, total)}
          onChange={(e) => {
            setPlaying(false);
            seekTimeline(Number(e.target.value));
          }}
          aria-label="Position"
          disabled={!hasSomething}
        />
        <span className="time">{mmss(time)} / {mmss(total)}</span>
        <input type="range" min={0} max={1} step={0.05} value={volume} onChange={(e) => setVolume(Number(e.target.value))} aria-label="Volume" className="volume" />
        {onExactFrame && (
          <button className="btn small" onClick={() => onExactFrame(timeRef.current)} title="Ask the editor engine for the real frame at this moment">
            Exact frame
          </button>
        )}
      </div>
    </div>
  );
}
