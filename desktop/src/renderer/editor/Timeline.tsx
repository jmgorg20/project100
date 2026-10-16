// The multi-track timeline: ruler, playhead, tracks (captions, effects, B-roll/photos, main
// video, sound) and clips you can select, move, trim and reorder, with snapping.
// While you drag, the change is shown as a draft; letting go makes it one undo step.
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Peaks, Thumbs } from "../../shared/api";
import {
  EditError, clipEnd, isMain, moveClip, moveMainClip, projectDuration, snap, snapMove, snapPoints, speedOf, trimClip,
} from "../../shared/edit";
import { FX_INFO } from "../../shared/effectsEdit";
import { trackfxLabel } from "../../shared/trackEdit";
import type { Clip, FxEffect, Project, Track } from "../../shared/types";
import { mmss } from "../components/Player";
import { Filmstrip, Waveform } from "./ClipVisuals";

export const HEADER_WIDTH = 150;
const SNAP_PX = 8;
const ROW_HEIGHT: Record<string, number> = { video: 64, overlay: 44, effect: 30, caption: 36, audio: 44 };

const TRACK_ICON: Record<string, string> = { video: "🎬", overlay: "🖼", effect: "✨", caption: "💬", audio: "🎵" };
const ROLE_ICON: Record<string, string> = { voiceover: "🎙", music: "🎵", sfx: "🔔", original: "🔊" };

/** Tracks top to bottom, like CapCut: captions, effects, overlays (top one first), video, sound. */
export function orderedTracks(p: Project): Track[] {
  const of = (kind: string) => p.tracks.filter((t) => t.kind === kind);
  return [...of("caption").reverse(), ...of("effect").reverse(), ...of("overlay").reverse(), ...of("video"), ...of("audio")];
}

function clipLabel(c: Clip, p: Project): string {
  if (c.label) return c.label;
  if (c.type === "caption") return (c.words ?? []).map((w) => w.text).join(" ");
  if (c.type === "zoom") return `Zoom ${Math.round((c.amount ?? 1) * 100)}%`;
  if (c.type === "grade") return `Colour: ${(c.grade ?? "").replace(/_/g, " ")}`;
  if (c.type === "trackfx") return trackfxLabel(c);
  if (c.type === "fx") return FX_INFO[c.effect as FxEffect]?.label ?? c.id;
  const m = p.media.find((x) => x.id === c.media);
  return m?.name ?? m?.path.split(/[\\/]/).pop() ?? c.id;
}

/** Nice ruler steps for the zoom level: about one labelled tick per 80 px. */
export function rulerStep(pps: number): number {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  return steps.find((s) => s * pps >= 80) ?? 600;
}

interface Drag {
  mode: "move" | "trim-start" | "trim-end";
  clip: Clip;
  track: Track;
  x0: number;
  y0: number;
  origin: Project;
  started: boolean;
  draft: Project | null;
}

export interface TimelineProps {
  project: Project;
  selection: string[];
  playhead: number;
  pps: number;
  snapping: boolean;
  peaks: Record<string, Peaks>;
  thumbs: Record<string, Thumbs>;
  url: (path: string) => string;
  onSelect: (ids: string[]) => void;
  onSeek: (t: number) => void;
  onDraft: (p: Project | null) => void;
  onCommit: (p: Project) => void;
  onError: (message: string) => void;
  onZoom: (pps: number, anchorTime?: number) => void;
  onDropMedia: (mediaId: string, at: number, trackId: string | undefined) => void;
  onTrackFlag: (trackId: string, flag: "muted" | "hidden" | "locked", value: boolean) => void;
}

