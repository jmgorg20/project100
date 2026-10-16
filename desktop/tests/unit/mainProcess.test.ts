// The Electron main process (src/main/main.ts) with a stand-in `electron` module: the IPC
// handlers, job queue, engine runs and history are real; only the window/dialog/encryption
// pieces are faked. The engine runs a real AI edit from an accepted plan (no AI call) on a
// synthetic video, with its transcript seeded in the engine's cache (no Whisper call).
import { execFileSync } from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { CompareResult, GenStatus, Job, VideoHistory } from "../../src/shared/types";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "autoedit-main-"));
// AI generation settings and measurements go to a test folder (never the repository's own).
const genHome = path.join(tmp, "gen");
process.env.AUTOEDIT_GENERATION_HOME = genHome;
const handlers = new Map<string, (...args: unknown[]) => unknown>();
const sent: [string, unknown][] = [];

vi.mock("electron", () => {
  class BrowserWindow {
    webContents = {
      send: (channel: string, payload: unknown) => sent.push([channel, payload]),
      setWindowOpenHandler: () => {},
      on: () => {},
    };
    static getAllWindows = () => [];
    loadURL() {}
    loadFile() {}
    on() {}
    isDestroyed() {
      return false;
    }
  }
  return {
    app: {
      getPath: () => path.join(tmp, "userData"),
      getAppPath: () => path.join(repo, "desktop"),
      whenReady: () => Promise.resolve(),
      on: () => {},
      quit: () => {},
    },
    BrowserWindow,
    dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) },
    ipcMain: { handle: (channel: string, fn: (...args: unknown[]) => unknown) => handlers.set(channel, fn) },
    safeStorage: {
      isEncryptionAvailable: () => true,
      encryptString: (s: string) => Buffer.from(s).reverse(),
      decryptString: (b: Buffer) => Buffer.from(b).reverse().toString(),
    },
    shell: { openExternal: () => {}, openPath: async () => "" },
    session: { defaultSession: { setPermissionRequestHandler: () => {}, setPermissionCheckHandler: () => {} } },
  };
});

const call = (channel: string, ...args: unknown[]) => handlers.get(channel)!({}, ...args) as Promise<unknown>;
let seeded = "";

beforeAll(async () => {
  // A synthetic talking video, a photo, and its transcript in the engine's cache.
  execFileSync(python, ["-c", `
import sys; sys.path.insert(0, ".")
from pathlib import Path
from tests import synthetic
d = Path(sys.argv[1])
synthetic.make_video(d / "talk.mp4"); synthetic.make_transcript(d / "talk.json"); synthetic.make_image(d / "logo.png")
`, tmp], { cwd: repo });
  const digest = crypto.createHash("sha256").update(fs.readFileSync(path.join(tmp, "talk.mp4"))).digest("hex");
  seeded = path.join(repo, "work", "cache", "transcripts", `${digest}-groq-whisper-large-v3-tl.json`);
  fs.mkdirSync(path.dirname(seeded), { recursive: true });
  fs.copyFileSync(path.join(tmp, "talk.json"), seeded);
  await import("../../src/main/main");
  await new Promise((r) => setTimeout(r, 0));
}, 60_000);

afterAll(() => {
  if (seeded) fs.rmSync(seeded, { force: true });
});

const lastJob = (): Job => [...sent].reverse().find(([c]) => c === "job:changed")![1] as Job;

