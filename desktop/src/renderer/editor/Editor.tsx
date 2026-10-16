// The timeline editor (CapCut-like): big preview on top, multi-track timeline below, media on
// the left and the selected clip's settings on the right. Opens a .project.json (the AI's
// result is one), saves by itself, and exports with the FFmpeg engine.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { OpenedProject, Peaks, Thumbs } from "../../shared/api";
import {
  EditError, addMedia, clipEnd, deleteClips, findClip, insertMedia, mainTrack, projectDuration, setClipProps, setSpeed, setTrackFlag,
  splitAt, splitClip, type ClipPatch,
} from "../../shared/edit";
import { baseName, exportPathFor, resolveMediaPath } from "../../shared/paths";
import type { Project } from "../../shared/types";
import { createHistory, pushHistory, redoHistory, undoHistory, type History } from "../../shared/undo";
import { FrameDialog } from "../components/Dialogs";
import { Player, mmss, type PlayerHandle } from "../components/Player";
import { api, mediaUrl } from "../lib/api";
import { ExportDialog } from "./ExportDialog";
import { Inspector } from "./Inspector";
import { MediaBin } from "./MediaBin";
import { SHORTCUTS, actionFor, typingInto, type Action } from "./shortcuts";
import { Timeline } from "./Timeline";

const AUTOSAVE_MS = 700;
const MIN_PPS = 4;
const MAX_PPS = 600;

type SaveState = { state: "saved" | "saving" | "unsaved" | "error"; message?: string };

