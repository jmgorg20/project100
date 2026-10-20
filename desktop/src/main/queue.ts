// The job queue: AI edits run one at a time (a batch of videos with the same instruction
// is simply several jobs). Each engine event updates the job and is sent to the window.
//
// A job can never stay "running" with nothing behind it (a real Windows run kept showing
// "Planning the editorial scenes..." after its engine was gone):
// - the queue is saved (deps.store) and a job left running or waiting by an earlier session comes
//   back as "interrupted" with Retry (restore)
// - Cancel always clears a job: when its engine is gone, or does not stop within the grace
//   period, the job is ended at once
// - a watchdog marks a running job interrupted ("stalled") when its engine process is gone and
//   nothing was written (engine output or logs) for 30 s
// - every status change is reported (deps.onTransition: the job log)
import { applyEvent, finishJob, interruptJob, newJob, requestOf } from "../shared/jobs";
import type { EngineEvent, Job, JobRequest, JobStatus } from "../shared/types";
import type { RunHandle } from "./engine";

export interface QueueDeps {
  run(job: Job, onEvent: (event: EngineEvent) => void): RunHandle;
  onChange(job: Job): void;
  onFinished?(job: Job): void;
  makeId?(): string;
  /** Saves the jobs (so a restart knows what was running). */
  store?: { save(jobs: Job[]): void };
  /** Each change of a job's status (the job log). */
  onTransition?(job: Job, from: JobStatus | "new", to: JobStatus, why?: string): void;
  /** When anything was last written to the engine's logs (ms), for the watchdog. */
  logActivity?(): number;
  now?(): number;
  /** No engine process and no activity for this long: stalled (default 30 s). */
  stallMs?: number;
  /** How often the watchdog looks (default 5 s; 0 = never by itself, tests call checkStalled). */
  watchMs?: number;
  /** After Cancel, the job is ended anyway if the engine has not stopped after this long. */
  cancelGraceMs?: number;
}

let counter = 0;
export const STALL_MS = 30_000;

export class JobQueue {
  jobs: Job[] = [];
  private running: { id: string; handle: RunHandle } | null = null;
  private idleWaiters: (() => void)[] = [];
  private watch: ReturnType<typeof setInterval> | null = null;

  constructor(private deps: QueueDeps) {
    const every = deps.watchMs ?? 5_000;
    if (every > 0) {
      this.watch = setInterval(() => this.checkStalled(), every);
      (this.watch as { unref?: () => void }).unref?.();
    }
  }

  private now(): number {
    return this.deps.now ? this.deps.now() : Date.now();
  }

  private makeId(): string {
    return this.deps.makeId ? this.deps.makeId() : `job${Date.now().toString(36)}${(counter++).toString(36)}`;
  }

  private update(job: Job, why?: string): void {
    const before = this.get(job.id);
    this.jobs = this.jobs.map((j) => (j.id === job.id ? job : j));
    if (before && before.status !== job.status) this.deps.onTransition?.(job, before.status, job.status, why);
    // saved on every change of status or step (not on every progress tick)
    if (!before || before.status !== job.status || before.stage !== job.stage) this.deps.store?.save(this.jobs);
    this.deps.onChange(job);
  }

  get(id: string): Job | undefined {
    return this.jobs.find((j) => j.id === id);
  }

  /** The jobs an earlier session left (already marked interrupted by the store). */
  restore(jobs: Job[]): void {
    this.jobs = [...jobs, ...this.jobs.filter((j) => !jobs.some((r) => r.id === j.id))];
    jobs.filter((j) => j.status === "interrupted" && j.interruptedReason?.startsWith("The app was closed"))
      .forEach((j) => this.deps.onTransition?.(j, "running", "interrupted", "found on start: " + j.interruptedReason));
    this.deps.store?.save(this.jobs);
  }

  add(requests: JobRequest[]): Job[] {
    const created = requests.map((r) => newJob(this.makeId(), r, this.now()));
    this.jobs = [...this.jobs, ...created];
    created.forEach((j) => {
      this.deps.onTransition?.(j, "new", "queued");
      this.deps.onChange(j);
    });
    this.deps.store?.save(this.jobs);
    this.pump();
    return created;
  }

