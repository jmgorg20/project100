import { GRAPHIC_STYLES } from "../shared/graphicsEdit";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EstimateResult } from "../shared/api";
import { canRedo, canUndo, currentVersion } from "../shared/history";
import { formatCost } from "../shared/planItems";
import type { GenStatus, Job, JobMode, Plan, Provider, Settings, VideoHistory } from "../shared/types";
import { ConsentDialog, FrameDialog, SettingsDialog } from "./components/Dialogs";
import { GenerationDialog } from "./components/GenerationDialog";
import { Editor } from "./editor/Editor";
import { PlanReview } from "./components/PlanReview";
import { Player } from "./components/Player";
import { Stages } from "./components/Stages";
import { SummaryCard } from "./components/SummaryCard";
import { api, mediaUrl } from "./lib/api";

const ACTIVE = new Set(["queued", "running", "review"]);
const base = (p: string) => p.split(/[\\/]/).pop() ?? p;

function statusText(job: Job | undefined, history: VideoHistory | undefined): [string, string] {
  if (job?.status === "queued") return ["Waiting…", ""];
  if (job?.status === "running") return [job.stageLabel ? `${job.stageLabel}…` : "Starting…", ""];
  if (job?.status === "review") return ["Ready to review", "review"];
  if (job?.status === "failed") return ["Did not finish", "failed"];
  if (job?.status === "cancelled") return ["Cancelled", ""];
  const version = history ? currentVersion(history) : null;
  if (version) return [version.summary?.fallback ? "Done (preset edit)" : "Done", "done"];
  if (history?.versions.length) return ["Showing the original", ""];
  return ["Not edited yet", ""];
}

function genSummary(gen: GenStatus | null): string {
  if (!gen) return "";
  if (gen.setup_problems.length) return "· WanGP not set up";
  const names: [keyof GenStatus["choices"], string][] = [["image", "pictures"], ["video", "clips"], ["voice", "voice-over"]];
  const ready = names.filter(([c]) => gen.choices[c].order.length).map(([c, label]) => `${label} ${gen.choices[c].order[0]}`);
  return ready.length ? `· ${ready.join(", ")}` : "· no tier installed";
}

