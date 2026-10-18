import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { setCaptionWords } from "@shared/captionEdit";
import { scenes, setSceneText } from "@shared/storyboard";
import type { Clip, Project, Word } from "@shared/types";
import { ApiError, call, get, post, type JobView } from "../api";
import { go, type SessionProps } from "../App";
import { duration, getLang, t, useLang } from "../i18n";

const FINAL = new Set(["succeeded", "failed", "cancelled"]);
const SIZES: [number, string][] = [[1920, "1080 × 1920 (Full HD)"], [1280, "720 × 1280"], [960, "540 × 960"]];
const QUALITIES: [string, string, string][] = [
  ["standard", "Standard (TikTok / Reels)", "Standard (TikTok / Reels)"],
  ["high", "High (bigger file)", "Mataas (mas malaking file)"],
  ["small", "Smaller file", "Mas maliit na file"],
  ["draft", "Quick draft", "Mabilis na draft"],
];

/** A caption's words from typed text, spread evenly over the caption's time. */
export function wordsFor(text: string, seconds: number): Word[] {
  const parts = text.split(/\s+/).filter(Boolean);
  const step = seconds / Math.max(1, parts.length);
  return parts.map((w, i) => ({ text: w, start: Math.round(i * step * 1e4) / 1e4, end: Math.round((i + 0.9) * step * 1e4) / 1e4 }));
}

