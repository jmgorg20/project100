// The job queue: AI edits run one at a time (a batch of videos with the same instruction
// is simply several jobs). Each engine event updates the job and is sent to the window.
import { applyEvent, finishJob, newJob } from "../shared/jobs";
import type { EngineEvent, Job, JobRequest } from "../shared/types";
import type { RunHandle } from "./engine";

export interface QueueDeps {
  run(job: Job, onEvent: (event: EngineEvent) => void): RunHandle;
  onChange(job: Job): void;
  onFinished?(job: Job): void;
  makeId?(): string;
}

let counter = 0;

export class JobQueue {
  jobs: Job[] = [];
  private running: { id: string; handle: RunHandle } | null = null;
  private idleWaiters: (() => void)[] = [];

  constructor(private deps: QueueDeps) {}

  private makeId(): string {
    return this.deps.makeId ? this.deps.makeId() : `job${Date.now().toString(36)}${(counter++).toString(36)}`;
  }

  private update(job: Job): void {
    this.jobs = this.jobs.map((j) => (j.id === job.id ? job : j));
    this.deps.onChange(job);
  }

  get(id: string): Job | undefined {
    return this.jobs.find((j) => j.id === id);
  }

  add(requests: JobRequest[]): Job[] {
    const created = requests.map((r) => newJob(this.makeId(), r));
    this.jobs = [...this.jobs, ...created];
    created.forEach((j) => this.deps.onChange(j));
    this.pump();
    return created;
  }

  cancel(id: string): void {
    const job = this.get(id);
    if (!job) return;
    if (job.status === "queued") this.update({ ...job, status: "cancelled" });
    else if (this.running?.id === id) this.running.handle.cancel();
  }

  cancelAll(): void {
    this.jobs.filter((j) => j.status === "queued").forEach((j) => this.cancel(j.id));
    if (this.running) this.running.handle.cancel();
  }

  dismiss(id: string): void {
    const job = this.get(id);
    if (job && job.status === "review") this.update({ ...job, status: "dismissed" });
  }

  /** Resolves when nothing is running or queued (used by tests and on quit). */
  whenIdle(): Promise<void> {
    if (!this.running && !this.jobs.some((j) => j.status === "queued")) return Promise.resolve();
    return new Promise((resolve) => this.idleWaiters.push(resolve));
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
    let job: Job = { ...next, status: "running" };
    this.update(job);
    const handle = this.deps.run(job, (event) => {
      job = applyEvent(job, event);
      this.update(job);
    });
    this.running = { id: job.id, handle };
    handle.done.then((result) => {
      job = finishJob(job, result.code, result.cancelled, result.startError);
      this.running = null;
      this.update(job);
      this.deps.onFinished?.(job);
      this.pump();
    });
  }
}
