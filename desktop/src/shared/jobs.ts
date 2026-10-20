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
    case "warning":
      next.warnings = [...(job.warnings ?? []), event.message].slice(-20);
      next.log = [...job.log, `WARNING: ${event.message}`].slice(-LOG_LINES);
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

/** A job that can no longer finish: the app restarted under it, or its engine is gone (stalled). */
export function interruptJob(job: Job, reason: string): Job {
  const next: Job = { ...job, status: "interrupted", interruptedReason: reason, stage: undefined, percent: undefined };
  if (job.stage && !job.stagesDone.includes(job.stage)) next.stagesDone = [...job.stagesDone, job.stage];
  return next;
}

/** The request a job was made from (Retry makes a new job from it). */
export function requestOf(job: Job): JobRequest {
  const { video, photos, instruction, provider, auto, mode, planFile, maxGenMinutes, maxAiClips, graphics, preset, format,
    formatInputs, items, offsets, transcriptFile } = job;
  return { video, photos, instruction, provider, auto, mode, planFile, maxGenMinutes, maxAiClips, graphics, preset, format,
    formatInputs, items, offsets, transcriptFile };
}

/** Jobs saved by an earlier session: whatever was waiting or running can no longer finish, so it
 * comes back interrupted (with Retry); interrupted ones stay; finished ones are not brought back. */
export function restoreJobs(jobs: Job[]): Job[] {
  return jobs.filter((job) => ["running", "queued", "interrupted"].includes(job.status)).map((job) => {
    if (job.status === "interrupted") return job;
    const where = job.status === "running" ? `while "${job.stageLabel ?? "starting"}"` : "before it started";
    return interruptJob(job, `The app was closed or restarted ${where}. Nothing is running for it now: press Retry to edit it again.`);
  });
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
