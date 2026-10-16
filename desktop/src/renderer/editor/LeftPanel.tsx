// The editor's left side: the project's media, your music and sound-effect folders, and
// effects/transitions/colour looks to add at the playhead.
import { useCallback, useEffect, useRef, useState } from "react";
import type { LibraryFile, Thumbs, TrackStatus } from "../../shared/api";
import { FX_INFO, GRADES } from "../../shared/effectsEdit";
import { TRACK_FX } from "../../shared/trackEdit";
import type { FxEffect, Project, TrackEffect } from "../../shared/types";
import { api, mediaUrl } from "../lib/api";
import { BrollPanel, type BrollAsk, type BrollTask } from "./BrollPanel";
import { MediaBin } from "./MediaBin";

type Tab = "media" | "broll" | "music" | "sfx" | "effects";

export interface BrollActions {
  folder: string;
  stockKeys: string[];
  task: BrollTask | null;
  onAsk: (ask: BrollAsk) => void;
  onCancel: () => void;
  onAddFile: (file: string) => void;
  onChooseFolder: () => void;
}

/** Effects that follow your hands / face (tracking). */
export interface TrackedActions {
  status: TrackStatus | null;
  /** Following is running: its label and progress. */
  task: { label: string; percent?: number } | null;
  /** The project already has tracked points. */
  hasTracking: boolean;
  /** Tracked effects in the project that have nothing to follow yet. */
  untracked: number;
  onAdd: (effect: TrackEffect) => void;
  onFollow: () => void;
  onCancel: () => void;
  onSetup: () => void;
}

export interface EffectActions {
  onFx: (effect: FxEffect) => void;
  onTransition: (effect: FxEffect) => void;
  onZoom: (kind: "punch" | "smooth") => void;
  onGrade: (grade: string, wholeVideo: boolean) => void;
  tracked: TrackedActions;
}

export function LeftPanel({ project, thumbs, url, busy, onImport, onAdd, onAddLibrary, effects, folders, onChooseFolder, broll }: {
  project: Project;
  thumbs: Record<string, Thumbs>;
  url: (p: string) => string;
  busy: boolean;
  onImport: () => void;
  onAdd: (mediaId: string, where: "main" | "overlay" | "audio") => void;
  onAddLibrary: (file: string, kind: "music" | "sfx") => void;
  effects: EffectActions;
  folders: { music: string; sfx: string };
  onChooseFolder: (kind: "music" | "sfx") => void;
  broll: BrollActions;
}) {
  const [tab, setTab] = useState<Tab>("media");
  // [tab, shown text, full name for screen readers and the tooltip]
  const tabs: [Tab, string, string][] = [
    ["media", "Media", "Media"], ["broll", "B-roll", "B-roll"], ["music", "Music", "Music"], ["sfx", "SFX", "Sound effects"], ["effects", "Effects", "Effects"],
  ];
  return (
    <div className="left-panel" data-testid="left-panel">
      <div className="segmented tabs" role="tablist" aria-label="Library">
        {tabs.map(([k, label, full]) => (
          <button key={k} role="tab" aria-selected={tab === k} aria-pressed={tab === k} onClick={() => setTab(k)} aria-label={full} title={full}>
            {label}
          </button>
        ))}
      </div>
      {tab === "media" && <MediaBin project={project} thumbs={thumbs} url={url} busy={busy} onImport={onImport} onAdd={onAdd} />}
      {(tab === "music" || tab === "sfx") && (
        <Library key={`${tab}-${folders[tab]}`} kind={tab} folder={folders[tab]} onChoose={() => onChooseFolder(tab)} onAdd={(f) => onAddLibrary(f, tab)} />
      )}
      {tab === "broll" && <BrollPanel {...broll} />}
      {tab === "effects" && <EffectsList actions={effects} />}
    </div>
  );
}

