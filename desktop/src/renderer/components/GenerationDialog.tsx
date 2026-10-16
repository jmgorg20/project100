// "AI pictures, clips & voice": hardware, WanGP, quality tiers, benchmark, compare.
// Shows facts only (installed or not, measured times, VRAM): it never says a tier or model
// is better; the creator compares the actual outputs.
import { useCallback, useEffect, useState } from "react";
import type { CompareResult, ContentType, GenStatus, GenTaskUpdate, TierRow } from "../../shared/types";
import { CONTENT_TYPES } from "../../shared/types";
import { api, mediaUrl } from "../lib/api";
import { Dialog } from "./Dialogs";

const TYPE_LABEL: Record<ContentType, string> = { image: "Pictures", video: "Video clips", voice: "Voice-over" };

export function seconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return "";
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export function gb(mb: number | null | undefined): string {
  return mb === null || mb === undefined ? "" : `${(mb / 1024).toFixed(1)} GB`;
}

function benchmarkText(row: TierRow): string {
  const b = row.benchmark;
  if (!b) return row.installed ? "Not tested on this PC yet" : "";
  const vram = b.peak_vram_mb ? `, peak VRAM about ${gb(b.peak_vram_mb)}` : "";
  if (b.success) return `Test passed in ${seconds(b.seconds)}${vram}`;
  if (b.out_of_memory) return `Test ran out of GPU memory${vram}`;
  return `Test failed: ${b.reason}`;
}

