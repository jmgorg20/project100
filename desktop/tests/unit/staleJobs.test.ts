// A job can never stay "running" with nothing behind it (a real Windows run kept showing "Planning the
// editorial scenes..." with Cancel, and "Edit with AI" greyed out, after a restart): a restart brings
// it back interrupted with Retry, Cancel always clears it, a watchdog ends a stalled one, and every
// change of status is written to the job log.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import type { RunHandle, RunResult } from "../../src/main/engine";
import { JobLog, JobStore } from "../../src/main/jobStore";
import { JobQueue } from "../../src/main/queue";
import { newJob } from "../../src/shared/jobs";
import type { EngineEvent, Job, JobRequest } from "../../src/shared/types";

const request = (video: string): JobRequest => ({ video, photos: [], instruction: "premium", provider: "groq", auto: true, mode: "new" });

function tmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "stale-"));
}

/** A stand-in engine run: it finishes when told to, says whether its process is alive, and when it last wrote. */
function fakeRun(opts: { alive?: () => boolean; lastActivity?: () => number } = {}) {
  let finish!: (r: RunResult) => void;
  let emit!: (e: EngineEvent) => void;
  const cancels: number[] = [];
  const handle: RunHandle = {
    done: new Promise((resolve) => (finish = resolve)),
    cancel: () => cancels.push(Date.now()),
    alive: opts.alive ?? (() => true),
    lastActivity: opts.lastActivity ?? (() => Date.now()),
  };
  return { handle, finish: (r: RunResult) => finish(r), emit: (e: EngineEvent) => emit(e), setEmit: (f: (e: EngineEvent) => void) => (emit = f), cancels };
}

