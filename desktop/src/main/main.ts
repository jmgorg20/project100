// Electron main process: window, settings, encrypted keys, the job queue and the engine.
import { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } from "electron";
import * as fs from "node:fs";
import * as path from "node:path";
import { versionFromJob } from "../shared/jobs";
import type { EngineEvent, Job, JobRequest, Plan, Provider, Settings } from "../shared/types";
import { runEngine, type EngineConfig } from "./engine";
import { HistoryStore } from "./historyStore";
import { freeOutputPath, jobArgs, modelFor } from "./jobArgs";
import { KeyStore } from "./keys";
import { JobQueue } from "./queue";
import { defaultSettings, loadSettings, saveSettings } from "./settings";

const VIDEO_TYPES = ["mp4", "mov", "m4v", "mkv", "avi", "webm", "3gp"];
const PHOTO_TYPES = ["png", "jpg", "jpeg", "webp", "bmp"];

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

function engineConfig(): EngineConfig {
  return { python: settings.pythonPath, engineDir: settings.engineDir, env: keys.env() };
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
  Promise.race([queue.whenIdle(), new Promise((r) => setTimeout(r, 15_000))]).then(() => app.quit());
});
