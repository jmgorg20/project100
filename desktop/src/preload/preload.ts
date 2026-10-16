// The only bridge between the window and the main process (contextIsolation + sandbox).
// Sandboxed preloads cannot load local modules: only type imports from ../shared.
import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from "electron";
import type { AppApi, BrollUpdate, ExportUpdate } from "../shared/api";
import type { GenTaskUpdate, Job, VideoHistory } from "../shared/types";

function listen<T>(channel: string, callback: (value: T) => void): () => void {
  const handler = (_event: IpcRendererEvent, value: T) => callback(value);
  ipcRenderer.on(channel, handler);
  return () => ipcRenderer.removeListener(channel, handler);
}

const api: AppApi = {
  platform: process.platform,
  pathForFile: (file) => webUtils.getPathForFile(file),
  getSettings: () => ipcRenderer.invoke("settings:get"),
  setSettings: (patch) => ipcRenderer.invoke("settings:set", patch),
  keysStatus: () => ipcRenderer.invoke("keys:status"),
  setKey: (provider, key) => ipcRenderer.invoke("keys:set", provider, key),
  clearKey: (provider) => ipcRenderer.invoke("keys:clear", provider),
  pickVideos: () => ipcRenderer.invoke("dialog:videos"),
  pickPhotos: () => ipcRenderer.invoke("dialog:photos"),
  addJobs: (requests) => ipcRenderer.invoke("jobs:add", requests),
  listJobs: () => ipcRenderer.invoke("jobs:list"),
  cancelJob: (id) => ipcRenderer.invoke("jobs:cancel", id),
  dismissJob: (id) => ipcRenderer.invoke("jobs:dismiss", id),
  applyPlan: (jobId, plan) => ipcRenderer.invoke("plan:apply", jobId, plan),
  history: (video) => ipcRenderer.invoke("history:get", video),
  undo: (video) => ipcRenderer.invoke("history:undo", video),
  redo: (video) => ipcRenderer.invoke("history:redo", video),
  estimate: (video, provider, instruction) => ipcRenderer.invoke("engine:estimate", video, provider, instruction),
  renderFrame: (projectFile, seconds) => ipcRenderer.invoke("engine:frame", projectFile, seconds),
  checkEngine: () => ipcRenderer.invoke("engine:check"),
  genStatus: (checkWangp) => ipcRenderer.invoke("gen:status", checkWangp),
  setWangp: (folder, python) => ipcRenderer.invoke("gen:setWangp", folder, python),
  setTier: (type, kind, tier) => ipcRenderer.invoke("gen:setTier", type, kind, tier),
  startBenchmark: (types) => ipcRenderer.invoke("gen:benchmark", types),
  startCompare: (type, prompt, seed) => ipcRenderer.invoke("gen:compare", type, prompt, seed),
  cancelGenTask: (taskId) => ipcRenderer.invoke("gen:cancel", taskId),
  onGenTask: (callback) => listen<GenTaskUpdate>("gen:task", callback),
  openPath: (path) => ipcRenderer.invoke("app:openPath", path),
  showInFolder: (path) => ipcRenderer.invoke("app:showInFolder", path),
  openProject: (path) => ipcRenderer.invoke("project:open", path),
  saveProject: (path, project) => ipcRenderer.invoke("project:save", path, project),
  pickProject: () => ipcRenderer.invoke("dialog:project"),
  pickMedia: () => ipcRenderer.invoke("dialog:media"),
  pickExportPath: (defaultPath) => ipcRenderer.invoke("dialog:exportPath", defaultPath),
  mediaInfo: (paths) => ipcRenderer.invoke("media:info", paths),
  peaks: (path) => ipcRenderer.invoke("media:peaks", path),
  thumbs: (path) => ipcRenderer.invoke("media:thumbs", path),
  startExport: (projectPath, options) => ipcRenderer.invoke("export:start", projectPath, options),
  cancelExport: (taskId) => ipcRenderer.invoke("export:cancel", taskId),
  onExport: (callback) => listen<ExportUpdate>("export:task", callback),
  getVocabulary: () => ipcRenderer.invoke("vocab:get"),
  setVocabulary: (v) => ipcRenderer.invoke("vocab:set", v),
  listLibrary: (kind) => ipcRenderer.invoke("library:list", kind),
  startBroll: (request) => ipcRenderer.invoke("broll:start", request),
  cancelBroll: (taskId) => ipcRenderer.invoke("broll:cancel", taskId),
  onBroll: (callback) => listen<BrollUpdate>("broll:task", callback),
  pickFolder: (title) => ipcRenderer.invoke("dialog:folder", title),
  saveRecording: (projectPath, data, extension) => ipcRenderer.invoke("media:saveRecording", projectPath, data, extension),
  retranscribe: (projectPath, start, end) => ipcRenderer.invoke("project:retranscribe", projectPath, start, end),
  onJobChanged: (callback) => listen<Job>("job:changed", callback),
  onHistoryChanged: (callback) => listen<VideoHistory>("history:changed", callback),
};

contextBridge.exposeInMainWorld("api", api);