function Links({ links }: { links: string[] }) {
  if (!links.length) return null;
  return (
    <span className="small">
      {links.map((url) => (
        <a key={url} href={url} target="_blank" rel="noreferrer" style={{ marginRight: 8 }}>
          {url.replace(/^https:\/\/(www\.)?/, "").replace(/\/blob\/main\/docs\//, " docs: ")}
        </a>
      ))}
      <span className="muted">Read the model's license there before downloading it in WanGP.</span>
    </span>
  );
}

function Media({ path }: { path: string }) {
  const url = mediaUrl(path);
  if (/\.(png|jpe?g|webp)$/i.test(path)) return <img src={url} alt="" className="compare-media" />;
  if (/\.(wav|mp3|flac|ogg|m4a)$/i.test(path)) return <audio src={url} controls style={{ width: "100%" }} />;
  return <video src={url} controls className="compare-media" />;
}

/**
 * Stays mounted once opened (hidden when `open` is false), so a test or Compare that is
 * still running keeps its log, Stop button and results when the window is closed and reopened.
 */
export function GenerationDialog({ open, onClose, onStatus, onRunning }: {
  open: boolean;
  onClose: () => void;
  onStatus?: (s: GenStatus) => void;
  onRunning?: (running: boolean) => void;
}) {
  const [status, setStatus] = useState<GenStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [type, setType] = useState<ContentType>("image");
  const [folder, setFolder] = useState("");
  const [python, setPython] = useState("");
  const [task, setTask] = useState<{ id: string; kind: "benchmark" | "compare"; lines: string[] } | null>(null);
  const [compare, setCompare] = useState<CompareResult[]>([]);
  const [prompt, setPrompt] = useState("A cozy sari-sari store at golden hour, vertical photo");
  const [seed, setSeed] = useState(1234);

  const load = useCallback(async (check: boolean) => {
    setBusy(check ? "Starting WanGP to read its models… (this can take a minute)" : "Detecting the hardware…");
    const s = await api.genStatus(check).catch((e: unknown) => ({ error: `Could not read the AI generation status: ${String(e)}` }));
    setBusy("");
    if ("error" in s) {
      setError(s.error);
      return;
    }
    setError("");
    setStatus(s);
    setFolder((f) => f || s.wangp.folder || "");
    setPython((p) => p || s.wangp.python || "");
    onStatus?.(s);
  }, [onStatus]);

  useEffect(() => {
    if (open) load(false);
  }, [open, load]);

  useEffect(
    () =>
      api.onGenTask((u: GenTaskUpdate) => {
        setTask((t) => {
          if (!t || t.id !== u.taskId) return t;
          const e = u.event;
          let line = "";
          if (e?.type === "benchmark_start" || e?.type === "compare_start") line = `Running ${e.content_type} ${e.tier}…`;
          if (e?.type === "benchmark_result") line = `${e.content_type} ${e.tier}: ${e.success ? "passed" : e.reason} in ${seconds(e.seconds as number)}`;
          if (e?.type === "compare_result") line = `${e.tier}: ${e.success ? "done" : e.reason} in ${seconds(e.seconds as number)}`;
          if (e?.type === "error") line = `Error: ${e.message}`;
          if (e?.type === "log" && /waiting for another GPU job/.test(String(e.message))) line = "Waiting for another GPU job to finish…";
          if (e?.type === "result" && t.kind === "compare") setCompare((e.results as CompareResult[]) ?? []);
          if (u.done) line = u.cancelled ? "Stopped." : u.startError ? `Error: ${u.startError}` : "Finished.";
          return line ? { ...t, lines: [...t.lines, line] } : t;
        });
        if (u.done) load(false);
      }),
    [load],
  );

  const saveWangp = async () => {
    const r = await api.setWangp(folder, python);
    if (r.error) setError(r.error);
    await load(false);
  };

  const setTier = async (kind: "default" | "pin", tier: string | null) => {
    const s = await api.setTier(type, kind, tier);
    if ("error" in s) setError(s.error);
    else {
      setStatus(s);
      onStatus?.(s);
    }
  };

  const running = Boolean(task && !task.lines.some((l) => l === "Finished." || l === "Stopped." || l.startsWith("Error: ")));
  useEffect(() => onRunning?.(running), [running, onRunning]);
  const rows = status?.tiers[type] ?? [];
  const installed = rows.filter((r) => r.installed);
  const rec = status?.recommendations[type];

  if (!open) return null;
  return (
    <Dialog title="AI pictures, clips & voice" onClose={onClose} wide>
      <div className="stack gen-dialog" data-testid="generation">
        <p className="muted small" style={{ margin: 0 }}>
          Made on this PC with <strong>WanGP</strong> by DeepBeepMeep (installed separately; its own license applies).
          This app never downloads models: you choose and download them in WanGP.
        </p>
        {busy && <p className="muted">{busy}</p>}
        {error && <p className="error" role="alert">{error}</p>}

        {status && (
          <>
            <section className="card" aria-label="This PC">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h3 style={{ margin: 0 }}>This PC</h3>
                <button className="btn small" onClick={() => load(false)}>Detect again</button>
              </div>
              <p style={{ margin: "8px 0 0" }} data-testid="hardware">{status.hardware_summary}</p>
              <p className="muted small" style={{ margin: 0 }}>
                {Object.entries(status.hardware.disk_free_mb)
                  .filter(([, mb]) => mb !== null)
                  .map(([p, mb]) => `${gb(mb)} free on ${p}`)
                  .join(" · ")}
              </p>
              {status.hardware_changed && (
                <p className="warn small">
                  The hardware changed since last time (was: {status.previous_hardware}). Old test results are kept for that
                  hardware; run the tests again here.
                </p>
              )}
              {status.hardware.notes.map((n) => (
                <p key={n} className="muted small" style={{ margin: "4px 0 0" }}>{n}</p>
              ))}
            </section>

            <section className="card" aria-label="WanGP">
              <h3>WanGP</h3>
              <div className="field">
                <label htmlFor="wangp-folder">WanGP folder (where wgp.py is)</label>
                <input id="wangp-folder" type="text" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\WanGP" />
              </div>
              <div className="field" style={{ marginTop: 8 }}>
                <label htmlFor="wangp-python">WanGP's Python</label>
                <input id="wangp-python" type="text" value={python} onChange={(e) => setPython(e.target.value)} placeholder="C:\Users\you\miniconda3\envs\wan2gp\python.exe" />
                <span className="muted small">In a terminal: conda activate wan2gp, then: where python</span>
              </div>
              <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
                <button className="btn small" onClick={saveWangp}>Save</button>
                <button className="btn small" disabled={status.setup_problems.length > 0 || Boolean(busy)} onClick={() => load(true)}>
                  Check WanGP models
                </button>
                <button className="btn small ghost" onClick={() => api.openPath(status.settings_file)}>Edit settings file</button>
                <button className="btn small ghost" onClick={() => api.openPath(status.templates_folder)}>Templates folder</button>
              </div>
              {status.wangp.version && <p className="muted small">WanGP {status.wangp.version}, models checked {status.wangp.checked_at}</p>}
              {[...status.setup_problems, ...status.problems, ...(status.wangp.error ? [status.wangp.error] : [])].map((p) => (
                <p key={p} className="warn small">{p}</p>
              ))}
            </section>

            <div className="segmented" role="tablist" aria-label="Content type">
              {CONTENT_TYPES.map((c) => (
                <button key={c} role="tab" aria-pressed={c === type} aria-selected={c === type} onClick={() => setType(c)}>
                  {TYPE_LABEL[c]}
                </button>
              ))}
            </div>

            <section aria-label="Quality tiers" data-testid="tiers">
              {rows.map((row) => {
                const isDefault = status.default_tier[type] === row.name;
                const isPinned = status.pinned_tier[type] === row.name;
                return (
                  <div key={row.name} className={`tier${row.installed ? "" : " disabled"}`} data-testid={`tier-${row.name}`} aria-disabled={!row.installed}>
                    <div className="row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
                      <strong>
                        {row.name} <span className="muted">· {row.label}</span>
                      </strong>
                      <span className={`chip-status ${row.installed ? "ok" : ""}`}>{row.status}</span>
                    </div>
                    <div className="small">
                      {row.model_name ?? ""}
                      {isDefault && <span className="badge">your default</span>}
                      {isPinned && <span className="badge">pinned</span>}
                    </div>
                    {row.installed && (
                      <div className="small muted">
                        {row.avg_seconds ? `About ${seconds(row.avg_seconds)} per item on this PC (${row.runs} run${row.runs === 1 ? "" : "s"})` : "No timing on this PC yet"}
                        {" · "}
                        {row.vram_gb ? `VRAM need: about ${row.vram_gb} GB (your estimate)` : "VRAM need: unknown"}
                        {" · "}
                        {benchmarkText(row)}
                      </div>
                    )}
                    {!row.installed && row.disabled_reason && <div className="small muted">{row.disabled_reason}</div>}
                    {!row.installed && row.model_type && <Links links={row.links} />}
                  </div>
                );
              })}
              <div className="row" style={{ marginTop: 8, flexWrap: "wrap" }}>
                <label className="small" htmlFor="pin">Auto mode uses</label>
                <select id="pin" style={{ width: "auto" }} value={status.pinned_tier[type] ?? ""} onChange={(e) => setTier("pin", e.target.value || null)}>
                  <option value="">Automatic{status.choices[type].order[0] ? ` (now: ${status.choices[type].order[0]})` : ""}</option>
                  {installed.map((r) => (
                    <option key={r.name} value={r.name}>Always {r.name}</option>
                  ))}
                </select>
                <span className="muted small">
                  Preview: {status.choices[type].preview ?? "none"}. If a job fails or takes too long, the next tier down is tried.
                </span>
              </div>
            </section>

            <section className="card" aria-label="Test and compare">
              <h3>Test and compare</h3>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <button className="btn small" disabled={running || !installed.length} onClick={async () => setTask({ id: await api.startBenchmark([type]), kind: "benchmark", lines: [] })}>
                  Test {TYPE_LABEL[type].toLowerCase()} tiers
                </button>
                <button className="btn small" disabled={running || !CONTENT_TYPES.some((c) => status.tiers[c].some((r) => r.installed))} onClick={async () => setTask({ id: await api.startBenchmark([]), kind: "benchmark", lines: [] })}>
                  Test everything
                </button>
                <span className="muted small">A short test per installed tier, one GPU job at a time.</span>
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <input type="text" aria-label="Compare prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
                <input type="text" aria-label="Seed" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} style={{ width: 90 }} />
                <button
                  className="btn small primary"
                  disabled={running || installed.length < 1 || !prompt.trim()}
                  onClick={async () => {
                    setCompare([]);
                    setTask({ id: await api.startCompare(type, prompt, seed), kind: "compare", lines: [] });
                  }}
                >
                  Compare
                </button>
              </div>
              <p className="muted small" style={{ margin: "4px 0 0" }}>Same prompt and seed on every installed tier, so you can judge the results yourself.</p>
              {task && (
                <div className="small" data-testid="task-log" style={{ marginTop: 8 }}>
                  {task.lines.map((l, i) => (
                    <div key={i}>{l}</div>
                  ))}
                  {running && <button className="btn small danger" style={{ marginTop: 6 }} onClick={() => api.cancelGenTask(task.id)}>Stop</button>}
                </div>
              )}
              {compare.length > 0 && (
                <div className="compare-grid" data-testid="compare">
                  {compare.map((r) => (
                    <figure key={r.tier} className="compare-item">
                      {r.output ? <Media path={r.output} /> : <div className="compare-media empty">{r.reason}</div>}
                      <figcaption>
                        <strong>{r.tier}</strong> · {r.success ? seconds(r.seconds) : r.reason}
                        {r.peak_vram_mb ? ` · VRAM ~${gb(r.peak_vram_mb)}` : ""}
                        {r.success && (
                          <button className="btn small" style={{ display: "block", marginTop: 6 }} disabled={status.default_tier[type] === r.tier} onClick={() => setTier("default", r.tier)}>
                            {status.default_tier[type] === r.tier ? "Your default" : "Use as default"}
                          </button>
                        )}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              )}
            </section>

            {rec && (
              <section className="card" aria-label="Recommendations" data-testid="recommendations">
                <h3>On this PC</h3>
                <p style={{ marginTop: 0 }}>
                  {rec.tier
                    ? `Highest ${TYPE_LABEL[type].toLowerCase()} tier that passed its test here: ${rec.tier} (${seconds(rec.tier_seconds)}).`
                    : `No ${TYPE_LABEL[type].toLowerCase()} tier has passed a test here yet.`}
                </p>
                {rec.could_download.length > 0 && (
                  <>
                    <p className="small" style={{ marginBottom: 4 }}>Other WanGP models of this kind that are not installed (from WanGP's own list):</p>
                    <ul className="small">
                      {rec.could_download.slice(0, 12).map((m) => (
                        <li key={m.model_type}>
                          {m.name} <span className="muted">({m.family ?? "WanGP"}, {m.status})</span> <Links links={m.links} />
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>
            )}
          </>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </Dialog>
  );
}
