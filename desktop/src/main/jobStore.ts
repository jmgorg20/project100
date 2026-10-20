// Jobs survive a restart (a real Windows run kept showing "Planning the editorial scenes..." with
// nothing running): the queue is saved to jobs.json, and a job that was waiting or running when the
// app stopped comes back as "interrupted" with a Retry. Every change of a job's status is written to
// jobs.log (work/logs/jobs.log next to the engine's own logs).
import * as fs from "node:fs";
import * as path from "node:path";
import { restoreJobs } from "../shared/jobs";
import type { Job } from "../shared/types";

const KEEP = 50;            // the newest jobs kept in jobs.json
const KEEP_LOG = 40;        // log lines kept per job

export class JobStore {
  constructor(private file: string) {}

  /** The previous session's jobs, the unfinished ones marked interrupted. */
  load(): Job[] {
    try {
      const data = JSON.parse(fs.readFileSync(this.file, "utf-8"));
      return Array.isArray(data?.jobs) ? restoreJobs(data.jobs as Job[]) : [];
    } catch {
      return [];
    }
  }

  save(jobs: Job[]): void {
    // small: the newest jobs, without their project (it is in the project file) and long logs
    const light = jobs.slice(-KEEP).map(({ project: _project, ...job }) => ({ ...job, log: job.log.slice(-KEEP_LOG) }));
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      const tmp = `${this.file}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify({ version: 1, savedAt: new Date().toISOString(), jobs: light }), "utf-8");
      fs.renameSync(tmp, this.file);
    } catch {
      // a full disk must not stop the edit; the next save tries again
    }
  }
}

export class JobLog {
  constructor(readonly file: string) {}

  write(job: Job, from: string, to: string, why = ""): void {
    const line = `${new Date().toISOString()} ${job.id} "${path.basename(job.video)}": ${from} -> ${to}` +
      (job.stageLabel && to !== "running" ? ` (at "${job.stageLabel}")` : "") + (why ? ` - ${why}` : "") + "\n";
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      fs.appendFileSync(this.file, line, "utf-8");
    } catch {
      // logging must never stop a job
    }
  }
}