export function Timeline(props: TimelineProps) {
  const { project, playhead, pps, snapping, onSeek, onZoom } = props;
  const scrollRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const seeking = useRef(false);
  const [snapLine, setSnapLine] = useState<number | null>(null);
  const [insertAt, setInsertAt] = useState<number | null>(null);
  const tracks = useMemo(() => orderedTracks(project), [project]);
  const total = projectDuration(project);
  const width = Math.max((total + 10) * pps, 800);

  const timeAt = useCallback(
    (clientX: number) => {
      const el = scrollRef.current;
      if (!el) return 0;
      const r = el.getBoundingClientRect();
      return Math.max(0, (clientX - r.left + el.scrollLeft) / pps);
    },
    [pps],
  );

  // Keep the playhead in view while playing.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const x = playhead * pps;
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - el.clientWidth / 3);
  }, [playhead, pps]);

  // Ctrl + wheel zooms around the pointer.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      onZoom(pps * (e.deltaY < 0 ? 1.25 : 0.8), timeAt(e.clientX));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [pps, onZoom, timeAt]);

  const startDrag = (e: React.PointerEvent, mode: Drag["mode"], clip: Clip, track: Track) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    drag.current = { mode, clip, track, x0: e.clientX, y0: e.clientY, origin: project, started: false, draft: null };
  };

  const trackUnder = (clientX: number, clientY: number): string | undefined => {
    for (const el of document.elementsFromPoint(clientX, clientY)) {
      const id = (el as HTMLElement).dataset?.trackRow;
      if (id) return id;
    }
    return undefined;
  };

  const onPointerMove = (e: PointerEvent) => {
    if (seeking.current) onSeek(timeAt(e.clientX));
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x0;
    if (!d.started && Math.abs(dx) < 3 && Math.abs(e.clientY - d.y0) < 3) return;
    d.started = true;
    const threshold = snapping ? SNAP_PX / pps : 0;
    const points = snapPoints(d.origin, playhead, [d.clip.id]);
    try {
      let next: Project;
      let line: number | null = null;
      if (d.mode === "move" && isMain(d.track)) {
        const t = timeAt(e.clientX);
        const others = [...d.track.clips].filter((c) => c.id !== d.clip.id).sort((a, b) => a.start - b.start);
        let index = others.findIndex((c) => t < c.start + c.duration / 2);
        if (index < 0) index = others.length;
        next = moveMainClip(d.origin, d.clip.id, index);
        const marker = index < others.length ? others[index].start : others.length ? clipEnd(others[others.length - 1]) : 0;
        setInsertAt(marker);
      } else if (d.mode === "move") {
        const raw = d.clip.start + dx / pps;
        const s = snapMove(raw, d.clip.duration, points, threshold);
        line = s.snapped;
        const over = trackUnder(e.clientX, e.clientY);
        const target = d.origin.tracks.find((t) => t.id === over);
        const targetId = target && target.kind === d.track.kind && !target.locked ? target.id : d.track.id;
        next = moveClip(d.origin, d.clip.id, s.start, targetId).project;
      } else {
        const edge = d.mode === "trim-start" ? "start" : "end";
        const raw = (edge === "start" ? d.clip.start : clipEnd(d.clip)) + dx / pps;
        const s = snap(raw, points, threshold);
        line = s.snapped;
        next = trimClip(d.origin, d.clip.id, edge, s.t);
      }
      d.draft = next;
      setSnapLine(line);
      props.onDraft(next);
    } catch (err) {
      if (!(err instanceof EditError)) throw err; // keep the last good draft
    }
  };

  const onPointerUp = (e: PointerEvent) => {
    seeking.current = false;
    const d = drag.current;
    drag.current = null;
    setSnapLine(null);
    setInsertAt(null);
    if (!d) return;
    if (!d.started) {
      const additive = e.shiftKey || e.ctrlKey || e.metaKey;
      const sel = props.selection;
      props.onSelect(additive ? (sel.includes(d.clip.id) ? sel.filter((x) => x !== d.clip.id) : [...sel, d.clip.id]) : [d.clip.id]);
      props.onDraft(null);
      return;
    }
    props.onDraft(null);
    if (d.draft) props.onCommit(d.draft);
  };

  // Window-level listeners: a drag keeps working when the pointer leaves the timeline or the
  // dragged clip moves to another row.
  const handlers = useRef({ move: onPointerMove, up: onPointerUp });
  handlers.current = { move: onPointerMove, up: onPointerUp };
  useEffect(() => {
    const move = (e: PointerEvent) => handlers.current.move(e);
    const up = (e: PointerEvent) => handlers.current.up(e);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
  }, []);

  // Ruler / empty space: click or drag to move the playhead.
  const onSeekDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    seeking.current = true;
    onSeek(timeAt(e.clientX));
    if (!(e.target as HTMLElement).closest(".ruler")) props.onSelect([]);
  };

  const step = rulerStep(pps);
  const ticks = [];
  for (let t = 0; t <= width / pps; t += step) {
    ticks.push(
      <div key={t} className="tick" style={{ left: t * pps }}>
        <span>{step < 1 ? t.toFixed(1) : mmss(t).replace(/\.0$/, "")}</span>
      </div>,
    );
  }

  return (
    <div className="timeline" data-testid="timeline">
      <div className="tl-headers">
        <div className="tl-corner">{mmss(playhead)}</div>
        {tracks.map((t) => (
          <TrackHeader key={t.id} track={t} onFlag={props.onTrackFlag} />
        ))}
      </div>
      <div className="tl-scroll" ref={scrollRef}>
        <div className="tl-content" style={{ width }}>
          <div className="ruler" onPointerDown={onSeekDown} data-testid="ruler">
            {ticks}
          </div>
          {tracks.map((t) => (
            <TrackRow
              key={t.id}
              track={t}
              {...props}
              onClipDown={startDrag}
              onEmptyDown={onSeekDown}
              timeAt={timeAt}
            />
          ))}
          <div className="playhead" style={{ left: playhead * pps }} data-testid="playhead" />
          {snapLine !== null && <div className="snap-line" style={{ left: snapLine * pps }} />}
          {insertAt !== null && <div className="insert-line" style={{ left: insertAt * pps }} data-testid="insert-line" />}
        </div>
      </div>
    </div>
  );
}

