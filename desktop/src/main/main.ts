// Electron main process: window, settings, encrypted keys, the job queue and the engine.
import { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } from "electron";
import * as fs from "node:fs";
import * as path from "node:path";
import type { ExportOptions, ExportUpdate } from "../shared/api";
import { versionFromJob } from "../shared/jobs";
import { backupPathFor } from "../shared/paths";
import type { ContentType, EngineEvent, Job, JobRequest, Plan, Project, Provider, Settings } from "../shared/types";
import { runEngine, type EngineConfig, type RunHandle } from "./engine";
import { HistoryStore } from "./historyStore";
import { freeOutputPath, jobArgs, modelFor } from "./jobArgs";
import { KeyStore } from "./keys";
import { JobQueue } from "./queue";
import { defaultSettings, loadSettings, saveSettings } from "./settings";

const VIDEO_TYPES = ["mp4", "mov", "m4v", "mkv", "avi", "webm", "3gp"];
const PHOTO_TYPES = ["png", "jpg", "jpeg", "webp", "bmp"];
const AUDIO_TYPES = ["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "wma"];

const dataDir = () => app.getPath("userData");
const settingsFile = () => path.join(dataDir(), "settings.json");
// In development the engine is the repository this app lives in (desktop/..).
const defaultEngineDir = () => path.resolve(app.getAppPath(), "..");

let window: BrowserWindow | null = null;
let settings: Settings;
let keys: KeyStore;
let history: HistoryStore;
let queue: JobQueue;
const takenOutputs = new Set<string>();
const genTasks = new Map<string, RunHandle>();
let genCounter = 0;
const exportTasks = new Map<string, RunHandle>();
const peaksCache = new Map<string, unknown>();
const thumbsCache = new Map<string, unknown>();

// After "cancel", the engine gets this long to stop by itself before it is killed. It must be
// longer than the engine's own wait for WanGP to stop a job (Bridge.STOP_GRACE, 60 s), so the
// engine always closes WanGP itself: a killed engine could leave WanGP running on the GPU.
const ENGINE_STOP_GRACE_MS = 90_000;

function engineConfig(): EngineConfig {
  return { python: settings.pythonPath, engineDir: settings.engineDir, env: keys.env(), graceMs: ENGINE_STOP_GRACE_MS };
}

function send(channel: string, payload: unknown): void {
  if (window && !window.isDestroyed()) window.webContents.send(channel, payload);
}

function runJob(job: Job, onEvent: (event: EngineEvent) => void) {
  const jobDir = path.join(dataDir(), "jobs", job.id);
  fs.mkdirSync(jobDir, { recursive: true });
  const instructionFile = path.join(jobDir, "instruction.txt");
  fs.writeFileSync(instructionFile, job.instruction, "utf-8");
  fs.mkdirSync(settings.outputDir, { recursive: true });
  const output = freeOutputPath(settings.outputDir, job.video, takenOutputs);
  takenOutputs.add(output);
  const handle = runEngine(engineConfig(), jobArgs(job, settings, { instructionFile, output }), onEvent);
  handle.done.finally(() => takenOutputs.delete(output));
  return handle;
}

/** Run a short engine command and return its last JSON "result" (or the error). */
function engineOnce(args: string[]): Promise<{ result?: Record<string, unknown>; error?: string }> {
  return new Promise((resolve) => {
    let result: Record<string, unknown> | undefined;
    let error: string | undefined;
    const handle = runEngine(engineConfig(), args, (event) => {
      if (event.type === "result") result = event;
      if (event.type === "error") error = event.message;
    });
    handle.done.then((r) => resolve(r.startError ? { error: r.startError } : { result, error }));
  });
}

/** A benchmark or compare run: engine events go to the window; one at a time per task id. */
function startGenTask(args: string[]): string {
  const taskId = `gen${++genCounter}`;
  const handle = runEngine(engineConfig(), args, (event) => send("gen:task", { taskId, event }));
  genTasks.set(taskId, handle);
  handle.done.then((r) => {
    genTasks.delete(taskId);
    send("gen:task", { taskId, done: true, code: r.code, cancelled: r.cancelled, startError: r.startError });
  });
  return taskId;
}

/** Write a file atomically: a crash or power cut never leaves a half-written project. */
export function writeAtomic(file: string, text: string): void {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, text, "utf-8");
  fs.renameSync(tmp, file);
}

