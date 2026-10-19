// Settings (API keys, provider, Python), the consent notice, and the exact-frame viewer.
import { useEffect, useState } from "react";
import type { EngineCheck } from "../../shared/api";
import type { KeyName, KeysStatus, Provider, Settings } from "../../shared/types";
import { api } from "../lib/api";

export function Dialog({ title, onClose, wide, children }: { title: string; onClose?: () => void; wide?: boolean; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

function KeyField({ provider, label, status, onChange }: { provider: KeyName; label: React.ReactNode; status: KeysStatus; onChange: (s: KeysStatus) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const info = status[provider];
  const save = async () => {
    setError("");
    try {
      onChange(await api.setKey(provider, value));
      setValue("");
    } catch (e) {
      setError(String((e as Error).message).replace(/^Error invoking remote method '[^']+': (Error: )?/, ""));
    }
  };
  return (
    <div className="field">
      <label htmlFor={`key-${provider}`}>{label}</label>
      <div className="row">
        <input id={`key-${provider}`} type="password" autoComplete="off" placeholder={info.set ? `Saved (${info.hint})` : "Paste your key"} value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn small" onClick={save} disabled={!value.trim()}>Save</button>
        {info.set && <button className="btn small danger" onClick={async () => onChange(await api.clearKey(provider))}>Remove</button>}
      </div>
      {error && <span className="error">{error}</span>}
    </div>
  );
}

export function SettingsDialog({ settings, onSave, onClose }: { settings: Settings; onSave: (patch: Partial<Settings>) => void; onClose: () => void }) {
  const [keys, setKeys] = useState<KeysStatus | null>(null);
  const [draft, setDraft] = useState(settings);
  const [check, setCheck] = useState<EngineCheck | null>(null);
  useEffect(() => {
    api.keysStatus().then(setKeys);
  }, []);
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setDraft((d) => ({ ...d, [key]: value }));
  return (
    <Dialog title="Settings" onClose={onClose}>
      <div className="stack">
        <p className="muted small" style={{ margin: 0 }}>
          Keys are encrypted on this PC and only given to the editor engine when it runs. They are never shown again or logged.
        </p>
        {keys && !keys.encryptionAvailable && <p className="warn">This PC cannot encrypt keys, so the app will not save them. Use the .env file instead (see README).</p>}
        {keys && <KeyField provider="groq" label="Groq API key (free at console.groq.com)" status={keys} onChange={setKeys} />}
        {keys && <KeyField provider="anthropic" label="Anthropic API key (optional, paid)" status={keys} onChange={setKeys} />}
        <div className="field">
          <label htmlFor="provider">AI that plans the edit</label>
          <select id="provider" value={draft.provider} onChange={(e) => set("provider", e.target.value as Provider)}>
            <option value="groq">Groq (default, free tier)</option>
            <option value="anthropic">Anthropic Claude (your key, paid)</option>
          </select>
        </div>
        <div className="row">
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="groq-model">Groq model</label>
            <input id="groq-model" type="text" value={draft.groqModel} onChange={(e) => set("groqModel", e.target.value)} />
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label htmlFor="anthropic-model">Anthropic model</label>
            <input id="anthropic-model" type="text" value={draft.anthropicModel} onChange={(e) => set("anthropicModel", e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="stt">Speech to text</label>
          <select id="stt" value={draft.transcribeWith} onChange={(e) => set("transcribeWith", e.target.value as Settings["transcribeWith"])}>
            <option value="groq">Groq Whisper (online, fast)</option>
            <option value="local">On this PC (offline, slower; needs faster-whisper)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="caption-punctuation">Caption punctuation · Bantas sa caption</label>
          <select id="caption-punctuation" value={draft.captionPunctuation} onChange={(e) => set("captionPunctuation", e.target.value as Settings["captionPunctuation"])}>
            <option value="remove">Remove (no , . ! ? ; : on screen; i-check and 3,600 stay)</option>
            <option value="keep">Keep (as transcribed)</option>
          </select>
        </div>
        <label className="row">
          <input type="checkbox" checked={draft.fixCaptionsFirst} onChange={(e) => set("fixCaptionsFirst", e.target.checked)} data-testid="fix-captions-first" />
          <span>Let me fix the words before the AI edit · Ayusin muna ang mga salita</span>
        </label>
        <h3 className="settings-head">B-roll · Dagdag na kuha</h3>
        <div className="field">
          <label htmlFor="broll-folder">Your B-roll folder (your own clips and pictures; name them after what they show)</label>
          <div className="row">
            <input id="broll-folder" type="text" value={draft.brollFolder} onChange={(e) => set("brollFolder", e.target.value)} placeholder="e.g. C:\Users\you\Videos\B-roll" />
            <button className="btn small" onClick={async () => { const f = await api.pickFolder("Your B-roll folder"); if (f) set("brollFolder", f); }}>Choose…</button>
          </div>
        </div>
        <label className="row">
          <input type="checkbox" checked={draft.useStock} onChange={(e) => set("useStock", e.target.checked)} />
          <span>Use free stock photos and videos (Pexels / Pixabay) when your folder has nothing that fits</span>
        </label>
        {keys && (
          <KeyField provider="pexels" status={keys} onChange={setKeys}
            label={<>Pexels API key (free: <a href="https://www.pexels.com/api/" target="_blank" rel="noreferrer">pexels.com/api</a>)</>} />
        )}
        {keys && (
          <KeyField provider="pixabay" status={keys} onChange={setKeys}
            label={<>Pixabay API key (free: <a href="https://pixabay.com/api/docs/" target="_blank" rel="noreferrer">pixabay.com/api/docs</a>; also has cartoons and drawings)</>} />
        )}
        <div className="field">
          <label htmlFor="python">Python</label>
          <input id="python" type="text" value={draft.pythonPath} onChange={(e) => set("pythonPath", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="engine">Editor folder (where editor.py is)</label>
          <input id="engine" type="text" value={draft.engineDir} onChange={(e) => set("engineDir", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="out">Save finished videos in</label>
          <input id="out" type="text" value={draft.outputDir} onChange={(e) => set("outputDir", e.target.value)} />
        </div>
        <div className="row">
          <button className="btn small" onClick={async () => setCheck(await api.checkEngine())}>Check the editor engine</button>
          {check && <span className={check.ok ? "status done" : "error"}>{check.message}</span>}
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={() => onSave(draft)}>Save</button>
        </div>
      </div>
    </Dialog>
  );
}

export function ConsentDialog({ onAccept }: { onAccept: () => void }) {
  const [checked, setChecked] = useState(false);
  return (
    <Dialog title="Before you start">
      <div className="stack">
        <p style={{ margin: 0 }}>
          Only edit videos and photos of people who agreed to appear in them. Siguraduhing pumayag ang lahat ng nasa video at litrato.
        </p>
        <p className="muted small" style={{ margin: 0 }}>
          This app cuts, captions and arranges what you recorded. It has no face swap, deepfake, voice cloning or lip-sync features.
          Use only music and pictures you have the right to use.
        </p>
        <label className="row">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          <span>I understand</span>
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn primary" disabled={!checked} onClick={onAccept}>Continue</button>
        </div>
      </div>
    </Dialog>
  );
}

export function FrameDialog({ previewNote, imageUrl, error, onClose }: { previewNote: string; imageUrl?: string; error?: string; onClose: () => void }) {
  return (
    <Dialog title="Exact frame from the engine" onClose={onClose}>
      <div className="stack">
        <p className="muted small" style={{ margin: 0 }}>{previewNote}</p>
        {error ? <p className="error">{error}</p> : imageUrl ? <img src={imageUrl} alt="The rendered frame" style={{ width: "100%", borderRadius: 12 }} /> : <p className="muted">Rendering the frame…</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </Dialog>
  );
}