const TrackHeader = memo(function TrackHeader({ track, onFlag }: { track: Track; onFlag: TimelineProps["onTrackFlag"] }) {
  const icon = track.kind === "audio" ? ROLE_ICON[track.role ?? ""] ?? "🎵" : TRACK_ICON[track.kind];
  const sound = track.kind === "video" || track.kind === "audio";
  const picture = track.kind !== "audio";
  const name = track.name ?? track.id;
  return (
    <div className={`tl-header${track.locked ? " locked" : ""}`} style={{ height: ROW_HEIGHT[track.kind] }} data-testid={`track-header-${track.id}`}>
      <span className="tl-name" title={name}>
        <span aria-hidden="true">{icon}</span> {name}
      </span>
      <span className="tl-flags">
        {sound && (
          <button className={`flag${track.muted ? " on" : ""}`} aria-pressed={Boolean(track.muted)} aria-label={`Mute ${name}`} title="Mute / I-mute" onClick={() => onFlag(track.id, "muted", !track.muted)}>
            {track.muted ? "🔇" : "🔈"}
          </button>
        )}
        {picture && (
          <button className={`flag${track.hidden ? " on" : ""}`} aria-pressed={Boolean(track.hidden)} aria-label={`Hide ${name}`} title="Hide / Itago" onClick={() => onFlag(track.id, "hidden", !track.hidden)}>
            {track.hidden ? "🚫" : "👁"}
          </button>
        )}
        <button className={`flag${track.locked ? " on" : ""}`} aria-pressed={Boolean(track.locked)} aria-label={`Lock ${name}`} title="Lock / I-lock" onClick={() => onFlag(track.id, "locked", !track.locked)}>
          {track.locked ? "🔒" : "🔓"}
        </button>
      </span>
    </div>
  );
});

