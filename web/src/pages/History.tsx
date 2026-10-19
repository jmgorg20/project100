import { useCallback, useEffect, useState } from "react";
import { ApiError, get, type JobView, type Project } from "../api";
import type { SessionProps } from "../App";
import { t, useLang } from "../i18n";

const ICON: Record<JobView["status"], string> = { queued: "…", running: "⟳", succeeded: "✓", failed: "✕", cancelled: "–" };

export function History(_: SessionProps) {
  useLang();
  const [jobs, setJobs] = useState<JobView[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async (before?: number) => {
    const q = new URLSearchParams({ limit: "20" });
    if (before) q.set("before", String(before));
    if (projectId) q.set("project_id", projectId);
    try {
      const r = await get<{ jobs: JobView[]; next_before: number | null }>(`/v1/jobs?${q}`);
      setJobs((old) => (before ? [...old, ...r.jobs] : r.jobs));
      setNext(r.next_before);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setLoaded(true);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    get<{ projects: Project[] }>("/v1/projects").then((r) => setProjects(r.projects)).catch(() => undefined);
  }, []);

  return (
    <section className="stack">
      <h1>{t("navHistory")}</h1>
      {projects.length > 0 && (
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label={t("project")}>
          <option value="">{t("allProjects")}</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {loaded && !jobs.length && <p className="muted">{t("historyEmpty")}</p>}
      <ul className="jobs" data-testid="history">
        {jobs.map((j) => (
          <li key={j.id}>
            <a href={`#/jobs/${j.id}`} className={`job ${j.status}`}>
              <span className="icon" aria-hidden>{ICON[j.status]}</span>
              <span className="grow">
                <strong>{j.kind === "render" ? t("exportTitle") : (j.params.preset ?? "auto").replace(/_/g, " ")}</strong>
                <small className="muted">{new Date(j.created_at * 1000).toLocaleString()} · {t(j.status === "queued" ? "queued" : j.status === "running" ? "running" : j.status, { pct: Math.round((j.progress ?? 0) * 100) })}</small>
              </span>
            </a>
          </li>
        ))}
      </ul>
      {next && <button className="ghost" onClick={() => void load(next)}>{t("loadMore")}</button>}
    </section>
  );
}
