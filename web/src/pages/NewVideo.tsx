import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, call, get, post, type Catalog, type JobView, type Me, type Project, type UploadView } from "../api";
import { go, type SessionProps } from "../App";
import { getLang, pick, t, useLang } from "../i18n";
import { uploadFile } from "../upload";

interface Info {
  limits: { max_upload_mb: number; max_duration_seconds: number };
}

/** A short fingerprint of a text (the same request sent twice starts one job, not two). */
function hash(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (Math.imul(31, h) + text.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

type Phase = { kind: "idle" } | { kind: "uploading"; name: string; pct: number } | { kind: "paused" } | { kind: "checking" };

export function NewVideo(_: SessionProps) {
  useLang();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [info, setInfo] = useState<Info | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [video, setVideo] = useState<File | null>(null);
  const [photos, setPhotos] = useState<File[]>([]);
  const [preset, setPreset] = useState("viral_tiktok");
  const [format, setFormat] = useState("auto");
  const [instruction, setInstruction] = useState("");
  const [projectId, setProjectId] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState("");
  const stop = useRef<AbortController | null>(null);

  useEffect(() => {
    get<Catalog>("/v1/catalog").then((c) => {
      setCatalog(c);
      if (c.presets.length && !c.presets.some((p) => p.id === "viral_tiktok")) setPreset(c.presets[0].id);
    }).catch((err) => setError((err as ApiError).message));
    get<Me>("/v1/me").then(setMe).catch(() => undefined);
    get<Info>("/v1/info").then(setInfo).catch(() => undefined);
    get<{ projects: Project[] }>("/v1/projects").then((r) => setProjects(r.projects)).catch(() => undefined);
  }, []);

  const newProject = async () => {
    const name = window.prompt(t("projectName"));
    if (!name?.trim()) return;
    try {
      const p = await post<Project>("/v1/projects", { name });
      setProjects([p, ...projects]);
      setProjectId(p.id);
    } catch (err) {
      setError((err as ApiError).message);
    }
  };

  const send = async (file: File, signal: AbortSignal): Promise<UploadView> =>
    uploadFile(file, { projectId: projectId || null, signal,
      onProgress: (sent, total) => setPhase({ kind: "uploading", name: file.name, pct: Math.floor((sent / total) * 100) }) });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!video) return;
    setError("");
    const ctl = new AbortController();
    stop.current = ctl;
    try {
      const main = await send(video, ctl.signal);
      const photoIds: string[] = [];
      for (const p of photos) photoIds.push((await send(p, ctl.signal)).id);
      setPhase({ kind: "checking" });
      const inputs: Record<string, string[]> = { main: [main.id] };
      if (photoIds.length) inputs.photos = photoIds;
      const job = await call<JobView>("POST", "/v1/jobs", {
        kind: "polish", inputs, preset, format: format === "auto" ? undefined : format,
        instruction: instruction.trim() || undefined, project_id: projectId || undefined,
      }, { headers: { "Idempotency-Key": `web-${main.id}-${preset}-${format}-${hash(instruction)}-${projectId}` } });
      go(`/jobs/${job.id}`);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        setPhase({ kind: "paused" });
        return;
      }
      setError((err as ApiError).message ?? t("tryAgain"));
      setPhase({ kind: "idle" });
    }
  };

  const tl = getLang() === "tl";
  const left = me ? Math.max(0, me.client.monthly_minutes - me.usage.input_minutes) : null;
  const busy = phase.kind === "uploading" || phase.kind === "checking";
  const chosen = catalog?.presets.find((p) => p.id === preset);
  return (
    <section>
      <h1>{t("newTitle")}</h1>
      {me && left !== null && <p className="muted" data-testid="minutes-left">{t("minutesLeft", { left: left.toFixed(0), total: me.client.monthly_minutes.toFixed(0) })}</p>}
      <form onSubmit={submit} className="stack">
        <label className="file">
          <span className="label">{t("pickVideo")}</span>
          <input type="file" accept="video/*" required disabled={busy} data-testid="pick-video"
            onChange={(e) => setVideo(e.target.files?.[0] ?? null)} />
          {video && <span className="chosen">{video.name} · {(video.size / 1048576).toFixed(1)} MB</span>}
          {info && <small className="muted">{t("pickHelp", { mb: info.limits.max_upload_mb, min: Math.floor(info.limits.max_duration_seconds / 60) })}</small>}
        </label>
        <label className="file">
          <span className="label">{t("addPhotos")}</span>
          <input type="file" accept="image/*" multiple disabled={busy} onChange={(e) => setPhotos(Array.from(e.target.files ?? []).slice(0, 10))} />
          {photos.length > 0 && <span className="chosen">{photos.length} 🖼</span>}
        </label>

        <fieldset>
          <legend>{t("style")}</legend>
          <div className="presets" role="radiogroup">
            {catalog?.presets.map((p) => (
              <button type="button" key={p.id} role="radio" aria-checked={preset === p.id} data-testid={`preset-${p.id}`}
                className={preset === p.id ? "preset on" : "preset"} onClick={() => setPreset(p.id)} disabled={busy}>
                <strong>{pick(p)}</strong>
                <small>{tl ? p.about_tl : p.about}</small>
              </button>
            ))}
          </div>
        </fieldset>

        <label>{t("formatLabel")}
          <select value={format} onChange={(e) => setFormat(e.target.value)} disabled={busy} data-testid="format">
            <option value="auto">{t("formatAuto")}{chosen?.format ? ` · ${pick(catalog!.formats.find((f) => f.id === chosen.format) ?? { name: chosen.format })}` : ""}</option>
            {catalog?.formats.filter((f) => f.inputs.every((i) => !i.required || i.role === "main")).map((f) => (
              <option key={f.id} value={f.id}>{pick(f)}</option>
            ))}
          </select>
        </label>

        <label>{t("instruction")}
          <textarea rows={3} maxLength={2000} value={instruction} placeholder={t("instructionHint")} disabled={busy}
            onChange={(e) => setInstruction(e.target.value)} data-testid="instruction" />
        </label>

        <div className="row">
          <label className="grow">{t("project")}
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)} disabled={busy}>
              <option value="">{t("noProject")}</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <button type="button" className="ghost small" onClick={() => void newProject()} disabled={busy}>{t("newProject")}</button>
        </div>

        {error && <p className="error" role="alert">{error}</p>}
        {phase.kind === "uploading" && (
          <div className="progress" data-testid="upload-progress">
            <div className="bar"><div style={{ width: `${phase.pct}%` }} /></div>
            <span>{t("uploading", { pct: phase.pct })}</span>
            <button type="button" className="ghost small" onClick={() => stop.current?.abort()}>{t("pause")}</button>
          </div>
        )}
        {phase.kind === "paused" && <p className="muted" role="status">{t("resumeHint")}</p>}
        {phase.kind === "checking" && <p className="muted" role="status">{t("checking")}</p>}
        <button className="wide big" disabled={!video || busy} data-testid="start">
          {phase.kind === "paused" ? t("resume") : t("start")}
        </button>
      </form>
    </section>
  );
}