function startExport(projectPath: string, o: ExportOptions): string {
  const taskId = `export${++genCounter}`;
  const args = ["render", projectPath, "--output", o.output, "--height", String(o.height), "--fps", String(o.fps), "--crf", String(o.crf), "--speed", o.speed];
  const update = (u: Omit<ExportUpdate, "taskId">) => send("export:task", { taskId, ...u });
  let error: string | undefined;
  let output: string | undefined;
  const handle = runEngine(engineConfig(), args, (event) => {
    if (event.type === "progress") update({ percent: event.percent });
    if (event.type === "result" && typeof event.output === "string") output = event.output;
    if (event.type === "error") error = event.message;
  });
  exportTasks.set(taskId, handle);
  handle.done.then((r) => {
    exportTasks.delete(taskId);
    if (r.cancelled) update({ done: true, cancelled: true });
    else if (r.startError || error || r.code !== 0) update({ done: true, error: r.startError ?? error ?? `The export stopped (exit code ${r.code}).` });
    else update({ done: true, percent: 100, output });
  });
  return taskId;
}

async function cachedEngine(cache: Map<string, unknown>, args: string[], key: string) {
  if (cache.has(key)) return cache.get(key);
  const r = await engineOnce(args);
  if (r.error || !r.result) return { error: r.error ?? "No answer from the editor engine." };
  const { type: _type, ...data } = r.result;
  cache.set(key, data);
  return data;
}

async function genStatus(check: boolean) {
  const r = await engineOnce(["gen-status", ...(check ? ["--check-wangp"] : [])]);
  return r.error || !r.result ? { error: r.error ?? "No answer from the editor engine." } : r.result;
}