  /** Retry an interrupted / failed / cancelled job: a new job with the same request. */
  retry(id: string): Job[] {
    const job = this.get(id);
    if (!job || ["queued", "running"].includes(job.status)) return [];
    if (job.status !== "dismissed") this.update({ ...job, status: "dismissed" }, "retried");
    return this.add([requestOf(job)]);
  }

  cancel(id: string): void {
    const job = this.get(id);
    if (!job) return;
    if (job.status === "queued") {
      this.update({ ...job, status: "cancelled" });
      return;
    }
    if (job.status !== "running") return;
    const run = this.running?.id === id ? this.running : null;
    if (!run || run.handle.alive?.() === false) {
      // nothing is running for it (its engine is gone, or it was left by an earlier session)
      this.end(id, "cancelled", run ? "cancelled; its engine had already stopped" : "cancelled; nothing was running for it");
      return;
    }
    run.handle.cancel();
    // if the engine does not stop by itself, the job is ended anyway (the engine runner kills it)
    const grace = this.deps.cancelGraceMs ?? 100_000;
    const timer = setTimeout(() => {
      if (this.get(id)?.status === "running") this.end(id, "cancelled", "cancelled; the engine did not stop in time");
    }, grace);
    (timer as { unref?: () => void }).unref?.();
  }

  cancelAll(): void {
    this.jobs.filter((j) => j.status === "queued").forEach((j) => this.cancel(j.id));
    if (this.running) this.cancel(this.running.id);
  }

  /** Clear a job from the list (the ✕): any job that is not waiting or running. */
  dismiss(id: string): void {
    const job = this.get(id);
    if (job && !["queued", "running", "dismissed"].includes(job.status)) this.update({ ...job, status: "dismissed" });
  }

  /** Watchdog: a running job whose engine process is gone, with no output and no log activity for
   * 30 s, is stalled: it is ended as interrupted (Retry), and the next job starts. */
  checkStalled(): void {
    const run = this.running;
    if (!run) {
      // a job marked running with nothing behind it (never left like that, but never trusted either)
      this.jobs.filter((j) => j.status === "running").forEach((j) => this.end(j.id, "interrupted",
        "Stalled: nothing was running for it. Press Retry to edit it again."));
      return;
    }
    if (run.handle.alive?.() !== false) return;
    const quiet = this.now() - Math.max(run.handle.lastActivity?.() ?? 0, this.deps.logActivity?.() ?? 0);
    if (quiet < (this.deps.stallMs ?? STALL_MS)) return;
    this.end(run.id, "interrupted", `Stalled: the engine stopped without finishing (no engine process and nothing written for ${Math.round(quiet / 1000)} s). Press Retry to edit it again.`);
  }

  /** End a running job now, whatever its engine does (it is no longer waited for). */
  private end(id: string, status: "cancelled" | "interrupted", why: string): void {
    const job = this.get(id);
    if (!job) return;
    const ended = status === "cancelled" ? finishJob(job, null, true) : interruptJob(job, why);
    if (this.running?.id === id) this.running = null;
    this.update(ended, why);
    this.pump();
  }

  /** Resolves when nothing is running or queued (used by tests and on quit). */
  whenIdle(): Promise<void> {
    if (!this.running && !this.jobs.some((j) => j.status === "queued")) return Promise.resolve();
    return new Promise((resolve) => this.idleWaiters.push(resolve));
  }

  stop(): void {
    if (this.watch) clearInterval(this.watch);
    this.watch = null;
  }

  private pump(): void {
    if (this.running) return;
    const next = this.jobs.find((j) => j.status === "queued");
    if (!next) {
      const waiters = this.idleWaiters;
      this.idleWaiters = [];
      waiters.forEach((resolve) => resolve());
      return;
    }
    let job: Job = { ...next, status: "running", lastActivity: this.now() };
    this.update(job);
    const handle = this.deps.run(job, (event) => {
      if (this.get(job.id)?.status !== "running") return;      // ended already (cancel, watchdog)
      job = applyEvent({ ...job, lastActivity: this.now() }, event);
      this.update(job);
    });
    this.running = { id: job.id, handle };
    handle.done.then((result) => {
      const current = this.get(job.id);
      if (this.running?.id === job.id) this.running = null;
      if (current?.status === "running") {
        job = finishJob(current, result.code, result.cancelled, result.startError);
        this.update(job, result.startError ?? (result.cancelled ? "cancelled" : `engine exit code ${result.code}`));
        this.deps.onFinished?.(job);
      }
      this.pump();
    });
  }
}