function Library({ kind, folder, onChoose, onAdd }: { kind: "music" | "sfx"; folder: string; onChoose: () => void; onAdd: (file: string) => void }) {
  const [files, setFiles] = useState<LibraryFile[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const load = useCallback(async () => {
    const r = await api.listLibrary(kind);
    setFiles(r.files);
    setError(r.error ?? "");
  }, [kind]);
  useEffect(() => {
    void load();
    return () => audio.current?.pause();
  }, [load]);
  const play = (f: LibraryFile) => {
    audio.current?.pause();
    if (playing === f.path) return setPlaying(null);
    audio.current = new Audio(mediaUrl(f.path));
    audio.current.play().catch(() => {});
    audio.current.onended = () => setPlaying(null);
    setPlaying(f.path);
  };
  const shown = (files ?? []).filter((f) => !filter || f.name.toLowerCase().includes(filter.toLowerCase()));
  const label = kind === "music" ? "music" : "sound effects";
  return (
    <div className="library" data-testid={`library-${kind}`}>
      <div className="row" style={{ padding: "8px 12px" }}>
        <span className="muted small path" title={folder}>{folder || `No ${label} folder yet`}</span>
        <button className="btn small" onClick={onChoose}>{folder ? "Change" : "Choose folder"}</button>
      </div>
      {!folder && (
        <p className="muted small" style={{ padding: "0 12px" }}>
          Choose a folder with your own {label} (MP3, WAV…). Only use sounds you have the right to use. Gamitin lang ang musikang may karapatan ka.
        </p>
      )}
      {error && <p className="error small" style={{ padding: "0 12px" }}>{error}</p>}
      {folder && files !== null && (
        <>
          <input type="text" placeholder="Search · Hanapin" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={`Search ${label}`} style={{ margin: "0 12px", width: "calc(100% - 24px)" }} />
          <div className="media-list">
            {shown.length === 0 && <p className="muted small">No sound files found here.</p>}
            {shown.map((f) => (
              <div key={f.path} className="lib-item" data-testid="library-item">
                <button className="btn small ghost" onClick={() => play(f)} aria-label={`${playing === f.path ? "Stop" : "Listen to"} ${f.name}`}>
                  {playing === f.path ? "■" : "▶"}
                </button>
                <div className="media-meta">
                  <div className="media-name" title={f.path}>{f.name}</div>
                  {f.group && <div className="muted small">{f.group}</div>}
                </div>
                <button className="btn small" onClick={() => onAdd(f.path)} aria-label={`Add ${f.name}`}>＋</button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function EffectsList({ actions }: { actions: EffectActions }) {
  const fx = Object.keys(FX_INFO) as FxEffect[];
  const [whole, setWhole] = useState(false);
  return (
    <div className="effects-list media-list" data-testid="effects-list">
      <h3>At the playhead · Sa playhead</h3>
      <div className="fx-grid">
        <button className="btn small" onClick={() => actions.onZoom("punch")}>Punch-in zoom</button>
        <button className="btn small" onClick={() => actions.onZoom("smooth")}>Smooth zoom</button>
        {fx.map((k) => (
          <button key={k} className="btn small" onClick={() => actions.onFx(k)} title={FX_INFO[k].tl}>{FX_INFO[k].label}</button>
        ))}
      </div>
      <h3>Transitions (on the nearest cut)</h3>
      <div className="fx-grid">
        {(["flash", "whip", "dip", "glitch"] as FxEffect[]).map((k) => (
          <button key={k} className="btn small" onClick={() => actions.onTransition(k)} aria-label={`${FX_INFO[k].label} transition`}>{FX_INFO[k].label}</button>
        ))}
      </div>
      <h3>Colour look · Kulay</h3>
      <label className="toggle-inline small">
        <input type="checkbox" checked={whole} onChange={(e) => setWhole(e.target.checked)} /> Whole video (else: the clip at the playhead)
      </label>
      <div className="fx-grid grades">
        {GRADES.filter((g) => g !== "none").map((g) => (
          <button key={g} className="btn small" onClick={() => actions.onGrade(g, whole)}>{g.replace(/_/g, " ")}</button>
        ))}
      </div>
      <TrackedSection actions={actions.tracked} />
      <p className="muted small">Every effect is a clip on the Effects track: drag it, trim it, or change its strength on the right.</p>
    </div>
  );
}

function TrackedSection({ actions }: { actions: TrackedActions }) {
  const { status, task } = actions;
  const ready = Boolean(status?.available);
  return (
    <div data-testid="tracked-section">
      <h3>Follow my hands · Sundan ang kamay</h3>
      {status && !ready && (
        <div className="notice small" data-testid="track-not-ready">
          <p style={{ margin: 0 }}>{status.installed ? "The hand model is not downloaded yet." : "The free MediaPipe tracker is not installed yet."} Hindi pa ready.</p>
          <button className="btn small" style={{ marginTop: 6 }} onClick={actions.onSetup} data-testid="track-setup-open">Set up…</button>
        </div>
      )}
      <div className="fx-grid tracked">
        {(Object.keys(TRACK_FX) as TrackEffect[]).map((k) => (
          <button key={k} className="btn small" onClick={() => actions.onAdd(k)} title={TRACK_FX[k].tl} aria-label={`Tracked ${TRACK_FX[k].label}`}>
            {TRACK_FX[k].label}
          </button>
        ))}
      </div>
      {task ? (
        <div className="broll-task" role="status" data-testid="track-task">
          <span className="spinner" aria-hidden="true" />
          <span className="small">
            {task.label}
            {task.percent !== undefined ? ` · ${Math.round(task.percent)}%` : "…"}
          </span>
          <button className="btn small ghost" onClick={actions.onCancel}>Cancel</button>
        </div>
      ) : (
        <button className={`btn small${actions.untracked ? " primary" : ""}`} disabled={!ready} onClick={actions.onFollow} data-testid="track-follow" title={ready ? "Find your hands and face in this video" : "Set up tracking first"}>
          {actions.hasTracking ? "Follow again · Ulitin" : "Follow my hands · Sundan"}
        </button>
      )}
      {actions.untracked > 0 && !task && (
        <p className="warn small" data-testid="track-untracked">
          {actions.untracked} tracked effect{actions.untracked === 1 ? " has" : "s have"} nothing to follow yet. Click “Follow my hands”.
        </p>
      )}
      <p className="muted small">Adds an effect that follows a hand, the face or the body. It fades out by itself when the point is not visible.</p>
    </div>
  );
}