interface RowProps extends TimelineProps {
  track: Track;
  onClipDown: (e: React.PointerEvent, mode: Drag["mode"], clip: Clip, track: Track) => void;
  onEmptyDown: (e: React.PointerEvent) => void;
  timeAt: (clientX: number) => number;
}

function TrackRow({ track, project, selection, pps, peaks, thumbs, url, onClipDown, onEmptyDown, onDropMedia, timeAt }: RowProps) {
  const height = ROW_HEIGHT[track.kind];
  const [over, setOver] = useState(false);
  return (
    <div
      className={`tl-row kind-${track.kind}${track.locked ? " locked" : ""}${over ? " drop" : ""}`}
      style={{ height }}
      data-track-row={track.id}
      data-testid={`track-${track.id}`}
      onPointerDown={onEmptyDown}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("application/x-autoedit-media")) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        const id = e.dataTransfer.getData("application/x-autoedit-media");
        if (id) {
          e.preventDefault();
          onDropMedia(id, timeAt(e.clientX), track.id);
        }
      }}
    >
      {track.clips.map((c) => (
        <ClipView key={c.id} clip={c} track={track} project={project} selected={selection.includes(c.id)} pps={pps} height={height} peaks={peaks} thumbs={thumbs} url={url} onDown={onClipDown} />
      ))}
    </div>
  );
}

const ClipView = memo(function ClipView({
  clip, track, project, selected, pps, height, peaks, thumbs, url, onDown,
}: {
  clip: Clip;
  track: Track;
  project: Project;
  selected: boolean;
  pps: number;
  height: number;
  peaks: Record<string, Peaks>;
  thumbs: Record<string, Thumbs>;
  url: (p: string) => string;
  onDown: RowProps["onClipDown"];
}) {
  const w = Math.max(2, clip.duration * pps);
  const from = clip.in ?? 0;
  const to = clip.out ?? from + clip.duration;
  const pk = clip.media ? peaks[clip.media] : undefined;
  const th = clip.media ? thumbs[clip.media] : undefined;
  const label = clipLabel(clip, project);
  const showStrip = th && (track.kind === "video" || track.kind === "overlay");
  const showWave = pk && pk.peaks.length && (track.kind === "audio" || (track.kind === "video" && clip.type === "video"));
  const sp = speedOf(clip);
  return (
    <div
      className={`clip type-${clip.type}${selected ? " selected" : ""}`}
      style={{ left: clip.start * pps, width: w, height: height - 4 }}
      onPointerDown={(e) => !track.locked && onDown(e, "move", clip, track)}
      data-testid="clip"
      data-clip={clip.id}
      role="button"
      aria-pressed={selected}
      aria-label={`${label}, ${mmss(clip.start)} to ${mmss(clipEnd(clip))}`}
      title={`${label}\n${mmss(clip.start)} – ${mmss(clipEnd(clip))}${sp !== 1 ? ` · ${sp}x` : ""}`}
    >
      {showStrip && th && <Filmstrip thumbs={th} from={from} to={to} width={w} height={track.kind === "video" ? height - 22 : height - 4} url={url} />}
      {showWave && pk && <Waveform peaks={pk} from={from} to={to} width={w} height={track.kind === "video" ? 18 : height - 18} />}
      <span className="clip-label">
        {sp !== 1 && <span className="badge-speed">{sp}x</span>}
        {clip.broll?.ai_generated && <span className="badge-ai" title="Made with AI">AI</span>}
        {label}
      </span>
      {!track.locked && (
        <>
          <span className="handle start" onPointerDown={(e) => onDown(e, "trim-start", clip, track)} data-testid="trim-start" aria-hidden="true" />
          <span className="handle end" onPointerDown={(e) => onDown(e, "trim-end", clip, track)} data-testid="trim-end" aria-hidden="true" />
        </>
      )}
    </div>
  );
});
