// The "B-roll" tab: describe what to show and the app finds or makes it (your B-roll folder,
// then free stock with your key, then AI), or add a file from your B-roll folder yourself.
import { useCallback, useEffect, useState } from "react";
import type { BrollRequest, LibraryFile } from "../../shared/api";
import { BROLL_STYLES } from "../../shared/brollEdit";
import type { BrollStyle } from "../../shared/types";
import { api, mediaUrl } from "../lib/api";

export type BrollAsk = Omit<BrollRequest, "projectPath" | "exclude" | "newVersion">;

export interface BrollTask {
  label: string;
  percent?: number;
}

const SOURCES: { id: BrollRequest["source"]; label: string }[] = [
  { id: "auto", label: "Best available (folder → stock → AI)" },
  { id: "library", label: "Only my B-roll folder" },
  { id: "stock", label: "Only free stock (Pexels/Pixabay)" },
  { id: "ai", label: "Only AI (WanGP on this PC)" },
];

export function TaskStatus({ task, onCancel }: { task: BrollTask; onCancel: () => void }) {
  return (
    <div className="broll-task" role="status" data-testid="broll-task">
      <span className="spinner" aria-hidden="true" />
      <span className="small">
        {task.label}
        {task.percent !== undefined ? ` · ${Math.round(task.percent)}%` : "…"}
      </span>
      <button className="btn small ghost" onClick={onCancel}>Cancel</button>
    </div>
  );
}

export function BrollPanel({ folder, stockKeys, task, onAsk, onCancel, onAddFile, onChooseFolder }: {
  folder: string;
  /** Which stock sites have a key (Settings). */
  stockKeys: string[];
  task: BrollTask | null;
  onAsk: (ask: BrollAsk) => void;
  onCancel: () => void;
  onAddFile: (file: string) => void;
  onChooseFolder: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [search, setSearch] = useState("");
  const [style, setStyle] = useState<BrollStyle>("realistic");
  const [kind, setKind] = useState<"image" | "video">("image");
  const [position, setPosition] = useState<"full" | "top" | "center">("full");
  const [duration, setDuration] = useState(3);
  const [source, setSource] = useState<BrollRequest["source"]>("auto");
  const [quality, setQuality] = useState<"draft" | "final">("final");
  const ready = Boolean((prompt.trim() || search.trim()) && duration > 0);
  return (
    <div className="broll-panel media-list" data-testid="broll-panel">
      <h3>Find or make B-roll · Maghanap o gumawa</h3>
      <label className="insp-field">
        <span className="insp-label">What should it show? <span className="muted small">· English works best</span></span>
        <textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. a steaming cup of coffee on a wooden table" aria-label="What to show" />
      </label>
      <label className="insp-field">
        <span className="insp-label">Search words <span className="muted small">· optional, 2–4 words</span></span>
        <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="coffee cup" aria-label="Search words" />
      </label>
      <div className="broll-grid">
        <label className="insp-field">
          <span className="insp-label">Look · Itsura</span>
          <select value={style} onChange={(e) => setStyle(e.target.value as BrollStyle)} aria-label="Look">
            {BROLL_STYLES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
        <label className="insp-field">
          <span className="insp-label">Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as "image" | "video")} aria-label="Kind">
            <option value="image">Picture</option>
            <option value="video">Video clip</option>
          </select>
        </label>
        <label className="insp-field">
          <span className="insp-label">Place</span>
          <select value={position} onChange={(e) => setPosition(e.target.value as "full" | "top" | "center")} aria-label="Place">
            <option value="full">Full screen</option>
            <option value="top">Top (pop-in)</option>
            <option value="center">Middle (pop-in)</option>
          </select>
        </label>
        <label className="insp-field">
          <span className="insp-label">Seconds</span>
          <input type="number" min={0.5} max={10} step={0.5} value={duration} onChange={(e) => setDuration(Number(e.target.value))} aria-label="Seconds on screen" />
        </label>
      </div>
      <label className="insp-field">
        <span className="insp-label">Where from · Saan kukunin</span>
        <select value={source} onChange={(e) => setSource(e.target.value as BrollRequest["source"])} aria-label="Where from">
          {SOURCES.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
      </label>
      {source !== "library" && source !== "stock" && (
        <label className="insp-field">
          <span className="insp-label">If AI makes it</span>
          <select value={quality} onChange={(e) => setQuality(e.target.value as "draft" | "final")} aria-label="AI quality">
            <option value="final">Final quality (slower)</option>
            <option value="draft">Quick draft (fast; regenerate later)</option>
          </select>
        </label>
      )}
      {task ? (
        <TaskStatus task={task} onCancel={onCancel} />
      ) : (
        <button className="btn small primary" disabled={!ready} onClick={() => onAsk({ prompt: prompt.trim(), search: search.trim(), style, kind, position, duration, source, quality })} data-testid="broll-add">
          Add at the playhead · Idagdag
        </button>
      )}
      <p className="muted small">
        {stockKeys.length ? `Free stock: ${stockKeys.join(", ")} (credits are kept for you).` : "Free stock: add a free Pexels or Pixabay key in Settings to use it."} AI pictures and clips are made on this PC with WanGP, if it is set up.
      </p>
      <Library key={folder} folder={folder} onChoose={onChooseFolder} onAdd={onAddFile} />
    </div>
  );
}

function Library({ folder, onChoose, onAdd }: { folder: string; onChoose: () => void; onAdd: (file: string) => void }) {
  const [files, setFiles] = useState<LibraryFile[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const load = useCallback(async () => {
    const r = await api.listLibrary("broll");
    setFiles(r.files);
    setError(r.error ?? "");
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const words = filter.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = (files ?? []).filter((f) => words.every((w) => `${f.group} ${f.name}`.toLowerCase().includes(w)));
  return (
    <div className="library" data-testid="library-broll">
      <h3>Your B-roll folder</h3>
      <div className="row" style={{ padding: "0 0 6px" }}>
        <span className="muted small path" title={folder}>{folder || "No B-roll folder yet"}</span>
        <button className="btn small" onClick={onChoose}>{folder ? "Change" : "Choose folder"}</button>
      </div>
      {!folder && (
        <p className="muted small">
          A folder of your own clips and pictures. Name files and folders after what they show (e.g. <em>coffee/cup.jpg</em>): the AI edit uses them first.
          Ilagay dito ang sarili mong B-roll.
        </p>
      )}
      {error && <p className="error small">{error}</p>}
      {folder && files !== null && (
        <>
          <input type="text" placeholder="Search · Hanapin" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Search B-roll" />
          {shown.length === 0 && <p className="muted small">No pictures or videos found here.</p>}
          {shown.slice(0, 300).map((f) => (
            <div key={f.path} className="lib-item" data-testid="broll-item">
              {/\.(png|jpe?g|webp|bmp)$/i.test(f.name) ? <img className="lib-thumb" src={mediaUrl(f.path)} alt="" loading="lazy" /> : <span className="lib-thumb" aria-hidden="true">🎞</span>}
              <div className="media-meta">
                <div className="media-name" title={f.path}>{f.name}</div>
                {f.group && <div className="muted small">{f.group}</div>}
              </div>
              <button className="btn small" onClick={() => onAdd(f.path)} aria-label={`Add ${f.name} as B-roll`}>＋</button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