export function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [videos, setVideos] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [photos, setPhotos] = useState<string[]>([]);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [histories, setHistories] = useState<Record<string, VideoHistory>>({});
  const [instruction, setInstruction] = useState("");
  const [graphicsStyle, setGraphicsStyle] = useState("auto");
  const [followUp, setFollowUp] = useState("");
  const [estimate, setEstimate] = useState<EstimateResult | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [view, setView] = useState<"edited" | "original">("edited");
  const [frame, setFrame] = useState<{ url?: string; error?: string } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [gen, setGen] = useState<GenStatus | null>(null);
  const [showGen, setShowGen] = useState(false);
  const [editorPath, setEditorPath] = useState<string | null>(null);
  const [genMounted, setGenMounted] = useState(false);
  const [genRunning, setGenRunning] = useState(false);
  // Per video (sent with each edit); start from the limits in the generation settings file.
  const [limits, setLimits] = useState<{ minutes: number; clips: number } | null>(null);
  const instructionRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.getSettings().then(setSettings);
    api.listJobs().then((list) => setJobs(Object.fromEntries(list.map((j) => [j.id, j]))));
    const offJob = api.onJobChanged((job) => setJobs((prev) => ({ ...prev, [job.id]: job })));
    const offHistory = api.onHistoryChanged((h) => setHistories((prev) => ({ ...prev, [h.video]: h })));
    // Hardware is detected on start; if that or anything else fails, the app works without it.
    api.genStatus(false).then((s) => {
      if (!("error" in s)) onGenStatus(s);
    }).catch(() => {});
    return () => {
      offJob();
      offHistory();
    };
  }, []);

  const onGenStatus = useCallback((s: GenStatus) => {
    setGen(s);
    setLimits((l) => l ?? { minutes: s.limits.max_generation_minutes, clips: s.limits.max_ai_clips });
  }, []);

  const openGen = () => {
    setGenMounted(true);
    setShowGen(true);
  };
  const closeGen = useCallback(() => setShowGen(false), []);

  const addVideos = useCallback(async (paths: string[]) => {
    const fresh = paths.filter((p) => p);
    if (!fresh.length) return;
    setVideos((prev) => [...prev, ...fresh.filter((p) => !prev.includes(p))]);
    setSelected((s) => s ?? fresh[0]);
    for (const p of fresh) {
      const h = await api.history(p);
      setHistories((prev) => ({ ...prev, [p]: h }));
    }
  }, []);

  const jobList = useMemo(() => Object.values(jobs).sort((a, b) => a.createdAt - b.createdAt), [jobs]);
  const latestJob = useCallback((video: string) => [...jobList].reverse().find((j) => j.video === video && j.status !== "dismissed"), [jobList]);
  const activeJob = (video: string) => {
    const job = latestJob(video);
    return job && ACTIVE.has(job.status) ? job : undefined;
  };

  const selectedJob = selected ? latestJob(selected) : undefined;
  const selectedActive = selectedJob && ACTIVE.has(selectedJob.status) ? selectedJob : undefined;
  const history = selected ? histories[selected] : undefined;
  const version = history ? currentVersion(history) : null;
  const provider: Provider = settings?.provider ?? "groq";
  const auto = settings?.autoMode ?? true;

  // Which videos the main button edits: everything not edited yet, else the selected one.
  const fresh = videos.filter((v) => !histories[v]?.versions.length && !activeJob(v));
  const targets = fresh.length ? fresh : selected && !selectedActive ? [selected] : [];
  const redoing = !fresh.length && Boolean(version);

  useEffect(() => {
    const video = targets[0];
    setEstimate(null);
    if (!video) return;
    const timer = setTimeout(() => api.estimate(video, provider, instruction).then(setEstimate), 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targets.join("|"), provider]);

  const startJobs = (list: string[], mode: JobMode, text: string, planFile?: string) =>
    api.addJobs(
      list.map((video) => ({
        video, photos, instruction: text, provider, auto, mode, planFile,
        maxGenMinutes: limits?.minutes, maxAiClips: limits?.clips, graphics: graphicsStyle,
      })),
    );

  const saveSettings = async (patch: Partial<Settings>) => setSettings(await api.setSettings(patch));

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = [...e.dataTransfer.files];
    const paths = files.map((f) => api.pathForFile(f));
    const isPhoto = (p: string) => /\.(png|jpe?g|webp|bmp)$/i.test(p);
    const isVideo = (p: string) => /\.(mp4|mov|m4v|mkv|avi|webm|3gp)$/i.test(p);
    addVideos(paths.filter(isVideo));
    setPhotos((prev) => [...prev, ...paths.filter((p) => isPhoto(p) && !prev.includes(p))]);
  };

  const showExactFrame = async (seconds: number) => {
    const projectFile = selectedActive?.projectFile ?? (view === "edited" ? version?.projectFile : undefined);
    if (!projectFile) {
      setFrame({ error: "There is no project yet: the exact frame is available once the AI has planned the edit." });
      return;
    }
    setFrame({});
    const r = await api.renderFrame(projectFile, seconds);
    setFrame(r.path ? { url: mediaUrl(r.path) } : { error: r.error ?? "The frame could not be rendered." });
  };

  // What the player shows.
  let previewProject = null;
  let previewVideo: string | null = selected;
  if (selectedActive?.project) previewProject = selectedActive.project;
  else if (version && view === "edited") previewVideo = version.output;
  const [statusLabel, statusClass] = statusText(selectedJob, history);

  if (!settings) return null;
  if (editorPath) return <Editor key={editorPath} path={editorPath} onClose={() => setEditorPath(null)} />;
  return (
    <div className="app" onDragOver={(e) => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={onDrop}>
      <header className="topbar">
        <h1>Auto Video Editor</h1>
        <span className="muted small">AI first edit · you stay in control</span>
        <span className="spacer" />
        <button className="btn small" onClick={async () => { const p = await api.pickProject(); if (p) setEditorPath(p); }} title="Open a .project.json in the timeline editor">Open project…</button>
        <button className="btn small" onClick={() => openGen()}>{genRunning ? "AI models · testing…" : "AI models"}</button>
        <button className="btn small" onClick={() => setShowSettings(true)}>Settings</button>
      </header>

      {/* ------------------------------------------------ videos */}
      <aside className="panel" aria-label="Videos">
        <div className="panel-head">
          <h2>Videos</h2>
          <button className="btn small" onClick={async () => addVideos(await api.pickVideos())}>Add videos</button>
        </div>
        <div className="panel-body stack" style={{ flex: 1 }}>
          {videos.length === 0 ? (
            <div className={`drop${dragOver ? " over" : ""}`}>
              Drop your videos here
              <br />
              <span className="small">o i-click ang “Add videos”. You can add several: they all get the same instructions.</span>
            </div>
          ) : (
            <div role="list">
              {videos.map((video) => {
                const job = latestJob(video);
                const [text, cls] = statusText(job, histories[video]);
                const running = job?.status === "running";
                return (
                  <div key={video} role="listitem" className={`video-item${video === selected ? " selected" : ""}`} onClick={() => setSelected(video)} data-testid="video-item">
                    <span aria-hidden="true">🎬</span>
                    <div style={{ minWidth: 0 }}>
                      <div className="video-name" title={video}>{base(video)}</div>
                      <div className={`status ${cls}`}>{text}</div>
                      {running && job?.stage === "render" && (
                        <div className="bar"><div style={{ width: `${job.percent ?? 0}%` }} /></div>
                      )}
                    </div>
                    {job && (job.status === "running" || job.status === "queued") ? (
                      <button className="btn small ghost" onClick={(e) => { e.stopPropagation(); api.cancelJob(job.id); }} aria-label={`Cancel ${base(video)}`}>Cancel</button>
                    ) : (
                      <button className="btn small ghost" onClick={(e) => { e.stopPropagation(); setVideos((v) => v.filter((x) => x !== video)); if (selected === video) setSelected(null); }} aria-label={`Remove ${base(video)} from the list`}>✕</button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
          <div className="stack" style={{ gap: 8 }}>
            <div className="row">
              <strong style={{ flex: 1 }}>Photos the AI may use</strong>
              <button className="btn small" onClick={async () => { const picked = await api.pickPhotos(); setPhotos((p) => [...p, ...picked.filter((x) => !p.includes(x))]); }}>Add photos</button>
            </div>
            {photos.length === 0 ? (
              <span className="muted small">Optional. Name them well (e.g. gcash_receipt.png) so the AI knows when to show them.</span>
            ) : (
              <div className="chips">
                {photos.map((p) => (
                  <span className="chip" key={p} title={p}>
                    <span>{base(p)}</span>
                    <button onClick={() => setPhotos((list) => list.filter((x) => x !== p))} aria-label={`Remove ${base(p)}`}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
        <p className="notice">Only use videos and photos of people who agreed to be in them. No face swaps or deepfakes here.</p>
      </aside>

      {/* ------------------------------------------------ preview */}
      <main className="stack" style={{ minHeight: 0 }} aria-label="Preview">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row" style={{ minWidth: 0 }}>
            <strong className="video-name">{selected ? base(selected) : "Preview"}</strong>
            {selected && <span className={`status ${statusClass}`}>{statusLabel}</span>}
          </div>
          {version && !selectedActive && (
            <div className="segmented" role="group" aria-label="Show">
              <button aria-pressed={view === "edited"} onClick={() => setView("edited")}>Edited</button>
              <button aria-pressed={view === "original"} onClick={() => setView("original")}>Original</button>
            </div>
          )}
        </div>
        {selectedActive && <Stages job={selectedActive} />}
        <Player
          project={previewProject}
          videoPath={previewProject ? null : previewVideo}
          mediaUrl={mediaUrl}
          onExactFrame={previewProject || (version && view === "edited") ? showExactFrame : undefined}
          emptyText="Add a video to start. Magdagdag ng video para magsimula."
        />
        {previewProject && (
          <p className="muted small" style={{ margin: 0 }}>
            Live preview: captions, photos and zooms are drawn by the app and may differ slightly from the final video. Use “Exact frame” to see the real thing.
          </p>
        )}
      </main>

      {/* ------------------------------------------------ AI */}
      <aside className="panel" aria-label="AI edit">
        <div className="panel-head">
          <h2>{redoing ? "Redo with new instructions" : "Describe your video"}</h2>
        </div>
        <div className="panel-body stack">
          {gen?.hardware_changed && (
            <p className="warn small" role="status" style={{ margin: 0 }}>
              This PC's hardware changed (was: {gen.previous_hardware}). Test the AI models again in “AI models”.
            </p>
          )}
          <textarea
            ref={instructionRef}
            aria-label="Instructions for the AI"
            placeholder={'Halimbawa: "Mabilis na edit, malaking yellow captions, ipakita ang gcash_receipt.png pag sinabi kong resibo. Tanggalin ang part na nagkamali ako."'}
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
          />
          <label className="toggle">
            <input type="checkbox" className="switch" role="switch" checked={auto} onChange={(e) => saveSettings({ autoMode: e.target.checked })} aria-label="Auto mode" />
            <span>
              <strong>Auto mode</strong>
              <br />
              <span className="muted small">{auto ? "The AI's edit is applied and rendered right away. You can undo it." : "You review the AI's changes before anything is rendered."}</span>
            </span>
          </label>
          <div className="row">
            <select aria-label="AI provider" value={provider} onChange={(e) => saveSettings({ provider: e.target.value as Provider })} style={{ flex: 1 }}>
              <option value="groq">Groq (free tier)</option>
              <option value="anthropic">Anthropic Claude (paid, your key)</option>
            </select>
          </div>
          <label className="field small">
            Motion graphics · Pop-up na salita at graphics
            <select aria-label="Motion graphics" value={graphicsStyle} onChange={(e) => setGraphicsStyle(e.target.value)} data-testid="graphics-style">
              {GRAPHIC_STYLES.map((g) => (
                <option key={g.id} value={g.id}>{g.label} · {g.tl}</option>
              ))}
            </select>
          </label>
          <details className="card" data-testid="gen-limits">
            <summary className="small">
              <strong>AI pictures &amp; clips</strong>{" "}
              <span className="muted">{genSummary(gen)}</span>
            </summary>
            {limits && (
              <div className="limits" style={{ marginTop: 8 }}>
                <label className="field small">
                  Max generation time (min)
                  <input type="number" min={1} max={600} aria-label="Max generation minutes" value={limits.minutes} onChange={(e) => setLimits({ ...limits, minutes: Math.max(1, Number(e.target.value) || 1) })} />
                </label>
                <label className="field small">
                  Max AI clips
                  <input type="number" min={0} max={50} aria-label="Max AI clips" value={limits.clips} onChange={(e) => setLimits({ ...limits, clips: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} />
                </label>
              </div>
            )}
            <p className="muted small" style={{ margin: "8px 0 0" }}>
              Only when your instructions ask for them (e.g. “add a short clip of coffee here”). Made on this PC with WanGP; Auto mode shows a quick draft first, then the final version.
            </p>
            <button className="btn small" style={{ marginTop: 8 }} onClick={() => openGen()}>AI models…</button>
          </details>
          {estimate && !estimate.error && (
            <p className="muted small" style={{ margin: 0 }} data-testid="estimate">
              {estimate.paid_provider
                ? `Estimated API cost: about ${formatCost(estimate.total)} per video.`
                : `Groq: $0 on the free tier (about ${formatCost(estimate.total)} per video on the paid tier).`}
              {estimate.transcript_cached ? " The transcript is saved, so it is not paid again." : ""}
            </p>
          )}
          <button
            className="btn primary"
            disabled={!targets.length}
            onClick={() => startJobs(targets, "new", instruction)}
            data-testid="run"
          >
            {targets.length > 1 ? `Edit ${targets.length} videos with AI` : redoing ? "Redo with these instructions" : "Edit with AI"}
          </button>

          {selectedActive?.status === "review" && selectedActive.plan && (
            <PlanReview
              key={selectedActive.id}
              job={selectedActive}
              onApply={(plan: Plan) => api.applyPlan(selectedActive.id, plan)}
              onReject={() => api.dismissJob(selectedActive.id)}
            />
          )}

          {selectedActive?.status === "running" && selectedActive.summary && <SummaryCard summary={selectedActive.summary} title="What the AI is doing" />}

          {selectedJob?.status === "failed" && (
            <div className="card" role="alert">
              <h3>That did not work</h3>
              <p className="error" style={{ whiteSpace: "pre-wrap" }}>{selectedJob.error}</p>
              <button className="btn small" onClick={() => startJobs([selectedJob.video], selectedJob.mode, selectedJob.instruction, selectedJob.planFile)}>Try again</button>
            </div>
          )}

          {!selectedActive && version?.summary && history && (
            <SummaryCard summary={version.summary}>
              <div className="row" style={{ flexWrap: "wrap", marginTop: 12 }}>
                <button className="btn small" disabled={!canUndo(history)} onClick={async () => { const h = await api.undo(history.video); setHistories((p) => ({ ...p, [h.video]: h })); }}>Undo AI edit</button>
                <button className="btn small" disabled={!canRedo(history)} onClick={async () => { const h = await api.redo(history.video); setHistories((p) => ({ ...p, [h.video]: h })); }}>Redo</button>
                <button className="btn small" onClick={() => { setInstruction(version.instruction); instructionRef.current?.focus(); }}>Redo with new instructions</button>
                <button className="btn small primary" onClick={() => setEditorPath(version.projectFile)} data-testid="open-editor" title="Fix anything by hand: cut, move, speed, volume, framing">Edit on timeline · Buksan sa timeline</button>
              </div>
              <div className="row" style={{ marginTop: 12 }}>
                <input type="text" aria-label="Change this edit" placeholder="Change this edit, e.g. “mas malaki pa ang captions”" value={followUp} onChange={(e) => setFollowUp(e.target.value)} />
                <button className="btn small" disabled={!followUp.trim()} onClick={() => { startJobs([history.video], "followup", followUp, version.planFile); setFollowUp(""); }}>Change</button>
              </div>
            </SummaryCard>
          )}
          {!selectedActive && history && history.versions.length > 0 && !version && (
            <div className="card">
              <p style={{ margin: 0 }}>The AI edit was undone: you are seeing the original video.</p>
              <button className="btn small" style={{ marginTop: 8 }} onClick={async () => { const h = await api.redo(history.video); setHistories((p) => ({ ...p, [h.video]: h })); }}>Redo AI edit</button>
            </div>
          )}
        </div>
      </aside>

      {genMounted && <GenerationDialog open={showGen} onClose={closeGen} onStatus={onGenStatus} onRunning={setGenRunning} />}
      {showSettings && <SettingsDialog settings={settings} onClose={() => setShowSettings(false)} onSave={async (patch) => { await saveSettings(patch); setShowSettings(false); }} />}
      {!settings.consentAccepted && <ConsentDialog onAccept={() => saveSettings({ consentAccepted: true })} />}
      {frame && (
        <FrameDialog
          previewNote="This is the true frame from the FFmpeg engine at the playhead: what the finished video will look like."
          imageUrl={frame.url}
          error={frame.error}
          onClose={() => setFrame(null)}
        />
      )}
    </div>
  );
}
