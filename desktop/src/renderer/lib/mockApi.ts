// A stand-in for the Electron bridge, used only by the UI tests (?mock=1). It replays an
// AI edit that the real engine made (fixtures written by tests/ui/make_fixtures.py), with the
// same events in the same order, so the window can be tested without Electron or API keys.
import type { AppApi, EstimateResult } from "../../shared/api";
import { addVersion, emptyHistory, redo, undo } from "../../shared/history";
import { applyEvent, finishJob, newJob, versionFromJob } from "../../shared/jobs";
import type { EngineEvent, Job, JobRequest, KeysStatus, Plan, Project, Settings, Summary, Track, VideoHistory } from "../../shared/types";

interface Fixture {
  project: Project;
  plan: Plan;
  baseline: Plan;
  summary: Summary;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createMockApi(): AppApi {
  const params = new URLSearchParams(window.location.search);
  const speed = Number(params.get("speed") ?? "1");
  let settings: Settings = {
    pythonPath: "python", engineDir: "C:/AutoEditor", outputDir: "C:/AutoEditor/output", provider: "groq",
    groqModel: "openai/gpt-oss-120b", anthropicModel: "claude-opus-5-5", transcribeWith: "groq", autoMode: true,
    consentAccepted: params.has("consent"),
  };
  let keys: KeysStatus = { encryptionAvailable: true, groq: { set: true, hint: "••••a1b2" }, anthropic: { set: false, hint: "" } };
  const jobs = new Map<string, Job>();
  const histories = new Map<string, VideoHistory>();
  const jobListeners = new Set<(job: Job) => void>();
  const historyListeners = new Set<(h: VideoHistory) => void>();
  let fixture: Promise<Fixture> | null = null;
  let queue: Promise<void> = Promise.resolve();
  let counter = 0;

  const load = () =>
    (fixture ??= Promise.all([
      fetch("/fixtures/demo.project.json").then((r) => r.json()),
      fetch("/fixtures/demo.plan.json").then((r) => r.json()),
    ]).then(([project, plan]) => ({ project, plan: plan.plan, baseline: plan.baseline, summary: plan.summary })));

  const update = (job: Job) => {
    jobs.set(job.id, job);
    jobListeners.forEach((l) => l(job));
  };

  async function run(id: string) {
    const f = await load();
    if (jobs.get(id)?.status !== "queued") return; // cancelled while waiting
    let job: Job = { ...jobs.get(id)!, status: "running" };
    update(job);
    const stopped = () => jobs.get(id)?.status === "cancelled";
    const emit = async (event: EngineEvent, ms = 120) => {
      await wait(ms / speed);
      if (stopped()) throw new Error("cancelled");
      job = applyEvent(job, event);
      update(job);
    };
    const fail = job.instruction.includes("FAIL");
    const plan = f.plan;
    await emit({ type: "stage", stage: "transcript", label: "Listening to your video" });
    await emit({ type: "transcript", words: 13, cached: job.mode !== "new", text: "Kumusta kayo mga kaibigan!" });
    await emit({ type: "stage", stage: "plan", label: "Planning the edit" });
    await emit({
      type: "plan", plan: fail ? f.baseline : plan, baseline: f.baseline, fallback: fail, cached: false, given: job.mode === "apply",
      reason: fail ? "The AI plan failed the checks twice (first problem: plan.style: 'comic' is not one of the styles), so this is the preset edit instead." : "",
      model: "openai/gpt-oss-120b", cost: 0.0016, attempts: [],
    }, 400);
    for (const stage of ["cuts", "zooms", "captions", "photos"]) {
      const kinds: Record<string, string[]> = { cuts: ["video"], zooms: ["video", "effect"], captions: ["video", "effect", "caption"], photos: ["video", "effect", "caption", "overlay", "audio"] };
      const view: Project = { ...f.project, tracks: f.project.tracks.map((t: Track) => (kinds[stage].includes(t.kind) ? t : { ...t, clips: [] })) };
      await emit({ type: "stage", stage, label: stage });
      await emit({ type: "project", stage, project: view }, 250);
    }
    const summary: Summary = fail
      ? { ...f.summary, fallback: true, headline: "Heads up: The AI plan failed the checks twice, so this is the preset edit instead." }
      : f.summary;
    await emit({ type: "summary", ...summary });
    if (job.auto || job.mode === "apply") {
      await emit({ type: "stage", stage: "render", label: "rendering the video" });
      for (const p of [10, 35, 60, 85, 100]) await emit({ type: "progress", stage: "render", percent: p }, 150);
      await emit({ type: "result", output: "C:/Videos/demo_talk_ai.mp4", project: "C:/Videos/demo_talk_ai.project.json", plan: "C:/Videos/demo_talk_ai.plan.json" });
    } else {
      await emit({ type: "result", output: null, project: "C:/Videos/demo_talk_ai.project.json", plan: "C:/Videos/demo_talk_ai.plan.json" });
    }
    job = finishJob(job, 0, false);
    update(job);
    const version = versionFromJob(job);
    if (version) {
      const h = addVersion(histories.get(job.video) ?? emptyHistory(job.video), version);
      histories.set(job.video, h);
      historyListeners.forEach((l) => l(h));
    }
  }

  const enqueue = (requests: JobRequest[]) => {
    const created = requests.map((r) => newJob(`mock${++counter}`, r));
    created.forEach((j) => {
      update(j);
      queue = queue.then(() => run(j.id)).catch(() => {});
    });
    return created;
  };

  const changeHistory = (video: string, fn: (h: VideoHistory) => VideoHistory) => {
    const h = fn(histories.get(video) ?? emptyHistory(video));
    histories.set(video, h);
    return Promise.resolve(h);
  };

  return {
    platform: "win32",
    pathForFile: (file) => `C:/Videos/${file.name}`,
    getSettings: async () => settings,
    setSettings: async (patch) => (settings = { ...settings, ...patch }),
    keysStatus: async () => keys,
    setKey: async (provider, key) => (keys = { ...keys, [provider]: { set: true, hint: `••••${key.slice(-4)}` } }),
    clearKey: async (provider) => (keys = { ...keys, [provider]: { set: false, hint: "" } }),
    pickVideos: async () =>
      params.get("scenario") === "parity" ? ["C:/Videos/parity.mp4"] : ["C:/Videos/demo_talk.mp4", "C:/Videos/demo_talk_2.mp4"],
    pickPhotos: async () => ["C:/Videos/github_logo.png"],
    addJobs: async (requests) => enqueue(requests),
    listJobs: async () => {
      if (params.get("scenario") === "parity" && !jobs.size) {
        // A project shown in the live preview, to compare with frames the engine rendered.
        const project = await fetch("/fixtures/parity.project.json").then((r) => r.json());
        const request: JobRequest = { video: "C:/Videos/parity.mp4", photos: [], instruction: "", provider: "groq", auto: false, mode: "new" };
        jobs.set("parity", { ...newJob("parity", request), status: "review", project });
      }
      return [...jobs.values()];
    },
    cancelJob: async (id) => {
      const job = jobs.get(id);
      if (job && (job.status === "queued" || job.status === "running")) update({ ...job, status: "cancelled" });
    },
    dismissJob: async (id) => {
      const job = jobs.get(id);
      if (job?.status === "review") update({ ...job, status: "dismissed" });
    },
    applyPlan: async (jobId, plan) => {
      const job = jobs.get(jobId)!;
      update({ ...job, status: "dismissed" });
      (window as unknown as { lastAppliedPlan: Plan }).lastAppliedPlan = plan;
      return enqueue([{ video: job.video, photos: job.photos, instruction: job.instruction, provider: job.provider, auto: true, mode: "apply", planFile: "C:/x/accepted.plan.json" }]);
    },
    history: async (video) => histories.get(video) ?? emptyHistory(video),
    undo: (video) => changeHistory(video, undo),
    redo: (video) => changeHistory(video, redo),
    estimate: async (_video, provider): Promise<EstimateResult> =>
      provider === "anthropic"
        ? { total: 0.0412, text: "$0.04", provider, model: "claude-opus-5-5", paid_provider: true, transcript_cached: false }
        : { total: 0.0021, text: "$0.0021", provider, model: "openai/gpt-oss-120b", paid_provider: false, transcript_cached: false },
    renderFrame: async () => ({ path: "C:/Videos/demo_frame.png" }),
    checkEngine: async () => ({ ok: true, message: "The editor engine is ready." }),
    onJobChanged: (callback) => {
      jobListeners.add(callback);
      return () => jobListeners.delete(callback);
    },
    onHistoryChanged: (callback) => {
      historyListeners.add(callback);
      return () => historyListeners.delete(callback);
    },
  };
}
