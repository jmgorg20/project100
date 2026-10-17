// "Set up tracking": says in plain words what is missing (the free MediaPipe package and the
// model files), and downloads the models ONLY when you confirm here. Nothing is downloaded by
// itself.
import { useState } from "react";
import type { TrackStatus } from "../../shared/api";
import { Dialog } from "../components/Dialogs";
import { api } from "../lib/api";

const INSTALL = "python -m pip install mediapipe";

export function TrackSetup({ status, onStatus, onClose }: { status: TrackStatus; onStatus: (s: TrackStatus) => void; onClose: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const missing = status.models.filter((m) => !m.present && (m.kind !== "pose"));
  const download = async () => {
    setBusy(true);
    setError("");
    const r = await api.downloadTrackModels(missing.map((m) => m.kind));
    setBusy(false);
    setConfirm(false);
    if ("error" in r) setError(r.error);
    else onStatus(r);
  };
  return (
    <Dialog title="Follow my hands: set up · I-set up" onClose={busy ? undefined : onClose}>
      <div className="stack" data-testid="track-setup">
        <p className="muted small" style={{ margin: 0 }}>
          Effects that follow your hands or face use the free, local <strong>MediaPipe</strong> tracker from Google. It runs on your PC (no internet, no account). Two things are needed once:
          <br />
          Libre at lokal ang tracker; dalawang bagay lang ang kailangan, isang beses lang.
        </p>
        <section className="card" style={{ margin: 0 }}>
          <strong>1. The MediaPipe package {status.installed ? "✓" : ""}</strong>
          {status.installed ? (
            <p className="small" style={{ margin: "4px 0 0" }}>Installed.</p>
          ) : (
            <>
              <p className="small" style={{ margin: "4px 0" }}>Open PowerShell and run this once, then restart the app:</p>
              <div className="row">
                <code className="path" data-testid="track-install-command">{INSTALL}</code>
                <button
                  className="btn small"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(INSTALL);
                      setCopied(true);
                    } catch {
                      setCopied(false);
                    }
                  }}
                >
                  {copied ? "Copied ✓" : "Copy"}
                </button>
              </div>
            </>
          )}
        </section>
        <section className="card" style={{ margin: 0 }}>
          <strong>2. The model files {status.hands ? "✓" : ""}</strong>
          <ul className="small" style={{ margin: "4px 0", paddingLeft: 18 }}>
            {status.models.map((m) => (
              <li key={m.kind} data-testid={`track-model-${m.kind}`}>
                {m.kind === "hand" ? "Hands" : m.kind === "face" ? "Face (and a rough body)" : "Body pose (optional, better aura)"} · {m.size} ·{" "}
                {m.present ? "downloaded ✓" : "not downloaded"}{" "}
                <a href={m.page} target="_blank" rel="noreferrer">model page</a>
              </li>
            ))}
          </ul>
          {missing.length > 0 && !confirm && (
            <button className="btn small primary" onClick={() => setConfirm(true)} disabled={!status.installed} title={status.installed ? "" : "Install the package first"} data-testid="track-download">
              Download the {missing.length === 1 ? "model" : "models"}…
            </button>
          )}
          {confirm && (
            <div className="notice small" role="alertdialog" aria-label="Confirm the model download" data-testid="track-confirm">
              <p style={{ margin: 0 }}>
                This downloads {missing.map((m) => m.file).join(", ")} from Google (storage.googleapis.com) into the editor's <code>models/tracking</code> folder. They are Google's MediaPipe models and have their own terms: read the model pages first. The app never downloads a model without this confirmation.
              </p>
              <div className="row" style={{ justifyContent: "flex-end", marginTop: 8 }}>
                <button className="btn small" onClick={() => setConfirm(false)} disabled={busy}>Cancel</button>
                <button className="btn small primary" onClick={download} disabled={busy} data-testid="track-confirm-yes">
                  {busy ? "Downloading…" : "I read it · Download"}
                </button>
              </div>
            </div>
          )}
          <p className="muted small" style={{ margin: "6px 0 0" }}>Prefer to do it by hand? <code>python editor.py track-models</code> lists the links; put the files in <code>models/tracking</code>.</p>
        </section>
        {status.problems.length > 0 && !status.available && (
          <ul className="muted small" style={{ margin: 0, paddingLeft: 18 }}>
            {status.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {status.available && <p className="status done" role="status">Ready. You can add tracked effects now. · Handa na!</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose} disabled={busy}>Close</button>
        </div>
      </div>
    </Dialog>
  );
}
