// A stand-in for the Electron bridge, used only by the UI tests (?mock=1). It replays an
// AI edit that the real engine made (fixtures written by tests/ui/make_fixtures.py), with the
// same events in the same order, so the window can be tested without Electron or API keys.
import type { AppApi, BrollFound, BrollRequest, BrollUpdate, EstimateResult, ExportUpdate, LibraryFile, TrackStatus, TrackUpdate } from "../../shared/api";
import { addVersion, emptyHistory, redo, undo } from "../../shared/history";
import { applyEvent, finishJob, newJob, versionFromJob } from "../../shared/jobs";
import type {
  CompareResult, EngineEvent, TrackData, GenStatus, GenTaskUpdate, Job, JobRequest, KeysStatus, Media, Plan, Project, Settings, Summary, Track, VideoHistory,
} from "../../shared/types";
import { CONTENT_TYPES } from "../../shared/types";
import { addGraphic, anotherLook, templateMeta } from "../../shared/graphicsEdit";
import { findScene } from "../../shared/storyboard";

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
    groqModel: "openai/gpt-oss-120b", anthropicModel: "claude-opus-5-5", transcribeWith: "groq", captionPunctuation: "remove", captionStyle: "preset", fixCaptionsFirst: false, autoMode: true,
    consentAccepted: params.has("consent"), musicFolder: params.has("music") ? "C:/Users/me/Music" : "", sfxFolder: "",
    brollFolder: params.has("broll") ? "C:/Users/me/B-roll" : "", useStock: true,
  };
  let keys: KeysStatus = {
    encryptionAvailable: true, groq: { set: true, hint: "••••a1b2" }, anthropic: { set: false, hint: "" },
    pexels: { set: false, hint: "" }, pixabay: { set: false, hint: "" },
  };
  const jobs = new Map<string, Job>();
  const histories = new Map<string, VideoHistory>();
  const jobListeners = new Set<(job: Job) => void>();
  const historyListeners = new Set<(h: VideoHistory) => void>();
  let fixture: Promise<Fixture> | null = null;
  // The AI generation screen: the real engine's status and a Compare run against the fake
  // WanGP (tests/ui/make_fixtures.py). Benchmark/compare runs replay those results.
  let gen: GenStatus | null = null;
  const genListeners = new Set<(u: GenTaskUpdate) => void>();
  const stoppedTasks = new Set<string>();
  const opened: string[] = [];
  // The timeline editor: the AI edit's project, and what the engine said about the demo files.
  const w = window as unknown as {
    savedProjects: { path: string; project: Project }[];
    shownInFolder: string[];
    exports: unknown[];
    vocabulary: { words: string[]; corrections: { from: string; to: string }[] };
    recordings: number[];
    brollRequests: BrollRequest[];
    trackStarts: string[];
    trackDownloads: string[][];
    graphicsRegenerated: { clip: string; ai: boolean }[];
    scenesRegenerated: { scene: string; ai: boolean }[];
  };
  w.vocabulary = { words: ["GCash", "Shopee"], corrections: [{ from: "g cash", to: "GCash" }] };
  w.recordings = [];
  w.brollRequests = [];
  w.trackStarts = [];
  w.trackDownloads = [];
  w.graphicsRegenerated = [];
  w.scenesRegenerated = [];
  const openedProjects = new Map<string, Project>();
  // Tracking: ?track=none (MediaPipe not installed), ?track=models (installed, no model files), else ready.
  const trackMode = params.get("track") ?? "ready";
  const trackModels: TrackStatus["models"] = (["hand", "face", "pose"] as const).map((kind) => ({
    kind, file: kind === "hand" ? "hand_landmarker.task" : kind === "face" ? "blaze_face_short_range.tflite" : "pose_landmarker_lite.task",
    url: `https://storage.googleapis.com/mediapipe-models/${kind}`, page: `https://ai.google.dev/edge/mediapipe/solutions/vision/${kind}`,
    size: kind === "face" ? "under 1 MB" : "about 8 MB", path: `C:/AutoEditor/models/tracking/${kind}`, present: trackMode === "ready",
  }));
  const trackStatus = (): TrackStatus => {
    const have = (k: string) => trackModels.find((m) => m.kind === k)!.present;
    const installed = trackMode !== "none";
    return {
      installed, available: installed && have("hand"), hands: installed && have("hand"), face: installed && have("face"), pose: installed && have("pose"),
      problems: !installed
        ? ["Tracking needs the free MediaPipe package. Install it once: python -m pip install mediapipe  (see docs/tracking.md)"]
        : have("hand") ? [] : ["No hand model yet: download it once (docs/tracking.md, or `python editor.py track-models`) and set tracking: hand_model."],
      models: trackModels.map((m) => ({ ...m })),
    };
  };
  const trackListeners = new Set<(u: TrackUpdate) => void>();
  const stoppedTracks = new Set<string>();
  w.brollRequests = [];
  // B-roll the real engine found or made (tests/ui/make_fixtures.py): library, stock, AI.
  type BrollFixture = { found: (BrollFound & { tag: string })[]; library: LibraryFile[]; media: Record<string, Media> };
  let brollFixture: Promise<BrollFixture> | null = null;
  const loadBroll = () => (brollFixture ??= fetch("/fixtures/broll.json").then((r) => r.json()));
  const brollListeners = new Set<(u: BrollUpdate) => void>();
  const stoppedBroll = new Set<string>();
  /** Like the engine: library first, then stock (with a key), then AI; or only the chosen source. */
  const pickBroll = (f: BrollFixture, r: BrollRequest): BrollFound | null => {
    const free = (x: BrollFound) => !r.exclude.includes(x.file) && !(x.broll.stock_id && r.exclude.includes(x.broll.stock_id));
    const of = (tag: string) => f.found.filter((x) => x.tag.startsWith(tag) && free(x));
    const stockKey = settings.useStock && (keys.pexels.set || keys.pixabay.set);
    const order = r.source === "ai" ? ["ai"] : r.source === "library" ? ["library"] : r.source === "stock" ? (stockKey ? ["stock"] : []) : ["library", ...(stockKey ? ["stock"] : []), "ai"];
    for (const tag of order) {
      if (tag === "library" && !settings.brollFolder) continue;
      const hit = of(tag)[0];
      if (hit) {
        const { tag: _tag, ...found } = hit;
        return { ...found, broll: { ...found.broll, kind: found.media.kind === "video" ? "video" : "image", prompt: r.prompt || found.broll.prompt, search: r.search || found.broll.search, style: r.style } };
      }
    }
    return null;
  };
  w.savedProjects = [];
  w.shownInFolder = [];
  w.exports = [];
  type MediaFixture = { info: Record<string, Media>; peaks: Record<string, unknown>; thumbs: Record<string, unknown> };
  let mediaFixture: Promise<MediaFixture> | null = null;
  const loadMedia = () => (mediaFixture ??= fetch("/fixtures/editor.media.json").then((r) => r.json()));
  const base = (p: string) => p.split(/[\\/]/).pop() ?? p;
  const exportListeners = new Set<(u: ExportUpdate) => void>();
  const stoppedExports = new Set<string>();
  (window as unknown as { openedPaths: string[] }).openedPaths = opened;
  const loadGen = async (): Promise<GenStatus> => {
    if (!gen) {
      gen = (await fetch("/fixtures/gen.status.json").then((r) => r.json())) as GenStatus;
      if (params.has("hwchanged")) {
        gen = { ...gen, hardware_changed: true, previous_hardware: "NVIDIA GeForce GTX 1660 (6 GB VRAM), 16 GB RAM" };
      }
    }
    return gen;
  };
  const recompute = (s: GenStatus): GenStatus => {
    const choices = { ...s.choices };
    for (const c of CONTENT_TYPES) {
      const usable = s.tiers[c].filter((r) => r.installed).map((r) => r.name).reverse();
      const top = s.pinned_tier[c] ?? s.default_tier[c];
      choices[c] = { ...choices[c], order: top && usable.includes(top) ? usable.slice(usable.indexOf(top)) : choices[c].order };
    }
    return { ...s, choices };
  };
  const genTask = (steps: (GenTaskUpdate["event"] & {})[]) => {
    const taskId = `mockgen${++counter}`;
    (async () => {
      for (const event of steps) {
        await wait(150 / speed);
        if (stoppedTasks.has(taskId)) break;
        genListeners.forEach((l) => l({ taskId, event }));
      }
      const cancelled = stoppedTasks.has(taskId);
      genListeners.forEach((l) => l({ taskId, done: true, code: cancelled ? null : 0, cancelled }));
    })();
    return taskId;
  };
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
    // "AI CLIP" in the instructions: the plan asks for one AI video clip (made with WanGP).
    const wantsAi = job.instruction.includes("AI CLIP");
    const clip = { kind: "video" as const, prompt: "Slow push towards a cup of coffee", search: "coffee cup", style: "realistic" as const, source: "ai" as const, at: 3, duration: 2, position: "full" as const, reason: "b-roll while you talk" };
    const plan: Plan = wantsAi ? { ...f.plan, ai_clips: [clip], voiceovers: [] } : f.plan;
    await emit({ type: "stage", stage: "transcript", label: "Listening to your video" });
    await emit({ type: "transcript", words: 13, cached: job.mode !== "new", text: "Kumusta kayo mga kaibigan!" });
    await emit({ type: "stage", stage: "plan", label: "Planning the edit" });
    await emit({
      type: "plan", plan: fail ? f.baseline : plan, baseline: f.baseline, fallback: fail, cached: false, given: job.mode === "apply",
      reason: fail ? "The AI plan failed the checks twice (first problem: plan.style: 'comic' is not one of the styles), so this is the preset edit instead." : "",
      model: "openai/gpt-oss-120b", cost: 0.0016, attempts: [],
    }, 400);
    if (wantsAi && !fail) {
      await emit({ type: "stage", stage: "broll", label: "Finding B-roll" });
      const render = job.auto || job.mode === "apply";
      const passes = job.mode === "apply" ? ["final"] : render ? ["draft", "final"] : ["draft"];
      for (const pass of passes) {
        await emit({ type: "stage", stage: `ai_${pass}`, label: pass === "draft" ? "Making AI clips (draft)" : "Making AI clips (final)" });
        for (const p of [0, 50]) await emit({ type: "progress", stage: `ai_${pass}`, percent: p }, 200);
      }
    }
    for (const stage of ["cuts", "zooms", "captions", "photos"]) {
      const kinds: Record<string, string[]> = { cuts: ["video"], zooms: ["video", "effect"], captions: ["video", "effect", "caption"], photos: ["video", "effect", "caption", "overlay", "audio"] };
      // With an AI clip: the clip WanGP made, as a full-screen video overlay for the first 2 s.
      const base: Project = wantsAi && !fail
        ? {
            ...f.project,
            media: [...f.project.media, { ...f.project.media[0], id: "ai1", path: "C:/AutoEditor/work/generation/outputs/demo_talk_2.mp4", name: "demo_talk_2.mp4", has_audio: false }],
            tracks: f.project.tracks.map((t: Track) =>
              t.id === "photos"
                ? { ...t, clips: [{ id: "ai-o1", type: "video" as const, media: "ai1", start: 0, duration: 2, in: 0, out: 2, x: 540, y: 960, width: 1080, height: 1920, animation: "none" as const }, ...t.clips] }
                : t,
            ),
          }
        : f.project;
      const view: Project = { ...base, tracks: base.tracks.map((t: Track) => (kinds[stage].includes(t.kind) ? t : { ...t, clips: [] })) };
      await emit({ type: "stage", stage, label: stage });
      await emit({ type: "project", stage, project: view }, 250);
    }
    const summary: Summary = fail
      ? { ...f.summary, fallback: true, headline: "Heads up: The AI plan failed the checks twice, so this is the preset edit instead." }
      : wantsAi
        ? {
            ...f.summary,
            details: [
              ...f.summary.details,
              "AI video clip at 0:03: Mid tier, 41s (b-roll while you talk)",
              "AI video clip at 0:03: the High tier out of GPU memory, so the Mid tier was used instead.",
            ],
          }
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
    pickFormatFiles: async (kinds) =>
      kinds.includes("audio") ? ["C:/Videos/vo.wav"] : kinds.includes("video") ? ["C:/Videos/reaction_source.mp4"] : ["C:/Videos/background.png"],
    addJobs: async (requests) => {
      (window as unknown as { lastJobRequests: JobRequest[] }).lastJobRequests = requests;
      return enqueue(requests);
    },
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
    genStatus: async () => recompute(await loadGen()),
    setWangp: async (folder, python) => {
      const s = await loadGen();
      gen = { ...s, wangp: { ...s.wangp, folder, python } };
      return { problems: [] };
    },
    setTier: async (type, kind, tier) => {
      const s = await loadGen();
      const key = kind === "default" ? "default_tier" : "pinned_tier";
      gen = recompute({ ...s, [key]: { ...s[key], [type]: tier } });
      return gen;
    },
    startBenchmark: async (types) => {
      const s = await loadGen();
      const rows = (types.length ? types : CONTENT_TYPES).flatMap((c) => s.tiers[c].filter((r) => r.installed).map((r) => ({ c, r })));
      return genTask(rows.flatMap(({ c, r }) => [
        { type: "benchmark_start", content_type: c, tier: r.name },
        { type: "benchmark_result", content_type: c, tier: r.name, ...r.benchmark },
      ]));
    },
    startCompare: async (type) => {
      const result = (await fetch("/fixtures/gen.compare.json").then((r) => r.json())) as { results: CompareResult[] };
      const results = type === "image" ? result.results : [];
      return genTask([
        ...results.flatMap((r) => [
          { type: "compare_start", content_type: type, tier: r.tier },
          { type: "compare_result", content_type: type, ...r },
        ]),
        { type: "result", ...result, results },
      ]);
    },
    cancelGenTask: async (taskId) => {
      stoppedTasks.add(taskId);
    },
    onGenTask: (callback) => {
      genListeners.add(callback);
      return () => {
        genListeners.delete(callback);
      };
    },
    openPath: async (target) => {
      opened.push(target);
    },
    showInFolder: async (target) => {
      w.shownInFolder.push(target);
    },
    trackStatus: async () => trackStatus(),
    downloadTrackModels: async (kinds) => {
      w.trackDownloads.push([...kinds]);
      await wait(300 / speed);
      for (const m of trackModels) if (kinds.includes(m.kind)) m.present = true;
      return trackStatus();
    },
    startTrack: async (projectPath) => {
      const taskId = `mocktrack${++counter}`;
      w.trackStarts.push(projectPath);
      (async () => {
        const send = (u: Omit<TrackUpdate, "taskId">) => trackListeners.forEach((l) => l({ taskId, ...u }));
        send({ label: "Following your hands and face" });
        for (const percent of [10, 40, 70]) {
          await wait(250 / speed);
          if (stoppedTracks.has(taskId)) return send({ done: true, cancelled: true });
          send({ percent });
        }
        const fixture = (await fetch("/fixtures/track.demo.json").then((r) => r.json())) as { media: string; track: TrackData };
        // The engine saves the points in the project file; the stand-in does the same.
        const saved = [...w.savedProjects].reverse().find((x) => x.path === projectPath);
        const project = structuredClone(saved?.project ?? ((await fetch("/fixtures/demo.project.json").then((r) => r.json())) as Project));
        project.tracking = { ...(project.tracking ?? {}), [fixture.media]: fixture.track };
        w.savedProjects.push({ path: projectPath, project });
        await wait(150 / speed);
        send({ done: true, percent: 100, found: { right_index_tip: 0.93, left_index_tip: 0.05, face: 0.97 } });
      })();
      return taskId;
    },
    cancelTrack: async (taskId) => {
      stoppedTracks.add(taskId);
    },
    onTrack: (callback) => {
      trackListeners.add(callback);
      return () => {
        trackListeners.delete(callback);
      };
    },
    openProject: async (path) => {
      if (params.get("project") === "trackfx" && !w.savedProjects.some((x) => x.path === path)) {
        return { path, project: (await fetch("/fixtures/trackfx.project.json").then((r) => r.json())) as Project, backup: path.replace(/\.project\.json$/, ".before-editing.project.json") };
      }
      if (params.get("project") === "storyboard" && !w.savedProjects.some((x) => x.path === path)) {
        // The demo talk as three scenes (hook, numbers, call to action) with a graphic and B-roll.
        const p = (await fetch("/fixtures/demo.project.json").then((r) => r.json())) as Project;
        p.tracks[0].clips = [{ id: "v1", type: "video", media: "m1", start: 0, duration: 8, in: 0, out: 8 }];
        p.tracks = p.tracks.filter((t) => t.kind !== "effect" || t.clips.every((c) => c.type !== "zoom"));
        const lines: [number, number, string][] = [[0.1, 1.5, "Alam niyo ba ito?"], [1.7, 1.0, "Simple lang."], [2.8, 1.6, "Una, mag-budget ng 500 piso."], [4.5, 1.4, "Pangalawa, mag-ipon araw-araw."], [6.0, 1.8, "I-follow niyo ako para sa part two!"]];
        p.tracks.find((t) => t.kind === "caption")!.clips = lines.map(([start, duration, text], i) => {
          const words = text.split(" ");
          const step = duration / words.length;
          return { id: `t${i + 1}`, type: "caption", start, duration, style: "bold_caps", words: words.map((x, k) => ({ text: x, start: Math.round(k * step * 1e4) / 1e4, end: Math.round((k + 0.9) * step * 1e4) / 1e4 })) };
        });
        p.tracks.splice(2, 0, { id: "graphics", kind: "graphics", name: "Graphics", clips: [{ id: "gx1", type: "graphic", template: "stamp", start: 3.0, duration: 1.2, params: { text: "500" }, x: 0.5, y: 0.3 }] });
        // New words: the scenes come from them, not from the fixture's saved scene starts.
        if (p.meta) delete (p.meta as Record<string, unknown>).storyboard;
        openedProjects.set(path, structuredClone(p));
        return { path, project: p, backup: path.replace(/\.project\.json$/, ".before-editing.project.json") };
      }
      if (params.get("project") === "broken") return { path, error: "The project file has problems:\n  - project.tracks[0] clip 'v1': unknown media 'nope'" };
      const saved = [...w.savedProjects].reverse().find((x) => x.path === path);
      const project = saved?.project ?? ((await fetch("/fixtures/demo.project.json").then((r) => r.json())) as Project);
      openedProjects.set(path, structuredClone(project));
      return { path, project, backup: path.replace(/\.project\.json$/, ".before-editing.project.json") };
    },
    saveProject: async (path, project) => {
      if (params.has("saveFail")) return { ok: false, error: "Could not save: the disk is full." };
      w.savedProjects.push({ path, project: structuredClone(project) });
      return { ok: true };
    },
    pickProject: async () => "C:/Videos/demo_talk_ai.project.json",
    pickMedia: async () => ["C:/Videos/demo_talk_2.mp4", "C:/Videos/tone.wav", "C:/Videos/broken.mp4"],
    pickExportPath: async () => "C:/Videos/my video export.mp4",
    mediaInfo: async (paths) => {
      const f = await loadMedia();
      const b = await loadBroll();
      const info = (p: string) => f.info[base(p)] ?? b.media[p] ?? b.found.find((x: BrollFound) => x.file === p)?.media;
      const media = paths.map(info).filter(Boolean) as Media[];
      const errors = paths.filter((p) => !info(p)).map((p: string) => ({ path: p, message: "FFmpeg cannot read 'broken.mp4'. It may be damaged or not a video/image file." }));
      return { media, errors };
    },
    peaks: async (path) => ((await loadMedia()).peaks[base(path)] as never) ?? { error: "no sound" },
    thumbs: async (path) => ((await loadMedia()).thumbs[base(path)] as never) ?? { error: "no pictures" },
    startExport: async (projectPath, options) => {
      const taskId = `mockexport${++counter}`;
      w.exports.push({ projectPath, ...options });
      (async () => {
        for (const percent of [5, 20, 45, 70, 90]) {
          await wait(200 / speed);
          if (stoppedExports.has(taskId)) {
            exportListeners.forEach((l) => l({ taskId, done: true, cancelled: true }));
            return;
          }
          exportListeners.forEach((l) => l({ taskId, percent }));
        }
        await wait(150 / speed);
        exportListeners.forEach((l) => l({ taskId, done: true, percent: 100, output: options.output }));
      })();
      return taskId;
    },
    getVocabulary: async () => structuredClone(w.vocabulary),
    transcribe: async () => {
      const text = "Teka lang! Tatyo sikreto ng viral na video. Sa search bar, hinanat ko: paano kumita online.";
      let t = 0.3;
      const words = text.split(" ").map((word) => {
        const out = { text: word, start: Math.round(t * 1000) / 1000, end: Math.round((t + 0.35) * 1000) / 1000 };
        t += word.endsWith(".") || word.endsWith("!") ? 0.9 : 0.4;
        return out;
      });
      (window as unknown as { lastTranscribed: unknown }).lastTranscribed = words;
      return { file: "C:/AppData/transcripts/demo.transcript.json", words };
    },
    saveTranscript: async (file, words) => {
      (window as unknown as { savedTranscript: unknown }).savedTranscript = { file, words };
      return { ok: true };
    },
    setVocabulary: async (v) => {
      w.vocabulary = structuredClone(v);
      return { ok: true };
    },
    listLibrary: async (kind) => {
      const folder = kind === "music" ? settings.musicFolder : kind === "sfx" ? settings.sfxFolder : settings.brollFolder;
      if (!folder) return { folder: "", files: [] };
      if (kind === "broll") return { folder, files: (await loadBroll()).library };
      return {
        folder,
        files: [
          { path: `${folder}/tone.wav`, name: "tone.wav", group: "" },
          { path: `${folder}/Upbeat/Sunny.mp3`, name: "Sunny.mp3", group: "Upbeat" },
        ],
      };
    },
    pickFolder: async (title) => (title.includes("B-roll") ? "C:/Users/me/B-roll" : "C:/Users/me/Sounds"),
    startBroll: async (request) => {
      const taskId = `mockbroll${++counter}`;
      w.brollRequests.push(structuredClone(request));
      (async () => {
        const f = await loadBroll();
        const send = (u: Omit<BrollUpdate, "taskId">) => brollListeners.forEach((l) => l({ taskId, ...u }));
        send({ label: "Finding B-roll" });
        const found = pickBroll(f, request);
        if (found?.broll.source === "ai") {
          send({ label: request.quality === "draft" ? "Making AI clips (draft)" : "Making AI clips (final)" });
          for (const percent of [0, 50]) {
            await wait(250 / speed);
            if (stoppedBroll.has(taskId)) return send({ done: true, cancelled: true });
            send({ percent });
          }
        }
        await wait(200 / speed);
        if (stoppedBroll.has(taskId)) return send({ done: true, cancelled: true });
        if (!found) return send({ done: true, error: "No B-roll found or made. Add a B-roll folder, a stock key, or set up WanGP." });
        send({ done: true, result: found });
      })();
      return taskId;
    },
    cancelBroll: async (taskId) => {
      stoppedBroll.add(taskId);
    },
    onBroll: (callback) => {
      brollListeners.add(callback);
      return () => {
        brollListeners.delete(callback);
      };
    },
    saveRecording: async (_projectPath, data) => {
      w.recordings.push(data.length);
      // The stand-in has no disk: the "recording" becomes the demo tone (what the engine reads back).
      return { path: "C:/Videos/tone.wav" };
    },
    retranscribe: async (projectPath, start, end) => {
      await wait(300 / speed);
      const saved = [...w.savedProjects].reverse().find((x) => x.path === projectPath);
      const project = structuredClone(saved?.project ?? ((await fetch("/fixtures/demo.project.json").then((r) => r.json())) as Project));
      const caps = project.tracks.find((t) => t.kind === "caption")!;
      caps.clips = caps.clips.filter((c) => c.start + c.duration <= start || c.start >= end);
      caps.clips.push({ id: "rt1", type: "caption", start, duration: Math.max(0.3, end - start), style: "bold_caps", words: [{ text: "Pakinggan", start: 0, end: 0.4 }, { text: "ulit", start: 0.45, end: 0.8 }] });
      caps.clips.sort((a, b) => a.start - b.start);
      w.savedProjects.push({ path: projectPath, project });
      return { project, words: 2 };
    },
    storyboardRegenerate: async (projectPath, sceneId, useAi) => {
      // Like the engine: another look for the scene's unlocked graphics (or one new pop-up word).
      await wait(200 / speed);
      // Like the engine, read the project file: the last save, else the file as it was opened.
      const saved = [...w.savedProjects].reverse().find((x) => x.path === projectPath) ?? (openedProjects.has(projectPath) ? { project: openedProjects.get(projectPath)! } : undefined);
      if (!saved) return { error: "The project was not saved." };
      w.scenesRegenerated.push({ scene: sceneId, ai: useAi });
      try {
        let project = structuredClone(saved.project);
        const scene = findScene(project, sceneId);
        if (scene.locked) return { error: "This scene is locked. Unlock it first." };
        if (scene.graphics.length) {
          for (const g of scene.graphics) project = anotherLook(project, g.id);
        } else {
          const word = scene.text.split(/\s+/).sort((a, b) => b.length - a.length)[0] ?? "WOW";
          const text = word.replace(/[^\p{L}\p{N}-]/gu, "").toUpperCase() || "WOW";
          project = addGraphic(project, "pop-heavy", scene.start + 0.1, { text }).project;
        }
        w.savedProjects.push({ path: projectPath, project });
        return { project, notes: [] };
      } catch (err) {
        return { error: (err as Error).message };
      }
    },
    graphicsRegenerate: async (projectPath, clipId, useAi) => {
      await wait(200 / speed);
      const saved = [...w.savedProjects].reverse().find((x) => x.path === projectPath);
      if (!saved) return { error: "The project was not saved." };
      w.graphicsRegenerated.push({ clip: clipId, ai: useAi });
      try {
        const project = anotherLook(structuredClone(saved.project), clipId);
        w.savedProjects.push({ path: projectPath, project });
        return { project };
      } catch (err) {
        return { error: (err as Error).message };
      }
    },
    graphicsCheck: async (projectPath) => {
      // The stand-in checks one thing like the engine: a graphic over the usual face area.
      const saved = [...w.savedProjects].reverse().find((x) => x.path === projectPath);
      const issues = [];
      for (const t of saved?.project.tracks ?? []) {
        for (const c of t.kind === "graphics" ? t.clips : []) {
          const meta = templateMeta(c.template);
          if (!meta) continue;
          const k = c.params?.size ?? 1;
          const [cx, cy] = [(c.x ?? 0.5) * 1080, (c.y ?? 0.5) * 1920];
          const [w2, h2] = [(meta.box.w * k) / 2, (meta.box.h * k) / 2];
          if (cx - w2 < 760 && cx + w2 > 320 && cy - h2 < 920 && cy + h2 > 380) {
            issues.push({ clip: c.id, kind: "face", severity: "warn", time: c.start, message: `'${meta.name}' at ${c.start.toFixed(1)}s covers the speaker's face.`, tl: `Natatakpan ang mukha.` });
          }
        }
      }
      return { issues };
    },
    cancelExport: async (taskId) => {
      stoppedExports.add(taskId);
    },
    onExport: (callback) => {
      exportListeners.add(callback);
      return () => {
        exportListeners.delete(callback);
      };
    },
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
