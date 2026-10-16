// When no clip is selected: the whole project's sound (loudness, music ducking, noise
// reduction), your vocabulary, and adding a caption.
import { useState } from "react";
import type { AudioSettings } from "../../shared/effectsEdit";
import type { Project } from "../../shared/types";

const pct = (v: number) => `${Math.round(v * 100)}%`;

export function ProjectPanel({ project, onAudio, onVocabulary, onAddCaption, onRecord }: {
  project: Project;
  onAudio: (patch: AudioSettings, key: string) => void;
  onVocabulary: () => void;
  onAddCaption: (text: string) => void;
  onRecord: () => void;
}) {
  const a = project.settings.audio ?? {};
  const [text, setText] = useState("");
  return (
    <div className="project-panel" data-testid="project-panel">
      <div className="insp-head">
        <h3>This video · Ang video</h3>
        <span className="muted small">Click a clip to change just that clip.</span>
      </div>

      <section className="insp-section" aria-label="Sound">
        <h3>Sound · Tunog</h3>
        <label className="toggle-inline small">
          <input type="checkbox" checked={Boolean(a.normalize)} onChange={(e) => onAudio({ normalize: e.target.checked }, "normalize")} aria-label="Even out the loudness" />
          Even out the loudness (speech)
        </label>
        {a.normalize && (
          <label className="insp-field">
            <span className="insp-label">Target</span>
            <select value={a.loudness ?? -14} onChange={(e) => onAudio({ loudness: Number(e.target.value) }, "loudness")} aria-label="Loudness target">
              <option value={-14}>-14 LUFS (TikTok, Reels, YouTube)</option>
              <option value={-16}>-16 LUFS (a bit quieter)</option>
              <option value={-11}>-11 LUFS (loud)</option>
            </select>
          </label>
        )}
        <label className="insp-field">
          <span className="insp-label">
            Lower the music when someone talks <span className="insp-value">{a.ducking ? pct(a.ducking) : "off"}</span>
          </span>
          <input type="range" min={0} max={1} step={0.05} value={a.ducking ?? 0} onChange={(e) => onAudio({ ducking: Number(e.target.value) }, "ducking")} aria-label="Music ducking" data-testid="ducking" />
        </label>
        <label className="insp-field">
          <span className="insp-label">
            Reduce background noise <span className="insp-value">{a.denoise ? pct(a.denoise) : "off"}</span>
          </span>
          <input type="range" min={0} max={1} step={0.05} value={a.denoise ?? 0} onChange={(e) => onAudio({ denoise: Number(e.target.value) }, "denoise")} aria-label="Noise reduction" data-testid="denoise" />
        </label>
        <p className="muted small" style={{ margin: 0 }}>Heard in the export (and "Exact frame" for pictures). The live preview plays the sound as recorded.</p>
        <button className="btn small" onClick={onRecord}>🎙 Record a voice-over</button>
      </section>

      <section className="insp-section" aria-label="Captions">
        <h3>Captions</h3>
        <div className="row">
          <input type="text" value={text} placeholder="New caption at the playhead" aria-label="New caption text" onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && text.trim() && (onAddCaption(text), setText(""))} />
          <button className="btn small" disabled={!text.trim()} onClick={() => (onAddCaption(text), setText(""))}>Add</button>
        </div>
        <button className="btn small ghost" onClick={onVocabulary} data-testid="open-vocabulary">Your words & corrections (Taglish)…</button>
      </section>
    </div>
  );
}
