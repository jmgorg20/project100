// Export: render the project to an MP4 with the FFmpeg engine (what the timeline shows).
import { useEffect, useRef, useState } from "react";
import type { ExportOptions, ExportUpdate } from "../../shared/api";
import { baseName } from "../../shared/paths";
import { Dialog } from "../components/Dialogs";
import { api } from "../lib/api";

export const QUALITY: Record<string, { crf: number; speed: ExportOptions["speed"]; label: string }> = {
  high: { crf: 18, speed: "medium", label: "High (bigger file)" },
  standard: { crf: 21, speed: "medium", label: "Standard (recommended for TikTok/Reels)" },
  small: { crf: 26, speed: "fast", label: "Smaller file (quicker to upload)" },
  draft: { crf: 28, speed: "veryfast", label: "Quick draft (fastest export)" },
};

export const SIZES: { height: ExportOptions["height"]; label: string }[] = [
  { height: 1920, label: "1080 × 1920 (Full HD)" },
  { height: 1280, label: "720 × 1280" },
  { height: 960, label: "540 × 960" },
];

export function ExportDialog({ projectPath, defaultOutput, fps, beforeExport, onClose, broll }: {
  projectPath: string;
  defaultOutput: string;
  fps: number;
  /** Save the latest changes first. Returns an error message, or null. */
  beforeExport: () => Promise<string | null>;
  onClose: () => void;
  /** Stock credits to post with the video, and how many clips were made with AI. */
  broll?: { credits: string[]; aiClips: number };
}) {
  const [copied, setCopied] = useState(false);
  const creditText = broll?.credits.length ? `Credits: ${broll.credits.join("; ")}` : "";
  const [output, setOutput] = useState(defaultOutput);
  const [height, setHeight] = useState<ExportOptions["height"]>(1920);
  const [rate, setRate] = useState<ExportOptions["fps"]>(fps as ExportOptions["fps"]);
  const [quality, setQuality] = useState("standard");
  const [task, setTask] = useState<{ id: string; percent: number } | null>(null);
  const [result, setResult] = useState<ExportUpdate | null>(null);
  const [error, setError] = useState("");

  const current = useRef<string | null>(null);
  useEffect(
    () =>
      api.onExport((u) => {
        if (u.taskId !== current.current) return;
        if (u.done) {
          current.current = null;
          setTask(null);
          setResult(u);
        } else setTask((t) => (t ? { ...t, percent: u.percent ?? t.percent } : t));
      }),
    [],
  );

  const start = async () => {
    setError("");
    setResult(null);
    const problem = await beforeExport();
    if (problem) {
      setError(problem);
      return;
    }
    const q = QUALITY[quality];
    const id = await api.startExport(projectPath, { output, height, fps: rate, crf: q.crf, speed: q.speed });
    current.current = id;
    setTask({ id, percent: 0 });
  };

  const choose = async () => {
    const picked = await api.pickExportPath(output);
    if (picked) setOutput(picked);
  };

  return (
    <Dialog title="Export video · I-export" onClose={task ? undefined : onClose}>
      <div className="stack" data-testid="export-dialog">
        <div className="field">
          <label htmlFor="export-size">Size</label>
          <select id="export-size" value={height} onChange={(e) => setHeight(Number(e.target.value) as ExportOptions["height"])} disabled={Boolean(task)}>
            {SIZES.map((s) => (
              <option key={s.height} value={s.height}>{s.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="export-fps">Frames per second</label>
          <select id="export-fps" value={rate} onChange={(e) => setRate(Number(e.target.value) as ExportOptions["fps"])} disabled={Boolean(task)}>
            {[24, 25, 30, 50, 60].map((f) => (
              <option key={f} value={f}>{f}{f === fps ? " (as edited)" : ""}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="export-quality">Quality</label>
          <select id="export-quality" value={quality} onChange={(e) => setQuality(e.target.value)} disabled={Boolean(task)}>
            {Object.entries(QUALITY).map(([k, q]) => (
              <option key={k} value={k}>{q.label}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Save as</label>
          <div className="row">
            <span className="path" title={output} data-testid="export-path">{baseName(output)}</span>
            <button className="btn small" onClick={choose} disabled={Boolean(task)}>Change…</button>
          </div>
        </div>

        {broll && broll.aiClips > 0 && (
          <p className="notice small" data-testid="export-ai-label">
            <strong>AI-made content:</strong> {broll.aiClips} B-roll clip{broll.aiClips === 1 ? " was" : "s were"} made with AI. When you post, turn on the
            platform's "AI-generated" label (TikTok, Facebook and YouTube ask for it). · May AI-generated na bahagi: i-on ang AI label pag nag-post.
          </p>
        )}
        {creditText && (
          <div className="field" data-testid="export-credits">
            <label htmlFor="export-credit-text">Stock credits (paste them in your caption)</label>
            <textarea id="export-credit-text" readOnly rows={Math.min(4, broll!.credits.length + 1)} value={creditText} />
            <div className="row">
              <button
                className="btn small"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(creditText);
                    setCopied(true);
                  } catch {
                    setCopied(false);
                  }
                }}
              >
                {copied ? "Copied ✓" : "Copy credits"}
              </button>
              <span className="muted small">Pexels and Pixabay don't require credit, but it is kind and recommended.</span>
            </div>
          </div>
        )}

        {task && (
          <div data-testid="export-progress">
            <div className="bar big"><div style={{ width: `${task.percent}%` }} /></div>
            <p className="muted small">Exporting… {Math.round(task.percent)}% · Huwag munang isara ang app.</p>
          </div>
        )}
        {result?.output && (
          <div className="card" role="status" data-testid="export-done">
            <strong>Done · Tapos na!</strong>
            <p className="small" style={{ margin: "4px 0 8px" }}>{baseName(result.output)}</p>
            <div className="row">
              <button className="btn small" onClick={() => api.showInFolder(result.output!)}>Show in folder</button>
              <button className="btn small" onClick={() => api.openPath(result.output!)}>Play it</button>
            </div>
          </div>
        )}
        {result?.cancelled && <p className="muted" role="status">Export cancelled. Nothing was saved.</p>}
        {(error || result?.error) && <p className="error" role="alert">{error || result?.error}</p>}

        <div className="row" style={{ justifyContent: "flex-end" }}>
          {task ? (
            <button className="btn danger" onClick={() => api.cancelExport(task.id)}>Cancel</button>
          ) : (
            <>
              <button className="btn" onClick={onClose}>Close</button>
              <button className="btn primary" onClick={start} data-testid="export-start">{result?.output ? "Export again" : "Export"}</button>
            </>
          )}
        </div>
      </div>
    </Dialog>
  );
}
