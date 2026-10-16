// The preview player. Two modes:
//  - a finished video (or the original) plays as is;
//  - a Project plays live: the source video jumps over the cuts (at each clip's speed), and
//    captions, photos, B-roll, zoom, colour and the sound tracks are added on top. This is an
//    approximation of the export; "Exact frame" asks the engine for the real thing.
// The timeline editor drives it through a PlayerHandle (seek, play/pause) and onTime.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type CSSProperties } from "react";
import type { Clip, Media, Project, Word } from "../../shared/types";
import {
  CANVAS, audioClipsAt, captionAt, captionPlacement, clipGain, clipSourceTime, cropBox, displayText, duration, fxAt, fxStyle, gradeCss,
  gradeLookAt, overlaysAt, popOpacity, popScale, segmentAt, segments, sourceTime, zoomAt, type CaptionFrame,
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

function CaptionView({ frame, onClick }: { frame: CaptionFrame; onClick?: (id: string) => void }) {
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
    <div
      className={`caption${onClick ? " clickable" : ""}`}
      style={base}
      data-testid="caption"
      onClick={onClick ? () => onClick(frame.clip.id) : undefined}
      title={onClick ? "Click to edit this caption" : undefined}
    >
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

function overlayStyle(clip: Clip, t: number): CSSProperties {
  const local = t - clip.start;
  const pop = clip.animation === "pop";
  const scale = pop ? popScale(local, clip.duration) : 1;
  const opacity = (pop ? popOpacity(local, clip.duration) : 1) * (clip.opacity ?? 1);
  return {
    left: (clip.x ?? 540) - (clip.width ?? 0) / 2,
    top: (clip.y ?? 960) - (clip.height ?? 0) / 2,
    width: clip.width,
    height: clip.height,
    transform: `scale(${scale})`,
    opacity,
  };
}

function OverlayView({ clip, t, url }: { clip: Clip; t: number; url: string }) {
  return <img className="overlay-photo" src={url} alt="" data-testid="overlay" style={overlayStyle(clip, t)} />;
}

/** Keeps a media element at the clip's source time (and speed) while the playhead moves. */
function useSynced(ref: React.RefObject<HTMLMediaElement | null>, clip: Clip, t: number, playing: boolean, volume?: number) {
  const want = clipSourceTime(clip, t);
  const speed = clip.speed ?? 1;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (el.playbackRate !== speed) el.playbackRate = speed;
    if (Math.abs(el.currentTime - want) > (playing ? 0.25 : 0.02)) el.currentTime = want;
    if (volume !== undefined) el.volume = Math.max(0, Math.min(1, volume));
    if (playing && el.paused) el.play().catch(() => {});
    if (!playing && !el.paused) el.pause();
  }, [ref, want, playing, speed, volume]);
}