function captionClips(p: Project): Clip[] {
  return p.tracks.filter((tr) => tr.kind === "caption").flatMap((tr) => tr.clips).sort((a, b) => a.start - b.start);
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function JobPage({ id }: { id: string } & SessionProps) {
  useLang();
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState("");
  const [project, setProject] = useState<Project | null>(null);
  const [edited, setEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const loadedAt = useRef(Date.now());

  const load = useCallback(async () => {
    try {
      const view = await get<JobView>(`/v1/jobs/${id}`);
      loadedAt.current = Date.now();
      setNow(Date.now());
      setJob(view);
    } catch (err) {
      setError((err as ApiError).message);
    }
  }, [id]);

  useEffect(() => {
    void load();
    const refresh = setInterval(() => void load(), 5 * 60_000);       // fresh links (they last 15 minutes)
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      clearInterval(refresh);
      clearInterval(tick);
    };
  }, [load]);

  // live progress while it runs (Server-Sent Events; the browser reconnects by itself)
  const running = job && !FINAL.has(job.status);
  useEffect(() => {
    if (!running) return;
    const events = new EventSource(`/v1/jobs/${id}/events`);
    events.addEventListener("status", (e) => {
      const s = JSON.parse((e as MessageEvent).data) as { status: JobView["status"]; progress: number | null; stage: string | null };
      setJob((j) => (j ? { ...j, ...s } : j));
      if (FINAL.has(s.status)) void load();
    });
    for (const kind of ["started", "progress", "succeeded", "failed", "cancelled", "retry"]) {
      events.addEventListener(kind, () => void load());
    }
    return () => events.close();
  }, [id, running, load]);

  // the editable project (storyboard and captions)
  const projectUrl = job?.outputs.find((o) => o.name === "project")?.preview_url;
  useEffect(() => {
    if (!projectUrl || project) return;
    fetch(projectUrl, { credentials: "same-origin" }).then((r) => (r.ok ? r.json() : null)).then((p) => p && setProject(p as Project))
      .catch(() => undefined);
  }, [projectUrl, project]);

  const sceneList = useMemo(() => {
    try {
      return project ? scenes(project) : [];
    } catch {
      return [];
    }
  }, [project]);

  const startRender = async (exportOpts: Record<string, unknown>) => {
    if (!project) return;
    setBusy(true);
    setError("");
    try {
      const r = await post<JobView>("/v1/jobs", { kind: "render", project, export: exportOpts, project_id: job?.project_id ?? undefined });
      go(`/jobs/${r.id}`);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const retry = async () => {
    if (!job) return;
    setBusy(true);
    try {
      const body = job.kind === "render" ? { kind: "render", project: job.params.project, export: job.params.export }
        : { kind: "polish", inputs: job.inputs, preset: job.params.preset,
            format: job.params.format ?? undefined, instruction: job.params.instruction || undefined, project_id: job.project_id ?? undefined };
      const r = await post<JobView>("/v1/jobs", body);
      go(`/jobs/${r.id}`);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  if (!job) return <section>{error ? <p className="error" role="alert">{error}</p> : <p className="muted">{t("loading")}</p>}</section>;
  const video = job.outputs.find((o) => o.name === "video");
  const pct = Math.round((job.progress ?? 0) * 100);                  // the service keeps 0..1
  const left = video ? video.expires_in_seconds - Math.floor((now - loadedAt.current) / 1000) : 0;
  const qc = job.result?.qc;
  const tl = getLang() === "tl";

  return (
    <section className="stack" data-testid="job" data-status={job.status}>
      <p><a href="#/jobs">← {t("navHistory")}</a></p>
      <h1>{job.status === "queued" ? t("queued") : job.status === "running" ? t("running", { pct }) : t(job.status)}</h1>
      {running && (
        <div className="progress">
          <div className="bar"><div style={{ width: `${job.status === "queued" ? 2 : Math.max(4, pct)}%` }} /></div>
          {job.stage && <small className="muted">{job.stage}</small>}
          <button className="ghost small" onClick={() => void post(`/v1/jobs/${id}/cancel`).then(load)}>{t("cancel")}</button>
        </div>
      )}
      {job.status === "failed" && (
        <div className="card">
          <p className="error">{job.error}</p>
          <button onClick={() => void retry()} disabled={busy}>{t("tryAgain")}</button>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}

      {job.status === "succeeded" && video && (
        <>
          <video className="preview" src={video.preview_url} controls playsInline preload="metadata" data-testid="preview" />
          <p className="ai-note">{t("aiNote")}</p>
          {qc && (
            <p className={qc.passed ? "ok" : "warn"} data-testid="qc">
              {qc.passed ? `✓ ${t("checksPassed")}` : `⚠ ${t("checksWarn")}: ${(qc.failed ?? []).join(", ")}`}
            </p>
          )}
          <div className="row wrap">
            <a className="button big" href={video.url} download data-testid="download">{t("download")}</a>
            <button className="ghost danger" onClick={() => {
              if (window.confirm(t("deleteConfirm"))) void call("DELETE", `/v1/jobs/${id}`).then(() => go("/jobs"));
            }}>{t("deleteNow")}</button>
          </div>
          <p className="muted" data-testid="expires">{t("expiresIn", { time: duration(Math.max(0, left)) })}</p>

          {project && sceneList.length > 0 && (
            <details className="card" open>
              <summary>{t("storyboard")}</summary>
              <ol className="scenes" data-testid="storyboard">
                {sceneList.map((s) => (
                  <li key={s.id} data-testid={`scene-${s.id}`}>
                    <span className="tag">{tl ? s.purpose_tl : s.purpose_label}</span>
                    <span className="muted">{clock(s.start)}–{clock(s.end)}</span>
                    <SceneText text={s.text} onSave={(text) => {
                      setProject(setSceneText(project, s.id, text));
                      setEdited(true);
                    }} />
                  </li>
                ))}
              </ol>
              <div className="timeline" aria-hidden>
                {sceneList.map((s) => (
                  <span key={s.id} style={{ flexGrow: Math.max(0.1, s.duration) }} title={s.text} />
                ))}
              </div>
            </details>
          )}

          {project && captionClips(project).length > 0 && (
            <details className="card" data-testid="captions">
              <summary>{t("editCaptions")}</summary>
              {captionClips(project).map((c) => (
                <CaptionLine key={c.id} clip={c} onSave={(text) => {
                  try {
                    setProject(setCaptionWords(project, c.id, wordsFor(text, c.duration)));
                    setEdited(true);
                  } catch (err) {
                    setError((err as Error).message);
                  }
                }} />
              ))}
            </details>
          )}

          {project && <ExportBox edited={edited} busy={busy} onStart={startRender} />}
        </>
      )}
    </section>
  );
}

function SceneText({ text, onSave }: { text: string; onSave: (text: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(text);
  if (!editing) return <p className="scene-text" onClick={() => setEditing(true)}>{text || "—"}</p>;
  return (
    <span className="row">
      <input value={value} onChange={(e) => setValue(e.target.value)} aria-label={t("captions")} />
      <button className="small" onClick={() => {
        onSave(value);
        setEditing(false);
      }}>{t("save")}</button>
    </span>
  );
}

function CaptionLine({ clip, onSave }: { clip: Clip; onSave: (text: string) => void }) {
  const original = (clip.words ?? []).map((w) => w.text).join(" ");
  const [value, setValue] = useState(original);
  return (
    <div className="caption-line" data-testid={`caption-${clip.id}`}>
      <span className="muted">{clock(clip.start)}</span>
      <input value={value} onChange={(e) => setValue(e.target.value)} aria-label={`${t("captions")} ${clock(clip.start)}`}
        onBlur={() => value.trim() && value !== original && onSave(value)} />
    </div>
  );
}

function ExportBox({ edited, busy, onStart }: { edited: boolean; busy: boolean; onStart: (o: Record<string, unknown>) => void }) {
  const [height, setHeight] = useState(1920);
  const [quality, setQuality] = useState("standard");
  const [fps, setFps] = useState(30);
  const tl = getLang() === "tl";
  return (
    <div className="card" data-testid="export">
      <h2>{t("exportTitle")}</h2>
      <div className="row wrap">
        <label>{t("exportSize")}<select value={height} onChange={(e) => setHeight(Number(e.target.value))}>
          {SIZES.map(([h, label]) => <option key={h} value={h}>{label}</option>)}</select></label>
        <label>{t("exportQuality")}<select value={quality} onChange={(e) => setQuality(e.target.value)}>
          {QUALITIES.map(([id, en, tlLabel]) => <option key={id} value={id}>{tl ? tlLabel : en}</option>)}</select></label>
        <label>{t("exportFps")}<select value={fps} onChange={(e) => setFps(Number(e.target.value))}>
          {[24, 25, 30, 50, 60].map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
      </div>
      <button className="wide" disabled={busy} data-testid="render" onClick={() => onStart({ height, quality, fps })}>
        {edited ? t("saveRender") : t("exportStart")}
      </button>
    </div>
  );
}