function registerIpc(): void {
  ipcMain.handle("settings:get", () => settings);
  ipcMain.handle("settings:set", (_e, patch: Partial<Settings>) => {
    settings = { ...settings, ...patch };
    saveSettings(settingsFile(), settings);
    return settings;
  });
  ipcMain.handle("keys:status", () => keys.status());
  ipcMain.handle("keys:set", (_e, provider: Provider, key: string) => {
    keys.set(provider, key);
    return keys.status();
  });
  ipcMain.handle("keys:clear", (_e, provider: Provider) => {
    keys.clear(provider);
    return keys.status();
  });
  ipcMain.handle("dialog:videos", async () => {
    const r = await dialog.showOpenDialog(window!, {
      title: "Choose videos",
      properties: ["openFile", "multiSelections"],
      filters: [{ name: "Videos", extensions: VIDEO_TYPES }],
    });
    return r.canceled ? [] : r.filePaths;
  });
  ipcMain.handle("dialog:photos", async () => {
    const r = await dialog.showOpenDialog(window!, {
      title: "Choose photos the AI may use",
      properties: ["openFile", "multiSelections"],
      filters: [{ name: "Photos", extensions: PHOTO_TYPES }],
    });
    return r.canceled ? [] : r.filePaths;
  });
  ipcMain.handle("jobs:add", (_e, requests: JobRequest[]) => queue.add(requests));
  ipcMain.handle("jobs:list", () => queue.jobs);
  ipcMain.handle("jobs:cancel", (_e, id: string) => queue.cancel(id));
  ipcMain.handle("jobs:dismiss", (_e, id: string) => queue.dismiss(id));
  ipcMain.handle("plan:apply", (_e, jobId: string, plan: Plan) => {
    const job = queue.get(jobId);
    if (!job) throw new Error("That edit is no longer in the list.");
    const planFile = path.join(dataDir(), "jobs", jobId, "accepted.plan.json");
    fs.writeFileSync(planFile, JSON.stringify({ plan }, null, 1), "utf-8");
    queue.dismiss(jobId);
    const request: JobRequest = {
      video: job.video,
      photos: job.photos,
      instruction: job.instruction,
      provider: job.provider,
      auto: true,
      mode: "apply",
      planFile,
      maxGenMinutes: job.maxGenMinutes,
      maxAiClips: job.maxAiClips,
    };
    return queue.add([request]);
  });
  ipcMain.handle("history:get", (_e, video: string) => history.get(video));
  ipcMain.handle("history:undo", (_e, video: string) => history.undo(video));
  ipcMain.handle("history:redo", (_e, video: string) => history.redo(video));
  ipcMain.handle("engine:estimate", async (_e, video: string, provider: Provider, instruction: string) => {
    const r = await engineOnce(["estimate", video, "--provider", provider, "--model", modelFor(settings, provider), "-i", instruction]);
    if (r.error || !r.result) return { error: r.error ?? "No estimate." };
    const items = r.result.items as Record<string, unknown>[];
    return items[0];
  });
  ipcMain.handle("engine:frame", async (_e, projectFile: string, seconds: number) => {
    const out = path.join(dataDir(), "frames", `frame-${Date.now()}.png`);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    const r = await engineOnce(["frame", projectFile, "--time", String(seconds), "--output", out]);
    return r.error ? { error: r.error } : { path: out };
  });
  ipcMain.handle("gen:status", (_e, check: boolean) => genStatus(Boolean(check)));
  ipcMain.handle("gen:setWangp", async (_e, folder: string, python: string) => {
    const r = await engineOnce(["gen-config", "--wangp-folder", folder, "--wangp-python", python]);
    return r.error ? { error: r.error } : { problems: (r.result?.problems as string[]) ?? [] };
  });
  ipcMain.handle("gen:setTier", async (_e, type: ContentType, kind: "default" | "pin", tier: string | null) => {
    const flag = kind === "default" ? (tier ? ["--default", tier] : ["--clear-default"]) : tier ? ["--pin", tier] : ["--unpin"];
    const r = await engineOnce(["set-tier", "--type", type, ...flag]);
    return r.error ? { error: r.error } : genStatus(false);
  });
  ipcMain.handle("gen:benchmark", (_e, types: ContentType[]) => startGenTask(["benchmark", ...(types.length ? ["--type", ...types] : [])]));
  ipcMain.handle("gen:compare", (_e, type: ContentType, prompt: string, seed: number) =>
    startGenTask(["compare", "--type", type, "--prompt", prompt, "--seed", String(seed)]),
  );
  ipcMain.handle("gen:cancel", (_e, taskId: string) => genTasks.get(taskId)?.cancel());
  ipcMain.handle("app:openPath", (_e, target: string) => shell.openPath(target));
  ipcMain.handle("app:showInFolder", (_e, target: string) => shell.showItemInFolder(target));
  // ---- timeline editor
  ipcMain.handle("project:open", async (_e, file: string) => {
    let project: Project;
    try {
      project = JSON.parse(fs.readFileSync(file, "utf-8"));
    } catch (err) {
      return { path: file, error: `Could not open the project: ${(err as Error).message}` };
    }
    const check = await engineOnce(["validate", file]);
    if (check.error) return { path: file, error: check.error };
    const backup = backupPathFor(file);
    try {
      if (!fs.existsSync(backup)) fs.copyFileSync(file, backup);
    } catch {
      // read-only folder: editing still works, there is just no backup
    }
    return { path: file, project, backup: fs.existsSync(backup) ? backup : undefined };
  });
  ipcMain.handle("project:save", (_e, file: string, project: Project) => {
    if (!/\.json$/i.test(file)) return { ok: false, error: "Projects are saved as .project.json files." };
    try {
      writeAtomic(file, JSON.stringify(project, null, 1) + "\n");
      return { ok: true };
    } catch (err) {
      return { ok: false, error: `Could not save: ${(err as Error).message}` };
    }
  });
  ipcMain.handle("dialog:project", async () => {
    const r = await dialog.showOpenDialog(window!, {
      title: "Open a project",
      properties: ["openFile"],
      filters: [{ name: "Projects", extensions: ["json"] }],
    });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle("dialog:media", async () => {
    const r = await dialog.showOpenDialog(window!, {
      title: "Add videos, pictures or sound",
      properties: ["openFile", "multiSelections"],
      filters: [{ name: "Media", extensions: [...VIDEO_TYPES, ...PHOTO_TYPES, ...AUDIO_TYPES] }],
    });
    return r.canceled ? [] : r.filePaths;
  });
  ipcMain.handle("dialog:exportPath", async (_e, defaultPath: string) => {
    const r = await dialog.showSaveDialog(window!, { title: "Export video", defaultPath, filters: [{ name: "MP4 video", extensions: ["mp4"] }] });
    return r.canceled || !r.filePath ? null : r.filePath;
  });
  ipcMain.handle("media:info", async (_e, paths: string[]) => {
    const r = await engineOnce(["media-info", ...paths]);
    if (r.error || !r.result) return { media: [], errors: paths.map((p) => ({ path: p, message: r.error ?? "No answer from the editor engine." })) };
    return { media: r.result.media, errors: r.result.errors };
  });
  ipcMain.handle("media:peaks", (_e, file: string) => cachedEngine(peaksCache, ["peaks", file], file));
  ipcMain.handle("media:thumbs", (_e, file: string) => cachedEngine(thumbsCache, ["thumbs", file], file));
  ipcMain.handle("export:start", (_e, projectPath: string, options: ExportOptions) => startExport(projectPath, options));
  ipcMain.handle("export:cancel", (_e, taskId: string) => exportTasks.get(taskId)?.cancel());
  ipcMain.handle("engine:check", async () => {
    const r = await engineOnce(["validate", path.join(settings.engineDir, "examples", "project.json")]);
    return r.error ? { ok: false, message: r.error } : { ok: true, message: "The editor engine is ready." };
  });
}

function createWindow(): void {
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: "Auto Video Editor",
    backgroundColor: "#f5f5f7",
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // The dev server is http://, which may not show local file:// videos. Only in development.
      webSecurity: !devUrl,
    },
  });
  // Links open in the browser, never inside the app.
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event) => event.preventDefault());
  if (devUrl) window.loadURL(devUrl);
  else window.loadFile(path.join(__dirname, "..", "..", "dist", "renderer", "index.html"));
  window.on("closed", () => (window = null));
}

app.whenReady().then(() => {
  settings = loadSettings(settingsFile(), defaultSettings(process.platform, defaultEngineDir()));
  keys = new KeyStore(path.join(dataDir(), "keys.json"), safeStorage);
  history = new HistoryStore(path.join(dataDir(), "history.json"));
  queue = new JobQueue({
    run: runJob,
    onChange: (job) => send("job:changed", job),
    onFinished: (job) => {
      const version = versionFromJob(job);
      if (version) send("history:changed", history.add(job.video, version));
    },
  });
  registerIpc();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Stop any running render cleanly before quitting, so no FFmpeg is left behind.
let quitting = false;
app.on("before-quit", (event) => {
  if (quitting || !queue) return;
  quitting = true;
  event.preventDefault();
  queue.cancelAll();
  genTasks.forEach((handle) => handle.cancel());
  exportTasks.forEach((handle) => handle.cancel());
  Promise.race([queue.whenIdle(), new Promise((r) => setTimeout(r, 15_000))]).then(() => app.quit());
});