/** A video clip on an overlay track (e.g. an AI video clip): muted, kept in step with the playhead. */
function OverlayVideoView({ clip, t, url, playing }: { clip: Clip; t: number; url: string; playing: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  useSynced(ref, clip, t, playing);
  return <video ref={ref} className="overlay-photo" src={url} muted playsInline preload="auto" data-testid="overlay" style={overlayStyle(clip, t)} />;
}

/** A clip on a sound track (music, voice-over, effects). */
function AudioClipView({ clip, t, url, playing, volume }: { clip: Clip; t: number; url: string; playing: boolean; volume: number }) {
  const ref = useRef<HTMLAudioElement>(null);
  useSynced(ref, clip, t, playing, volume * clipGain(clip, t));
  return <audio ref={ref} src={url} preload="auto" data-testid="audio-clip" data-clip={clip.id} />;
}

/** CSS that places the main picture like the engine's fill/reframe (or "blur": fit inside). */
function pictureStyle(clip: Clip | null | undefined, m: Media | undefined): { className?: string; style: CSSProperties } {
  if (!clip || clip.fit === "blur") return { className: "contain", style: {} };
  if (!m?.width || !m?.height) return { style: {} }; // unknown size: plain "cover"
  const box = cropBox(m.width, m.height, clip.crop);
  return { className: "framed", style: { left: box.left, top: box.top, width: box.width, height: box.height } };
}

export interface PlayerHandle {
  seek(t: number): void;
  toggle(): void;
  pause(): void;
  isPlaying(): boolean;
  time(): number;
}

interface PlayerProps {
  project: Project | null;
  /** A finished or original video to play as is (used when there is no project). */
  videoPath: string | null;
  mediaUrl: (path: string) => string;
  onExactFrame?: (seconds: number) => void;
  emptyText?: string;
  /** Called as the playhead moves (every frame while playing). */
  onTime?: (t: number) => void;
  /** Keep the playhead when the project changes (the editor), instead of going back to 0. */
  keepTime?: boolean;
  /** Hide the player's own transport bar (the editor has its own). */
  compact?: boolean;
  onPlaying?: (playing: boolean) => void;
  /** Clicking a caption on the picture (the editor selects it). */
  onCaptionClick?: (clipId: string) => void;
}

export const Player = forwardRef<PlayerHandle, PlayerProps>(function Player(
  { project, videoPath, mediaUrl, onExactFrame, emptyText, onTime, keepTime, compact, onPlaying, onCaptionClick },
  handle,
) {
  const [wrapRef, size] = useStageSize();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [time, setTimeState] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [plainDuration, setPlainDuration] = useState(0);
  const timeRef = useRef(0);
  const segIndex = useRef(0);
  const onTimeRef = useRef(onTime);
  onTimeRef.current = onTime;
  const onPlayingRef = useRef(onPlaying);
  onPlayingRef.current = onPlaying;
  useEffect(() => onPlayingRef.current?.(playing), [playing]);

  const setTime = useCallback((t: number) => {
    timeRef.current = t;
    setTimeState(t);
    onTimeRef.current?.(t);
  }, []);

  const segs = useMemo(() => (project ? segments(project) : []), [project]);
  const media = useMemo(() => new Map((project?.media ?? []).map((m) => [m.id, m])), [project]);
  const mainMuted = Boolean(project?.tracks.find((t) => t.kind === "video")?.muted);
  const total = project ? duration(project) : plainDuration;
  const fps = project?.settings.fps ?? 30;

  /** Show the timeline at time t: pick the segment and point the video at the right spot. */
  const seekTimeline = useCallback(
    (t: number) => {
      const video = videoRef.current;
      const clamped = Math.max(0, Math.min(t, Math.max(0, total - 1e-3)));
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
        video.playbackRate = seg.clip.speed ?? 1;
        video.volume = mainMuted ? 0 : Math.max(0, Math.min(1, volume * clipGain(seg.clip, clamped)));
      }
    },
    [project, segs, media, mediaUrl, total, volume, mainMuted, setTime],
  );

  useImperativeHandle(
    handle,
    () => ({
      seek: (t: number) => {
        setPlaying(false);
        seekTimeline(t);
      },
      toggle: () => setPlaying((p) => !p),
      pause: () => setPlaying(false),
      isPlaying: () => playing,
      time: () => timeRef.current,
    }),
    [seekTimeline, playing],
  );

  // New project or video: start from the beginning (the editor keeps its place instead).
  useEffect(() => {
    if (keepTime) {
      seekTimeline(timeRef.current);
      return;
    }
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
          setTime(video.currentTime);
          if (video.ended) setPlaying(false);
        }
      } else {
        const seg = segs[segIndex.current];
        let t = timeRef.current;
        if (seg?.clip?.type === "video" && video) {
          if (video.paused) video.play().catch(() => {});
          t = seg.start + (video.currentTime - (seg.clip.in ?? 0)) / (seg.clip.speed ?? 1);
          video.volume = mainMuted ? 0 : Math.max(0, Math.min(1, volume * clipGain(seg.clip, t)));
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
        setTime(t);
      }
      raf = requestAnimationFrame(tick);
    };
    if (!project) video?.play().catch(() => setPlaying(false));
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, project, segs, seekTimeline, fps, total, volume, mainMuted, setTime]);

  useEffect(() => {
    if (videoRef.current && !project) videoRef.current.volume = volume;
  }, [volume, project]);

  const step = (frames: number) => {
    setPlaying(false);
    seekTimeline(Math.floor(timeRef.current * fps + 1e-6) / fps + frames / fps);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (compact) return; // the editor handles its own keys
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
  const look = project ? gradeLookAt(project, time) : { grade: "none", intensity: 1 };
  const fx = project ? fxStyle(fxAt(project, time), CANVAS.width, CANVAS.height) : { transform: "", filter: "", overlay: null };
  const gradeFilter = gradeCss(look.grade, look.intensity);
  const grade = [gradeFilter === "none" ? "" : gradeFilter, fx.filter].filter(Boolean).join(" ") || "none";
  const caption = project ? captionAt(project, time) : null;
  const overlays = project ? overlaysAt(project, time) : [];
  const sounds = project ? audioClipsAt(project, time) : [];
  const hasSomething = Boolean(project || videoPath);
  const videoFrame = project ? pictureStyle(seg?.clip, media.get(seg?.clip?.media ?? "")) : { className: "contain", style: {} };
  const stillFrame = still ? pictureStyle(seg?.clip, still) : null;

  return (
    <div className="center" onKeyDown={onKey}>
      <div className="stage-wrap" ref={wrapRef}>
        {hasSomething ? (
          <div className="stage" style={{ width: size.width, height: size.height }} data-testid="stage">
            <div className="canvas" style={{ transform: `scale(${scale})` }}>
              <div
                className="picture"
                style={{
                  transform: [zoom.amount > 1 ? `scale(${zoom.amount})` : "", fx.transform].filter(Boolean).join(" ") || undefined,
                  transformOrigin: `50% ${zoom.anchorY * 100}%`,
                  filter: grade,
                }}
                data-testid="picture"
              >
                <video
                  ref={videoRef}
                  src={!project && videoPath ? mediaUrl(videoPath) : undefined}
                  className={videoFrame.className}
                  style={{ ...videoFrame.style, visibility: showVideo ? "visible" : "hidden" }}
                  data-testid="main-video"
                  onLoadedMetadata={(e) => !project && setPlainDuration(e.currentTarget.duration || 0)}
                  playsInline
                  preload="auto"
                />
                {still && stillFrame && <img className={`still ${stillFrame.className ?? ""}`} src={mediaUrl(still.path)} alt="" style={stillFrame.style} />}
                {fx.overlay && <div className="fx-layer" style={{ background: fx.overlay.color, opacity: fx.overlay.opacity }} data-testid="fx-layer" />}
              </div>
              {overlays.map((clip) => {
                const m = media.get(clip.media ?? "");
                if (m?.kind === "image") return <OverlayView key={clip.id} clip={clip} t={time} url={mediaUrl(m.path)} />;
                if (m?.kind === "video" && clip.type === "video") return <OverlayVideoView key={clip.id} clip={clip} t={time} url={mediaUrl(m.path)} playing={playing} />;
                return null;
              })}
              {caption && <CaptionView frame={caption} onClick={onCaptionClick} />}
            </div>
            {sounds.map(({ clip, muted }) => {
              const m = media.get(clip.media ?? "");
              return m ? <AudioClipView key={clip.id} clip={clip} t={time} url={mediaUrl(m.path)} playing={playing} volume={muted ? 0 : volume} /> : null;
            })}
          </div>
        ) : (
          <div className="empty-stage">{emptyText ?? "Add a video to start."}</div>
        )}
      </div>
      {!compact && (
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
      )}
    </div>
  );
});