describe("main process with the real engine", () => {
  it("registers every channel the window uses", () => {
    for (const channel of ["settings:get", "settings:set", "keys:status", "keys:set", "keys:clear", "dialog:videos", "dialog:photos",
      "jobs:add", "jobs:list", "jobs:cancel", "jobs:dismiss", "plan:apply", "history:get", "history:undo", "history:redo",
      "engine:estimate", "engine:frame", "engine:check", "gen:status", "gen:setWangp", "gen:setTier", "gen:benchmark",
      "gen:compare", "gen:cancel", "app:openPath", "app:showInFolder", "project:open", "project:save", "dialog:project",
      "dialog:media", "dialog:exportPath", "media:info", "media:peaks", "media:thumbs", "export:start", "export:cancel",
      "vocab:get", "vocab:set", "library:list", "dialog:folder", "media:saveRecording", "project:retranscribe", "broll:start", "broll:cancel"]) {
      expect(handlers.has(channel), channel).toBe(true);
    }
  });

  it("starts with Auto mode on and the repository as the engine", async () => {
    const settings = (await call("settings:get")) as { autoMode: boolean; engineDir: string };
    expect(settings.autoMode).toBe(true);
    expect(settings.engineDir).toBe(repo);
    await call("settings:set", { pythonPath: python, outputDir: path.join(tmp, "out") });
    expect(await call("engine:check")).toEqual({ ok: true, message: "The editor engine is ready." });
  });

  it("keeps keys encrypted and only reports a hint", async () => {
    const status = (await call("keys:set", "anthropic", "sk-ant-abcd1234")) as { anthropic: { set: boolean; hint: string } };
    expect(status.anthropic).toEqual({ set: true, hint: "••••1234" });
    expect(fs.readFileSync(path.join(tmp, "userData", "keys.json"), "utf-8")).not.toContain("sk-ant-abcd1234");
    await call("keys:clear", "anthropic");
  });

  it("estimates the cost with the real engine", async () => {
    const estimate = (await call("engine:estimate", path.join(tmp, "talk.mp4"), "anthropic", "fast")) as { total: number; transcript_cached: boolean; model: string };
    expect(estimate.model).toBe("claude-opus-5-5");
    expect(estimate.transcript_cached).toBe(true);
    expect(estimate.total).toBeGreaterThan(0);
  }, 60_000);

  it("runs an accepted plan to a finished video, records the version, and undoes it", async () => {
    const plan = JSON.parse(execFileSync(python, ["-c", `
import json
from autoedit.config import load_config
from autoedit.ai_plan import preset_plan
p = preset_plan(load_config()); p["style"] = "one_word"
p["photos"] = [{"file": "logo.png", "at": 5.5, "duration": 1.5, "position": "top", "reason": "GitHub"}]
print(json.dumps(p))`], { cwd: repo, encoding: "utf-8" }));
    const planFile = path.join(tmp, "accepted.plan.json");
    fs.writeFileSync(planFile, JSON.stringify({ plan }));
    const video = path.join(tmp, "talk.mp4");
    await call("jobs:add", [{ video, photos: [path.join(tmp, "logo.png")], instruction: "one word captions", provider: "groq", auto: true, mode: "apply", planFile }]);
    await vi.waitFor(() => expect(["done", "failed"]).toContain(lastJob().status), { timeout: 120_000, interval: 200 });
    const job = lastJob();
    expect(job.error).toBeUndefined();
    expect(job.status).toBe("done");
    expect(job.stagesDone).toEqual(["transcript", "plan", "cuts", "zooms", "captions", "photos", "render"]);
    expect(job.transcriptCached).toBe(true);
    expect(job.summary?.details.join(" ")).toContain("one_word");
    expect(path.basename(job.output!)).toBe("talk_ai.mp4");
    expect(fs.existsSync(job.output!)).toBe(true);
    // A version was added to the history and sent to the window.
    const history = [...sent].reverse().find(([c]) => c === "history:changed")![1] as VideoHistory;
    expect(history.current).toBe(0);
    expect(history.versions[0].output).toBe(job.output);
    expect(((await call("history:undo", video)) as VideoHistory).current).toBe(-1);
    expect(((await call("history:redo", video)) as VideoHistory).current).toBe(0);
    // "Exact frame" renders the true frame from the saved project.
    const frame = (await call("engine:frame", job.projectFile, 1.0)) as { path: string };
    expect(fs.existsSync(frame.path)).toBe(true);
  }, 180_000);

  // ---------------------------------------------------------------- AI generation (WanGP)
  // The real engine against the stand-in for WanGP in tests/fake_wangp (no GPU here).

  type GenUpdate = { taskId: string; event?: Record<string, unknown>; done?: boolean; code?: number | null; cancelled?: boolean };
  const updates = (taskId: string) => sent.filter(([c, u]) => c === "gen:task" && (u as GenUpdate).taskId === taskId).map(([, u]) => u as GenUpdate);
  const finished = async (taskId: string) => {
    await vi.waitFor(() => expect(updates(taskId).some((u) => u.done)).toBe(true), { timeout: 120_000, interval: 200 });
    return updates(taskId);
  };

  it("sets up WanGP and reads the tiers, with WanGP's own installed check", async () => {
    const wangp = path.join(genHome, "WanGP");
    fs.cpSync(path.join(repo, "tests", "fake_wangp"), wangp, { recursive: true });
    const hf = (m: string) => [`https://huggingface.co/SomeOrg/${m}/resolve/main/model.safetensors`];
    fs.writeFileSync(path.join(wangp, "fake_models.json"), JSON.stringify([
      { model_type: "pic_small", name: "Pic Small", family: "Pic", main_output: ["image"], status: "available", urls: hf("pic_small"), seconds: 0.2 },
      { model_type: "pic_big", name: "Pic Big", family: "Pic", main_output: ["image"], status: "available", urls: hf("pic_big"), seconds: 0.3 },
      { model_type: "clip_slow", name: "Clip Slow", family: "Clip", main_output: ["video"], status: "available", urls: hf("clip_slow"), seconds: 60 },
      { model_type: "clip_missing", name: "Clip Missing", family: "Clip", main_output: ["video"], status: "missing", urls: hf("clip_missing") },
    ]));
    const templates = path.join(genHome, "templates");
    fs.mkdirSync(templates, { recursive: true });
    const template = (name: string, model: string, extra = {}) => {
      fs.writeFileSync(path.join(templates, name), JSON.stringify({ model_type: model, resolution: "320x576", num_inference_steps: 2, ...extra }));
      return name;
    };
    const settings = JSON.parse(fs.readFileSync(path.join(repo, "generation.example.json"), "utf-8"));
    settings.templates_folder = templates;
    settings.tiers.image[0].template = template("pic_draft.json", "pic_small");
    settings.tiers.image[2].template = template("pic_mid.json", "pic_big");
    settings.tiers.video[0].template = template("clip_draft.json", "clip_slow", { video_length: 17, num_inference_steps: 30 });
    settings.tiers.video[3].template = template("clip_high.json", "clip_missing");
    fs.writeFileSync(path.join(genHome, "generation.json"), JSON.stringify(settings));

    const before = (await call("gen:status", false)) as { setup_problems: string[]; settings_file: string; hardware_summary: string };
    expect(before.settings_file).toBe(path.join(genHome, "generation.json"));
    expect(before.setup_problems.length).toBeGreaterThan(0); // no WanGP folder yet
    expect(before.hardware_summary).toBeTruthy(); // something is always shown, even with no GPU

    expect(await call("gen:setWangp", wangp, python)).toEqual({ problems: [] });
    const status = (await call("gen:status", true)) as GenStatus;
    expect(status.wangp.version).toBe("99.1-test");
    const statusOf = (type: "image" | "video", tier: string) => status.tiers[type].find((r) => r.name === tier)!;
    expect(statusOf("image", "Draft")).toMatchObject({ installed: true, model_name: "Pic Small" });
    expect(statusOf("image", "Mid")).toMatchObject({ installed: true, model_name: "Pic Big" });
    expect(statusOf("image", "Low")).toMatchObject({ installed: false, status: "not set up" });
    expect(statusOf("video", "High")).toMatchObject({ installed: false, status: "not installed" });
    expect(statusOf("video", "High").links[0]).toBe("https://huggingface.co/SomeOrg/clip_missing");
    expect(status.choices.image).toEqual({ preview: "Draft", order: ["Mid", "Draft"] });
  }, 120_000);

  it("saves a default and a pinned tier per content type", async () => {
    let status = (await call("gen:setTier", "image", "default", "Draft")) as GenStatus;
    expect(status.default_tier.image).toBe("Draft");
    expect(status.choices.image.order).toEqual(["Draft"]);
    status = (await call("gen:setTier", "image", "pin", "Mid")) as GenStatus;
    expect(status.pinned_tier.image).toBe("Mid");
    expect(status.choices.image.order).toEqual(["Mid", "Draft"]);
    status = (await call("gen:setTier", "image", "pin", null)) as GenStatus;
    status = (await call("gen:setTier", "image", "default", null)) as GenStatus;
    expect([status.pinned_tier.image, status.default_tier.image]).toEqual([null, null]);
  }, 60_000);

  it("runs a test of each installed tier and sends its events to the window", async () => {
    const taskId = (await call("gen:benchmark", ["image"])) as string;
    const got = await finished(taskId);
    const results = got.filter((u) => u.event?.type === "benchmark_result").map((u) => u.event!);
    expect(results.map((e) => [e.tier, e.success])).toEqual([["Draft", true], ["Mid", true]]);
    expect(got.filter((u) => u.event?.type === "benchmark_start")).toHaveLength(2);
    expect(got.at(-1)).toMatchObject({ done: true, code: 0, cancelled: false });
    const status = (await call("gen:status", false)) as GenStatus;
    expect(status.tiers.image.find((r) => r.name === "Mid")!.benchmark).toMatchObject({ success: true });
  }, 120_000);

  it("compares every installed tier with the same prompt and seed", async () => {
    const taskId = (await call("gen:compare", "image", "A sari-sari store", 7)) as string;
    const got = await finished(taskId);
    const result = got.find((u) => u.event?.type === "result")!.event as { results: CompareResult[]; seed: number };
    expect(result.seed).toBe(7);
    expect(result.results.map((r) => [r.tier, r.success])).toEqual([["Draft", true], ["Mid", true]]);
    for (const r of result.results) expect(fs.existsSync(r.output!)).toBe(true);
    const calls = fs.readFileSync(path.join(genHome, "WanGP", "calls.jsonl"), "utf-8").trim().split("\n").map((l) => JSON.parse(l));
    const compared = calls.filter((c) => c.prompt === "A sari-sari store");
    expect(compared.map((c) => [c.model_type, c.seed])).toEqual([["pic_small", 7], ["pic_big", 7]]);
    expect(calls.some((c) => c.model_type === "clip_missing")).toBe(false); // never sent: WanGP would download it
  }, 120_000);

  it("stops a running test", async () => {
    const taskId = (await call("gen:benchmark", ["video"])) as string; // a 60-second job
    await vi.waitFor(() => expect(updates(taskId).some((u) => u.event?.type === "benchmark_start")).toBe(true), { timeout: 60_000, interval: 200 });
    const started = Date.now();
    await call("gen:cancel", taskId);
    const got = await finished(taskId);
    expect(got.at(-1)).toMatchObject({ done: true, cancelled: true });
    expect(Date.now() - started).toBeLessThan(30_000); // WanGP stopped at its next step
    // The engine closed WanGP itself: no bridge process is left behind.
    if (process.platform !== "win32") {
      const left = execFileSync("ps", ["-eo", "args"], { encoding: "utf-8" }).split("\n").filter((l) => l.includes(genHome) && l.includes("wangp_bridge"));
      expect(left).toEqual([]);
    }
  }, 120_000);

  it("makes a plan's AI picture during the edit, within the per-video limits", async () => {
    const plan = JSON.parse(execFileSync(python, ["-c", `
import json
from autoedit.config import load_config
from autoedit.ai_plan import preset_plan
p = preset_plan(load_config())
p["ai_clips"] = [{"kind": "image", "prompt": "a cup of coffee", "at": 1.0, "duration": 1.5, "position": "full", "reason": "b-roll"},
                 {"kind": "image", "prompt": "a jeepney", "at": 3.0, "duration": 1.0, "position": "top", "reason": "b-roll"}]
print(json.dumps(p))`], { cwd: repo, encoding: "utf-8" }));
    const planFile = path.join(tmp, "ai.plan.json");
    fs.writeFileSync(planFile, JSON.stringify({ plan }));
    const video = path.join(tmp, "talk.mp4");
    await call("jobs:add", [{ video, photos: [], instruction: "add b-roll", provider: "groq", auto: true, mode: "apply", planFile, maxGenMinutes: 5, maxAiClips: 1 }]);
    await vi.waitFor(() => expect(["done", "failed"]).toContain(lastJob().status), { timeout: 150_000, interval: 200 });
    const job = lastJob();
    expect(job.error).toBeUndefined();
    expect(job.stagesDone).toEqual(["transcript", "plan", "broll", "ai_final", "cuts", "zooms", "captions", "photos", "render"]);
    const details = job.summary!.details.join("\n");
    expect(details).toContain("AI picture at 0:01: Mid tier");
    expect(details).toContain("Not done: 1 AI picture(s)/clip(s) over this video's limit of 1.");
    expect(fs.existsSync(job.output!)).toBe(true);
  }, 200_000);

  // ---------------------------------------------------------------- timeline editor

  type ExportMsg = { taskId: string; percent?: number; done?: boolean; output?: string; error?: string; cancelled?: boolean };
  const exportUpdates = (taskId: string) => sent.filter(([c, u]) => c === "export:task" && (u as ExportMsg).taskId === taskId).map(([, u]) => u as ExportMsg);

  it("opens a project (checked by the engine, backed up once) and saves it atomically", async () => {
    const file = path.join(tmp, "edit me.project.json");
    execFileSync(python, ["-c", `
import sys
from autoedit.project import new_project, media_from_file, save_project
p = new_project("edit me")
p["media"] = [media_from_file(sys.argv[1], "m1")]
p["tracks"][0]["clips"] = [{"id": "v1", "type": "video", "media": "m1", "start": 0, "duration": 3, "in": 1, "out": 4}]
save_project(p, sys.argv[2])`, path.join(tmp, "talk.mp4"), file], { cwd: repo });
    const opened = (await call("project:open", file)) as { project: { tracks: { clips: unknown[] }[] }; backup: string; error?: string };
    expect(opened.error).toBeUndefined();
    expect(opened.project.tracks[0].clips).toHaveLength(1);
    expect(opened.backup).toBe(path.join(tmp, "edit me.before-editing.project.json"));
    expect(fs.existsSync(opened.backup)).toBe(true);

    const edited = { ...opened.project, name: "changed" };
    expect(await call("project:save", file, edited)).toEqual({ ok: true });
    expect(JSON.parse(fs.readFileSync(file, "utf-8")).name).toBe("changed");
    expect(fs.existsSync(`${file}.tmp`)).toBe(false);
    expect(JSON.parse(fs.readFileSync(opened.backup, "utf-8")).name).toBe("edit me"); // the backup is kept as it was
    await call("project:open", file);
    expect(JSON.parse(fs.readFileSync(opened.backup, "utf-8")).name).toBe("edit me"); // and not replaced on reopening
    expect(((await call("project:save", path.join(tmp, "x.txt"), edited)) as { ok: boolean }).ok).toBe(false);

    const bad = path.join(tmp, "bad.project.json");
    fs.writeFileSync(bad, JSON.stringify({ ...edited, tracks: [{ id: "main", kind: "video", clips: [{ id: "v1", type: "video", media: "nope", start: 0, duration: 1, in: 0, out: 1 }] }] }));
    expect(((await call("project:open", bad)) as { error: string }).error).toContain("unknown media 'nope'");
  }, 120_000);

  it("reads media info, waveforms and filmstrips with the engine", async () => {
    const info = (await call("media:info", [path.join(tmp, "talk.mp4"), path.join(tmp, "missing.mp4")])) as { media: { kind: string }[]; errors: { path: string }[] };
    expect(info.media.map((m) => m.kind)).toEqual(["video"]);
    expect(info.errors[0].path).toContain("missing.mp4");
    const peaks = (await call("media:peaks", path.join(tmp, "talk.mp4"))) as { peaks: number[]; per_second: number };
    expect(peaks.per_second).toBe(50);
    expect(peaks.peaks.length).toBeGreaterThan(100);
    const thumbs = (await call("media:thumbs", path.join(tmp, "talk.mp4"))) as { files: string[] };
    expect(thumbs.files.length).toBeGreaterThan(2);
    expect(thumbs.files.every((f) => fs.existsSync(f))).toBe(true);
  }, 120_000);

  it("exports with the chosen size and frame rate, with progress; and can cancel", async () => {
    const file = path.join(tmp, "edit me.project.json");
    const output = path.join(tmp, "my export.mp4");
    const taskId = (await call("export:start", file, { output, height: 1280, fps: 25, crf: 28, speed: "veryfast" })) as string;
    await vi.waitFor(() => expect(exportUpdates(taskId).some((u) => u.done)).toBe(true), { timeout: 120_000, interval: 200 });
    const got = exportUpdates(taskId);
    expect(got.at(-1)).toMatchObject({ done: true, output });
    expect(got.some((u) => (u.percent ?? 0) > 0 && !u.done)).toBe(true);
    const probe = execFileSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames", "-of", "json", output], { encoding: "utf-8" });
    expect(JSON.parse(probe).streams[0]).toMatchObject({ width: 720, height: 1280, r_frame_rate: "25/1", nb_read_frames: "75" });

    const cancelled = (await call("export:start", file, { output: path.join(tmp, "never.mp4"), height: 1920, fps: 30, crf: 18, speed: "slow" })) as string;
    await call("export:cancel", cancelled);
    await vi.waitFor(() => expect(exportUpdates(cancelled).some((u) => u.done)).toBe(true), { timeout: 60_000, interval: 200 });
    expect(exportUpdates(cancelled).at(-1)).toMatchObject({ done: true, cancelled: true });
    expect(fs.existsSync(path.join(tmp, "never.mp4"))).toBe(false);
    expect(fs.existsSync(path.join(tmp, "never.part.mp4"))).toBe(false);
  }, 200_000);

  // ---------------------------------------------------------------- captions, sound, effects

  it("reads and saves your vocabulary next to the engine (starting from the example)", async () => {
    const file = path.join(repo, "vocabulary.json");
    const had = fs.existsSync(file) ? fs.readFileSync(file, "utf-8") : null;
    try {
      if (had !== null) fs.rmSync(file);
      const first = (await call("vocab:get")) as { words: string[] };
      expect(first.words).toContain("GCash"); // from vocabulary.example.json
      expect(await call("vocab:set", { words: ["Ate Rose", " "], corrections: [{ from: "g cash", to: "GCash" }, { from: "", to: "x" }] })).toEqual({ ok: true });
      expect(JSON.parse(fs.readFileSync(file, "utf-8"))).toEqual({ words: ["Ate Rose"], corrections: [{ from: "g cash", to: "GCash" }] });
      expect(await call("vocab:get")).toEqual({ words: ["Ate Rose"], corrections: [{ from: "g cash", to: "GCash" }] });
    } finally {
      if (had !== null) fs.writeFileSync(file, had);
      else fs.rmSync(file, { force: true });
    }
  });

  it("lists your music folder (sound files only, also in sub-folders)", async () => {
    const music = path.join(tmp, "My Music");
    fs.mkdirSync(path.join(music, "Upbeat"), { recursive: true });
    fs.writeFileSync(path.join(music, "a song.mp3"), "x");
    fs.writeFileSync(path.join(music, "Upbeat", "b.WAV"), "x");
    fs.writeFileSync(path.join(music, "cover.jpg"), "x");
    expect(await call("library:list", "music")).toEqual({ folder: "", files: [] }); // no folder chosen yet
    await call("settings:set", { musicFolder: music });
    const r = (await call("library:list", "music")) as { files: { name: string; group: string }[] };
    expect(r.files.map((f) => [f.name, f.group])).toEqual([["a song.mp3", ""], ["b.WAV", "Upbeat"]]);
    await call("settings:set", { musicFolder: path.join(tmp, "gone") });
    expect(((await call("library:list", "music")) as { error: string }).error).toContain("not found");
  });

  it("saves a recording next to the project, and the engine can read its length", async () => {
    const file = path.join(tmp, "edit me.project.json");
    const data = new Uint8Array(fs.readFileSync(path.join(repo, "tests", "data", "browser_recording.webm")));
    const r = (await call("media:saveRecording", file, data, "webm")) as { path: string };
    expect(path.dirname(r.path)).toBe(path.join(tmp, "recordings"));
    expect(fs.readFileSync(r.path).length).toBe(data.length);
    const info = (await call("media:info", [r.path])) as { media: { kind: string; duration: number }[] };
    expect(info.media[0].kind).toBe("audio");
    expect(info.media[0].duration).toBeGreaterThan(1.5);
    expect(((await call("media:saveRecording", file, data, "../x")) as { error: string }).error).toBeTruthy();
  }, 60_000);

  it("listen again: the engine's error comes back clearly (no transcriber key in the tests)", async () => {
    const file = path.join(tmp, "edit me.project.json");
    const before = fs.readFileSync(file, "utf-8");
    const env = { ...process.env };
    // Empty (not removed): the engine then does not read a real key from your .env file.
    process.env.GROQ_API_KEY = "";
    try {
      const r = (await call("project:retranscribe", file, 0, 1)) as { error?: string; project?: unknown };
      expect(r.project).toBeUndefined();
      expect(r.error).toMatch(/GROQ_API_KEY|Groq|transcrib/i);
    } finally {
      if (env.GROQ_API_KEY === undefined) delete process.env.GROQ_API_KEY;
      else process.env.GROQ_API_KEY = env.GROQ_API_KEY;
    }
    expect(fs.readFileSync(file, "utf-8")).toBe(before); // nothing changed
  }, 120_000);

  // ---------------------------------------------------------------- B-roll

  const brollUpdates = (taskId: string) =>
    sent.filter(([c, u]) => c === "broll:task" && (u as { taskId: string }).taskId === taskId).map(([, u]) => u as {
      done?: boolean; label?: string; error?: string; cancelled?: boolean;
      result?: { file: string; media: { kind: string; path: string }; broll: { source: string; ai_generated?: boolean; tier?: string } };
    });
  const brollDone = async (taskId: string) => {
    await vi.waitFor(() => expect(brollUpdates(taskId).some((u) => u.done)).toBe(true), { timeout: 120_000, interval: 200 });
    return brollUpdates(taskId).at(-1)!;
  };
  const ask = (extra: Record<string, unknown>) => ({
    projectPath: path.join(tmp, "edit me.project.json"), kind: "image", prompt: "", search: "coffee", style: "realistic", source: "auto",
    duration: 2, position: "full", quality: "draft", exclude: [], newVersion: false, ...extra,
  });

  it("B-roll: your folder first, then another one, then AI (the fake WanGP); stock keys never leave Settings", async () => {
    const env = { ...process.env };
    process.env.PEXELS_API_KEY = ""; // never your real .env keys in the tests
    process.env.PIXABAY_API_KEY = "";
    const folder = path.join(tmp, "My B-roll");
    try {
      execFileSync(python, ["-c", `
import sys; sys.path.insert(0, ".")
from pathlib import Path
from tests import synthetic
d = Path(sys.argv[1]); (d / "coffee").mkdir(parents=True)
synthetic.make_image(d / "coffee" / "cup.png"); synthetic.make_image(d / "coffee" / "beans.png", color="black")
`, folder], { cwd: repo });
      fs.writeFileSync(path.join(folder, "notes.txt"), "x");
      await call("settings:set", { brollFolder: folder });
      const listed = (await call("library:list", "broll")) as { files: { name: string; group: string }[] };
      expect(listed.files.map((f) => [f.name, f.group])).toEqual([["beans.png", "coffee"], ["cup.png", "coffee"]]);

      const first = await brollDone((await call("broll:start", ask({}))) as string);
      expect(first.error).toBeUndefined();
      expect(first.result!.broll.source).toBe("library");
      expect(first.result!.media.kind).toBe("image");
      const second = await brollDone((await call("broll:start", ask({ exclude: [first.result!.file] }))) as string);
      expect(second.result!.broll.source).toBe("library");
      expect(second.result!.file).not.toBe(first.result!.file);

      const none = await brollDone((await call("broll:start", ask({ search: "-spaceship (typed text may start with a dash)", source: "library" }))) as string);
      expect(none.error).toMatch(/No B-roll found/);

      // AI: the fake WanGP set up above makes the picture (draft tier), one GPU job at a time.
      const madeId = (await call("broll:start", ask({ prompt: "a robot waving", search: "", style: "cartoon", source: "ai" }))) as string;
      const made = await brollDone(madeId);
      expect(made.error).toBeUndefined();
      expect(made.result!.broll).toMatchObject({ source: "ai", ai_generated: true });
      expect(fs.existsSync(made.result!.file)).toBe(true);
      expect(brollUpdates(madeId).map((u) => u.label).filter(Boolean)).toEqual(expect.arrayContaining(["Finding B-roll", "Making AI clips (draft)"]));
    } finally {
      process.env.PEXELS_API_KEY = env.PEXELS_API_KEY ?? "";
      process.env.PIXABAY_API_KEY = env.PIXABAY_API_KEY ?? "";
      if (env.PEXELS_API_KEY === undefined) delete process.env.PEXELS_API_KEY;
      if (env.PIXABAY_API_KEY === undefined) delete process.env.PIXABAY_API_KEY;
      await call("settings:set", { brollFolder: "" });
    }
  }, 300_000);
});
