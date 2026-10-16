// How engine events change a job (pure, used by the main process; unit-tested).
import type { EngineEvent, Job, JobRequest, Version } from "./types";

const LOG_LINES = 200;

export function newJob(id: string, request: JobRequest, now = Date.now()): Job {
  return { ...request, id, status: "queued", stagesDone: [], log: [], createdAt: now };
}

export function applyEvent(job: Job, event: EngineEvent): Job {
  const next: Job = { ...job };
  switch (event.type) {
    case "stage":
      if (job.stage && job.stage !== event.stage && !job.stagesDone.includes(job.stage)) {
        next.stagesDone = [...job.stagesDone, job.stage];
      }
      next.stage = event.stage;
      next.stageLabel = event.label;
      next.percent = undefined;
      break;
    case "progress":
      next.percent = event.percent;
      break;
    case "transcript":
      next.transcriptWords = event.words;
      next.transcriptCached = event.cached;
      break;
    case "plan":
      next.plan = event.plan;
      next.planBaseline = event.baseline;
      next.planFallback = event.fallback;
      next.planReason = event.reason;
      next.planCached = event.cached;
      break;
    case "project":
      next.project = event.project;
      break;
    case "summary": {
      const { type: _type, ...summary } = event;
      next.summary = summary;
      break;
    }
    case "result":
      next.output = typeof event.output === "string" ? event.output : undefined;
      next.projectFile = typeof event.project === "string" ? event.project : undefined;
      next.planFileOut = typeof event.plan === "string" ? event.plan : undefined;
      break;
    case "error":
      next.error = event.message;
      break;
    case "log":
      next.log = [...job.log, event.message].slice(-LOG_LINES);
      break;
    default:
      break;
  }
  return next;
}

/** Final status once the engine process has exited. */
export function finishJob(job: Job, exitCode: number | null, cancelled: boolean, startError?: string): Job {
  const next: Job = { ...job, stage: undefined, percent: undefined };
  if (job.stage && !job.stagesDone.includes(job.stage)) next.stagesDone = [...job.stagesDone, job.stage];
  if (startError) return { ...next, status: "failed", error: startError };
  if (cancelled) return { ...next, status: "cancelled" };
  if (exitCode !== 0) {
    return { ...next, status: "failed", error: job.error || `The editor stopped unexpectedly (exit code ${exitCode}).` };
  }
  if (!job.auto && job.mode !== "apply") return { ...next, status: "review" };
  return { ...next, status: "done" };
}

/** The history entry for a finished, rendered job (or null if there is nothing to keep). */
export function versionFromJob(job: Job, now = Date.now()): Version | null {
  if (job.status !== "done" || !job.output || !job.projectFile || !job.planFileOut) return null;
  return {
    id: `v-${job.id}`,
    jobId: job.id,
    instruction: job.instruction,
    mode: job.mode,
    output: job.output,
    projectFile: job.projectFile,
    planFile: job.planFileOut,
    summary: job.summary,
    createdAt: now,
  };
}