function queueWith(runs: ReturnType<typeof fakeRun>[], extra: Partial<ConstructorParameters<typeof JobQueue>[0]> = {}) {
  const started: string[] = [];
  let n = 0;
  let ids = 0;
  const q = new JobQueue({
    run: (job, onEvent) => {
      started.push(job.id);
      const r = runs[n++];
      r.setEmit(onEvent);
      return r.handle;
    },
    onChange: () => {},
    makeId: () => `j${++ids}`,
    watchMs: 0,
    ...extra,
  });
  return { q, started };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("restart with a job left running", () => {
  it("comes back interrupted with Retry, is logged, and Retry edits it again", async () => {
    const dir = tmpDir();
    const file = path.join(dir, "jobs.json");
    // what the earlier session saved: one job "running" at the editorial step, one waiting, one done
    const running = { ...newJob("old1", request("C:/Videos/test 2.mp4")), status: "running" as const, stage: "graphics", stageLabel: "Planning the editorial scenes" };
    const waiting = newJob("old2", request("C:/Videos/test 3.mp4"));
    const done = { ...newJob("old3", request("C:/Videos/done.mp4")), status: "done" as const };
    fs.writeFileSync(file, JSON.stringify({ version: 1, jobs: [running, waiting, done] }));

    const store = new JobStore(file);
    const log = new JobLog(path.join(dir, "logs", "jobs.log"));
    const previous = store.load();
    expect(previous.map((j) => [j.id, j.status])).toEqual([["old1", "interrupted"], ["old2", "interrupted"]]);
    expect(previous[0].interruptedReason).toContain('while "Planning the editorial scenes"');
    expect(previous[0].stagesDone).toContain("graphics");

    const run = fakeRun();
    const { q, started } = queueWith([run], { store, onTransition: (job, from, to, why) => log.write(job, from, to, why) });
    q.restore(previous);
    expect(started).toEqual([]);                                      // nothing starts by itself
    expect(q.jobs.every((j) => j.status !== "running")).toBe(true);
    const saved = JSON.parse(fs.readFileSync(file, "utf-8")).jobs as Job[];
    expect(saved.find((j) => j.id === "old1")!.status).toBe("interrupted");

    const [again] = q.retry("old1");
    expect(q.get("old1")!.status).toBe("dismissed");
    expect(again.video).toBe("C:/Videos/test 2.mp4");
    expect(started).toEqual([again.id]);
    run.finish({ code: 0, cancelled: false });
    await flush();
    expect(q.get(again.id)!.status).toBe("done");

    const text = fs.readFileSync(log.file, "utf-8");
    expect(text).toMatch(/old1 "test 2\.mp4": running -> interrupted .*found on start/);
    expect(text).toMatch(/old1 "test 2\.mp4": interrupted -> dismissed .*retried/);
    expect(text).toMatch(new RegExp(`${again.id} "test 2\\.mp4": queued -> running`));
    expect(text).toMatch(new RegExp(`${again.id} "test 2\\.mp4": running -> done`));
  });

  it("a broken or missing jobs.json starts empty", () => {
    const dir = tmpDir();
    fs.writeFileSync(path.join(dir, "jobs.json"), "{not json");
    expect(new JobStore(path.join(dir, "jobs.json")).load()).toEqual([]);
    expect(new JobStore(path.join(dir, "none.json")).load()).toEqual([]);
  });
});

describe("Cancel always clears the job", () => {
  it("at once when its engine is already gone (and the next job starts)", async () => {
    const dead = fakeRun({ alive: () => false });          // never finishes: the old Windows state
    const next = fakeRun();
    const { q, started } = queueWith([dead, next]);
    const [a, b] = q.add([request("C:/a.mp4"), request("C:/b.mp4")]);
    q.cancel(a.id);
    expect(q.get(a.id)!.status).toBe("cancelled");
    expect(dead.cancels).toEqual([]);                       // nothing to ask: it is gone
    expect(started).toEqual([a.id, b.id]);
    dead.finish({ code: 0, cancelled: false });             // a late exit changes nothing
    await flush();
    expect(q.get(a.id)!.status).toBe("cancelled");
  });

  it("after the grace period when the engine ignores the cancel", async () => {
    const stubborn = fakeRun();
    const { q } = queueWith([stubborn], { cancelGraceMs: 50 });
    const [a] = q.add([request("C:/a.mp4")]);
    q.cancel(a.id);
    expect(stubborn.cancels.length).toBe(1);
    expect(q.get(a.id)!.status).toBe("running");
    await new Promise((r) => setTimeout(r, 80));
    expect(q.get(a.id)!.status).toBe("cancelled");
  });

  it("the ✕ clears an interrupted, failed or cancelled job, never a waiting or running one", () => {
    const { q } = queueWith([fakeRun()]);
    const [a] = q.add([request("C:/a.mp4")]);
    q.dismiss(a.id);
    expect(q.get(a.id)!.status).toBe("running");
    q.restore([{ ...newJob("x", request("C:/x.mp4")), status: "interrupted", interruptedReason: "The app was closed" }]);
    q.dismiss("x");
    expect(q.get("x")!.status).toBe("dismissed");
  });
});

describe("the watchdog", () => {
  it("ends a job whose engine is gone and quiet for 30 s as stalled, and the next one starts", () => {
    let now = 1_000_000;
    const gone = fakeRun({ alive: () => false, lastActivity: () => 1_000_000 });
    const next = fakeRun();
    const { q, started } = queueWith([gone, next], { now: () => now, logActivity: () => 999_000 });
    const [a, b] = q.add([request("C:/a.mp4"), request("C:/b.mp4")]);
    now += 20_000;
    q.checkStalled();
    expect(q.get(a.id)!.status).toBe("running");            // not yet 30 s
    now += 11_000;
    q.checkStalled();
    expect(q.get(a.id)!.status).toBe("interrupted");
    expect(q.get(a.id)!.interruptedReason).toMatch(/Stalled: the engine stopped .* 31 s/);
    expect(started).toEqual([a.id, b.id]);
  });

  it("leaves a quiet job alone while its engine process is alive (e.g. waiting for the AI)", () => {
    let now = 0;
    const quiet = fakeRun({ alive: () => true, lastActivity: () => 0 });
    const { q } = queueWith([quiet], { now: () => now });
    const [a] = q.add([request("C:/a.mp4")]);
    now = 600_000;
    q.checkStalled();
    expect(q.get(a.id)!.status).toBe("running");
  });

  it("counts writing to the engine's logs as activity", () => {
    let now = 0;
    const gone = fakeRun({ alive: () => false, lastActivity: () => 0 });
    let logs = 0;
    const { q } = queueWith([gone], { now: () => now, logActivity: () => logs });
    const [a] = q.add([request("C:/a.mp4")]);
    now = 40_000;
    logs = 25_000;
    q.checkStalled();
    expect(q.get(a.id)!.status).toBe("running");
    now = 60_000;
    q.checkStalled();
    expect(q.get(a.id)!.status).toBe("interrupted");
  });

  it("ignores what an ended job's engine says afterwards", () => {
    const gone = fakeRun({ alive: () => false, lastActivity: () => 0 });
    const { q } = queueWith([gone], { now: () => 100_000 });
    const [a] = q.add([request("C:/a.mp4")]);
    q.checkStalled();
    gone.emit({ type: "stage", stage: "render", label: "Rendering" });
    expect(q.get(a.id)!.status).toBe("interrupted");
    expect(q.get(a.id)!.stageLabel).not.toBe("Rendering");
  });
});