export function Editor({ path, onClose }: { path: string; onClose: () => void }) {
  const [opened, setOpened] = useState<OpenedProject | null>(null);
  const [history, setHistory] = useState<History<Project> | null>(null);
  const [draft, setDraft] = useState<Project | null>(null);
  const [selection, setSelection] = useState<string[]>([]);
  const [playhead, setPlayhead] = useState(0);
  const [pps, setPps] = useState(60);
  const [snapping, setSnapping] = useState(true);
  const [save, setSave] = useState<SaveState>({ state: "saved" });
  const [toast, setToast] = useState<string | null>(null);
  const [peaks, setPeaks] = useState<Record<string, Peaks>>({});
  const [thumbs, setThumbs] = useState<Record<string, Thumbs>>({});
  const [showExport, setShowExport] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [importing, setImporting] = useState(false);
  const [frame, setFrame] = useState<{ url?: string; error?: string } | null>(null);
  const [playing, setPlaying] = useState(false);
  const playerRef = useRef<PlayerHandle>(null);
  const requested = useRef(new Set<string>());
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedProject = useRef<Project | null>(null);

  const project = draft ?? history?.present ?? null;
  const fps = project?.settings.fps ?? 30;
  const url = useCallback((p: string) => mediaUrl(resolveMediaPath(path, p)), [path]);

  // ---- open
  useEffect(() => {
    let alive = true;
    api.openProject(path).then((o) => {
      if (!alive) return;
      setOpened(o);
      if (o.project) {
        setHistory(createHistory(o.project));
        savedProject.current = o.project;
        const total = projectDuration(o.project);
        setPps(Math.max(MIN_PPS, Math.min(120, 900 / Math.max(total, 1))));
      }
    });
    return () => {
      alive = false;
    };
  }, [path]);

  // ---- waveforms and filmstrips (made by the engine, cached)
  useEffect(() => {
    if (!project) return;
    for (const m of project.media) {
      if (requested.current.has(m.id)) continue;
      requested.current.add(m.id);
      const file = resolveMediaPath(path, m.path);
      if (m.kind === "audio" || (m.kind === "video" && m.has_audio !== false)) {
        api.peaks(file).then((r) => !("error" in r) && setPeaks((x) => ({ ...x, [m.id]: r })));
      }
      if (m.kind !== "audio") api.thumbs(file).then((r) => !("error" in r) && setThumbs((x) => ({ ...x, [m.id]: r })));
    }
  }, [project, path]);

  // ---- saving (by itself, shortly after each change)
  const saveNow = useCallback(async (): Promise<string | null> => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = null;
    const current = history?.present;
    if (!current || current === savedProject.current) return null;
    setSave({ state: "saving" });
    const r = await api.saveProject(path, current);
    if (r.ok) {
      savedProject.current = current;
      setSave({ state: "saved" });
      return null;
    }
    setSave({ state: "error", message: r.error });
    return r.error ?? "Could not save.";
  }, [history, path]);

  useEffect(() => {
    if (!history || history.present === savedProject.current) return;
    setSave({ state: "unsaved" });
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void saveNow(), AUTOSAVE_MS);
  }, [history, saveNow]);

  const close = async () => {
    const problem = await saveNow();
    if (problem && !window.confirm(`${problem}\n\nClose anyway? Your last changes are not saved.`)) return;
    onClose();
  };

  // ---- editing
  // The latest history, updated at once (several edits in one event chain correctly).
  const histRef = useRef<History<Project> | null>(null);
  histRef.current = history;
  const commit = useCallback((next: History<Project>) => {
    histRef.current = next;
    setHistory(next);
  }, []);
  const apply = useCallback(
    (fn: (p: Project) => Project, key?: string) => {
      const h = histRef.current;
      if (!h) return;
      try {
        commit(pushHistory(h, fn(h.present), key));
      } catch (err) {
        if (!(err instanceof EditError)) throw err;
        setToast(err.message);
      }
    },
    [commit],
  );

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  // Forget a selection whose clips are gone (after undo, delete...).
  useEffect(() => {
    if (project) setSelection((sel) => (sel.every((id) => findClip(project, id)) ? sel : sel.filter((id) => findClip(project, id))));
  }, [project]);

  const seek = useCallback((t: number) => {
    playerRef.current?.seek(t);
    setPlayhead(Math.max(0, t));
  }, []);

  const split = () => {
    if (!project) return;
    const t = playhead;
    const under = selection.filter((id) => {
      const f = findClip(project, id);
      return f && t > f.clip.start && t < clipEnd(f.clip);
    });
    apply((p) => (under.length ? under.reduce((q, id) => splitClip(q, id, t).project, p) : splitAt(p, t)));
  };

  const remove = () => {
    if (!selection.length) return;
    apply((p) => deleteClips(p, selection));
    setSelection([]);
  };

  const editPoints = useMemo(() => {
    const pts = new Set<number>([0]);
    for (const c of project ? mainTrack(project)?.clips ?? [] : []) {
      pts.add(c.start);
      pts.add(clipEnd(c));
    }
    return [...pts].sort((a, b) => a - b);
  }, [project]);

  const zoomTo = useCallback((next: number) => setPps(Math.max(MIN_PPS, Math.min(MAX_PPS, next))), []);

  const run = useCallback(
    (action: Action) => {
      if (!project) return;
      const total = projectDuration(project);
      const frameT = Math.round(playhead * fps) / fps;
      switch (action) {
        case "play":
          playerRef.current?.toggle();
          break;
        case "split":
          split();
          break;
        case "delete":
          remove();
          break;
        case "undo":
          if (histRef.current) commit(undoHistory(histRef.current));
          break;
        case "redo":
          if (histRef.current) commit(redoHistory(histRef.current));
          break;
        case "frameBack":
          seek(frameT - 1 / fps);
          break;
        case "frameForward":
          seek(frameT + 1 / fps);
          break;
        case "secondBack":
          seek(playhead - 1);
          break;
        case "secondForward":
          seek(playhead + 1);
          break;
        case "prevEdit":
          seek([...editPoints].reverse().find((x) => x < playhead - 1e-3) ?? 0);
          break;
        case "nextEdit":
          seek(editPoints.find((x) => x > playhead + 1e-3) ?? total);
          break;
        case "home":
          seek(0);
          break;
        case "end":
          seek(total);
          break;
        case "zoomIn":
          zoomTo(pps * 1.5);
          break;
        case "zoomOut":
          zoomTo(pps / 1.5);
          break;
        case "zoomFit":
          zoomTo((document.querySelector(".tl-scroll")?.clientWidth ?? 900) / Math.max(1, total + 1));
          break;
        case "snapping":
          setSnapping((s) => !s);
          break;
        case "save":
          void saveNow();
          break;
        case "export":
          setShowExport(true);
          break;
        case "deselect":
          setSelection([]);
          break;
        case "help":
          setShowHelp((h) => !h);
          break;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [project, playhead, fps, selection, editPoints, pps, saveNow],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (showExport || frame || typingInto(e.target)) return;
      const action = actionFor(e);
      if (!action) return;
      e.preventDefault();
      run(action);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, showExport, frame]);

  // ---- media
  const importFiles = async (paths: string[]) => {
    if (!paths.length) return;
    setImporting(true);
    const r = await api.mediaInfo(paths);
    setImporting(false);
    if (r.errors.length) setToast(r.errors.map((e) => `${baseName(e.path)}: ${e.message}`).join("\n"));
    if (r.media.length) apply((p) => addMedia(p, r.media).project);
  };

  const addAt = (mediaId: string, where: "main" | "overlay" | "audio" | string, at = playhead) => {
    let added: string | null = null;
    apply((p) => {
      let trackId: string | undefined = where;
      if (where === "main") trackId = mainTrack(p)?.id;
      else if (where === "overlay") trackId = p.tracks.find((t) => t.kind === "overlay")?.id;
      else if (where === "audio") trackId = p.tracks.find((t) => t.kind === "audio" && t.role === "music")?.id ?? p.tracks.find((t) => t.kind === "audio")?.id;
      const r = insertMedia(p, mediaId, at, trackId);
      added = r.clipId;
      return r.project;
    });
    if (added) setSelection([added]);
  };

  const exactFrame = async () => {
    const problem = await saveNow();
    if (problem) {
      setFrame({ error: problem });
      return;
    }
    setFrame({});
    const r = await api.renderFrame(path, playhead);
    setFrame(r.path ? { url: mediaUrl(r.path) } : { error: r.error ?? "The frame could not be rendered." });
  };

  // ---- render
  if (!opened || (!project && !opened.error)) {
    return (
      <div className="editor loading" data-testid="editor">
        <p className="muted">Opening {baseName(path)}… · Binubuksan…</p>
      </div>
    );
  }
  if (opened.error || !project || !history) {
    return (
      <div className="editor loading" data-testid="editor">
        <div className="card" role="alert" style={{ maxWidth: 560 }}>
          <h3>This project could not be opened</h3>
          <p className="error" style={{ whiteSpace: "pre-wrap" }}>{opened.error}</p>
          <button className="btn" onClick={onClose}>Back</button>
        </div>
      </div>
    );
  }

  const total = projectDuration(project);
  const saveText = { saved: "Saved · Naka-save", saving: "Saving…", unsaved: "Saving soon…", error: "Not saved!" }[save.state];

  return (
    <div
      className="editor"
      data-testid="editor"
      onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
      onDrop={(e) => {
        if (!e.dataTransfer.files.length) return;
        e.preventDefault();
        void importFiles([...e.dataTransfer.files].map((f) => api.pathForFile(f)));
      }}
    >
      <header className="ed-top">
        <button className="btn small ghost" onClick={close} aria-label="Back to the AI edit">← Back</button>
        <div className="ed-title">
          <strong title={path}>{project.name || baseName(path)}</strong>
          <span className="muted small">Timeline editor · I-edit nang mano-mano</span>
        </div>
        <span className="spacer" />
        <button className="btn small ghost" onClick={() => run("undo")} disabled={!history.past.length} aria-label="Undo" title="Undo (Ctrl+Z)">↶</button>
        <button className="btn small ghost" onClick={() => run("redo")} disabled={!history.future.length} aria-label="Redo" title="Redo (Ctrl+Shift+Z)">↷</button>
        <span className={`save-state ${save.state}`} role="status" title={save.message} data-testid="save-state">{saveText}</span>
        <button className="btn small ghost" onClick={() => setShowHelp(true)} aria-label="Keyboard shortcuts">?</button>
        <button className="btn small primary" onClick={() => setShowExport(true)} data-testid="export">Export</button>
      </header>

      <MediaBin project={project} thumbs={thumbs} url={url} busy={importing} onImport={async () => importFiles(await api.pickMedia())} onAdd={(id, where) => addAt(id, where)} />

      <main className="ed-preview" aria-label="Preview">
        <Player ref={playerRef} project={project} videoPath={null} mediaUrl={url} keepTime compact onTime={setPlayhead} onPlaying={setPlaying} />
        <div className="ed-transport">
          <button className="btn small" onClick={() => run("play")} aria-label={playing ? "Pause" : "Play"} data-testid="play">{playing ? "❚❚" : "▶"}</button>
          <span className="time" data-testid="time">{mmss(playhead)} / {mmss(total)}</span>
          <button className="btn small ghost" onClick={exactFrame} title="The real frame from the engine, as it will export">Exact frame</button>
        </div>
      </main>

      <aside className="ed-inspector" aria-label="Clip settings">
        <Inspector
          project={project}
          selection={selection}
          onProps={(id, patch: ClipPatch, key) => apply((p) => setClipProps(p, id, patch), key)}
          onSpeed={(id, sp) => apply((p) => setSpeed(p, id, sp), `speed:${id}`)}
          onDelete={remove}
        />
      </aside>

      <section className="ed-timeline" aria-label="Timeline">
        <div className="tl-toolbar">
          <button className="btn small" onClick={split} title="Split at the playhead (S)" data-testid="split">✂ Split</button>
          <button className="btn small" onClick={remove} disabled={!selection.length} title="Delete (Del)" data-testid="delete">🗑 Delete</button>
          <span className="spacer" />
          <label className="toggle-inline" title="Snap clips to edges and the playhead (N)">
            <input type="checkbox" checked={snapping} onChange={(e) => setSnapping(e.target.checked)} aria-label="Snapping" /> Snapping
          </label>
          <button className="btn small ghost" onClick={() => run("zoomOut")} aria-label="Zoom out">−</button>
          <input type="range" min={Math.log(MIN_PPS)} max={Math.log(MAX_PPS)} step={0.01} value={Math.log(pps)} onChange={(e) => zoomTo(Math.exp(Number(e.target.value)))} aria-label="Timeline zoom" className="zoom-slider" />
          <button className="btn small ghost" onClick={() => run("zoomIn")} aria-label="Zoom in">+</button>
          <button className="btn small ghost" onClick={() => run("zoomFit")} title="Fit the whole video (Ctrl+0)">Fit</button>
        </div>
        <Timeline
          project={project}
          selection={selection}
          playhead={playhead}
          pps={pps}
          snapping={snapping}
          peaks={peaks}
          thumbs={thumbs}
          url={url}
          onSelect={setSelection}
          onSeek={seek}
          onDraft={setDraft}
          onCommit={(p) => apply(() => p)}
          onError={setToast}
          onZoom={(next) => zoomTo(next)}
          onDropMedia={(id, at, trackId) => addAt(id, trackId ?? "main", at)}
          onTrackFlag={(id, flag, value) => apply((p) => setTrackFlag(p, id, flag, value))}
        />
      </section>

      {toast && (
        <div className="toast" role="alert" data-testid="toast">
          {toast}
        </div>
      )}
      {showExport && (
        <ExportDialog projectPath={path} defaultOutput={exportPathFor(path)} fps={fps} beforeExport={saveNow} onClose={() => setShowExport(false)} />
      )}
      {showHelp && <ShortcutsHelp onClose={() => setShowHelp(false)} />}
      {frame && (
        <FrameDialog
          previewNote="This is the true frame from the FFmpeg engine at the playhead: what the export will look like."
          imageUrl={frame.url}
          error={frame.error}
          onClose={() => setFrame(null)}
        />
      )}
    </div>
  );
}

function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-label="Keyboard shortcuts">
        <h2>Keyboard shortcuts</h2>
        <table className="shortcuts">
          <tbody>
            {SHORTCUTS.map(([keys, what, tl]) => (
              <tr key={keys}>
                <td><kbd>{keys}</kbd></td>
                <td>{what}<br /><span className="muted small">{tl}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
