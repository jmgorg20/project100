// What the window can ask the main process (exposed as window.api by the preload script).
import type {
  BrollMeta, BrollStyle, ContentType, Cost, GenStatus, GenTaskUpdate, Job, JobRequest, KeyName, KeysStatus, Media, Plan, Project, Provider,
  Settings, VideoHistory,
} from "./types";

/** A warning from the engine's graphics check. */
export interface GraphicsIssue {
  clip: string;
  kind: string;
  severity: string;
  time: number;
  message: string;
  tl: string;
}

export interface OpenedProject {
  path: string;
  project?: Project;
  /** A copy made before the first edit in the app ("<name>.before-editing.project.json"). */
  backup?: string;
  error?: string;
}

/** A file's sound outline: one value (0-255) per 1/per_second of a second. */
export interface Peaks {
  duration: number;
  per_second: number;
  peaks: number[];
  has_audio?: boolean;
}

/** Small pictures along a video: one every `every` seconds of the source. */
export interface Thumbs {
  every: number;
  height: number;
  files: string[];
}

export interface ExportOptions {
  output: string;
  /** 1920 = 1080x1920, 1280 = 720x1280, 960 = 540x960. */
  height: 1920 | 1280 | 960;
  fps: 24 | 25 | 30 | 50 | 60;
  /** Lower = better quality and bigger file. */
  crf: number;
  speed: "veryfast" | "fast" | "medium" | "slow";
}

export interface LibraryFile {
  path: string;
  name: string;
  /** Folder inside the library ("" = top). */
  group: string;
}

/** Find or make one B-roll item: your library, then free stock, then AI (or only one source). */
export interface BrollRequest {
  projectPath: string;
  kind: "image" | "video";
  prompt: string;
  search: string;
  style: BrollStyle;
  source: "auto" | "library" | "stock" | "ai";
  duration: number;
  position: "full" | "top" | "center";
  /** AI generation: the quick draft tier, or the final tier. */
  quality: "draft" | "final";
  /** Files and stock ids (pexels-123) not to use again ("find another"). */
  exclude: string[];
  /** AI: a different version of the same prompt. */
  newVersion: boolean;
}

export interface BrollFound {
  file: string;
  media: Media;
  broll: BrollMeta;
  notes: string[];
}

export interface BrollUpdate {
  taskId: string;
  /** What the engine is doing now, e.g. "Finding B-roll", "Making AI clips (draft)". */
  label?: string;
  percent?: number;
  done?: boolean;
  result?: BrollFound;
  error?: string;
  cancelled?: boolean;
}

/** Can this PC follow hands and faces? (MediaPipe + the model files you downloaded.) */
export interface TrackStatus {
  available: boolean;
  installed: boolean;
  hands: boolean;
  face: boolean;
  pose: boolean;
  problems: string[];
  models: { kind: "hand" | "face" | "pose" | "segment"; file: string; url: string; page: string; size: string; path: string; present: boolean }[];
}

export interface TrackUpdate {
  taskId: string;
  label?: string;
  percent?: number;
  done?: boolean;
  /** Share of the tracked time each point was found (0-1). */
  found?: Record<string, number>;
  error?: string;
  cancelled?: boolean;
}

export interface ExportUpdate {
  taskId: string;
  percent?: number;
  done?: boolean;
  output?: string;
  error?: string;
  cancelled?: boolean;
}

export interface EstimateResult extends Partial<Cost> {
  text?: string;
  transcript_cached?: boolean;
  error?: string;
}

export interface EngineCheck {
  ok: boolean;
  message: string;
}

export interface AppApi {
  platform: string;
  /** The file's path on disk, for files dropped onto the window. */
  pathForFile(file: File): string;
  getSettings(): Promise<Settings>;
  setSettings(patch: Partial<Settings>): Promise<Settings>;
  keysStatus(): Promise<KeysStatus>;
  setKey(provider: KeyName, key: string): Promise<KeysStatus>;
  clearKey(provider: KeyName): Promise<KeysStatus>;
  pickVideos(): Promise<string[]>;
  pickPhotos(): Promise<string[]>;
  /** Files for a video format's role ("video" / "image" / "audio"). */
  pickFormatFiles(kinds: string[], multiple: boolean): Promise<string[]>;
  addJobs(requests: JobRequest[]): Promise<Job[]>;
  listJobs(): Promise<Job[]>;
  cancelJob(id: string): Promise<void>;
  dismissJob(id: string): Promise<void>;
  /** Render a reviewed plan (Auto mode off): only the accepted changes, no AI call. */
  applyPlan(jobId: string, plan: Plan): Promise<Job[]>;
  history(video: string): Promise<VideoHistory>;
  undo(video: string): Promise<VideoHistory>;
  redo(video: string): Promise<VideoHistory>;
  estimate(video: string, provider: Provider, instruction: string): Promise<EstimateResult>;
  renderFrame(projectFile: string, seconds: number): Promise<{ path?: string; error?: string }>;
  checkEngine(): Promise<EngineCheck>;
  /** Hardware, WanGP models and quality tiers. checkWangp starts WanGP to read its models. */
  genStatus(checkWangp: boolean): Promise<GenStatus | { error: string }>;
  setWangp(folder: string, python: string): Promise<{ problems?: string[]; error?: string }>;
  /** kind "default": your choice after Compare; "pin": always use this tier. null clears it. */
  setTier(type: ContentType, kind: "default" | "pin", tier: string | null): Promise<GenStatus | { error: string }>;
  startBenchmark(types: ContentType[]): Promise<string>;
  startCompare(type: ContentType, prompt: string, seed: number): Promise<string>;
  cancelGenTask(taskId: string): Promise<void>;
  onGenTask(callback: (update: GenTaskUpdate) => void): () => void;
  openPath(path: string): Promise<void>;
  showInFolder(path: string): Promise<void>;
  // ---- the timeline editor
  /** Read a project file (checked by the engine). */
  openProject(path: string): Promise<OpenedProject>;
  /** Write the project (atomically: a crash never leaves a half-written file). */
  saveProject(path: string, project: Project): Promise<{ ok: boolean; error?: string }>;
  pickProject(): Promise<string | null>;
  /** Videos, pictures and sound files to add to a project. */
  pickMedia(): Promise<string[]>;
  pickExportPath(defaultPath: string): Promise<string | null>;
  mediaInfo(paths: string[]): Promise<{ media: Media[]; errors: { path: string; message: string }[] }>;
  peaks(path: string): Promise<Peaks | { error: string }>;
  thumbs(path: string): Promise<Thumbs | { error: string }>;
  startExport(projectPath: string, options: ExportOptions): Promise<string>;
  cancelExport(taskId: string): Promise<void>;
  onExport(callback: (update: ExportUpdate) => void): () => void;
  // ---- captions, sound, effects
  /** Your words and corrections (vocabulary.json next to the editor engine). */
  getVocabulary(): Promise<{ words: string[]; corrections: { from: string; to: string }[] }>;
  setVocabulary(v: { words: string[]; corrections: { from: string; to: string }[] }): Promise<{ ok: boolean; error?: string }>;
  /** Sound files in your music or sound-effect folder, or pictures/videos in your B-roll folder. */
  listLibrary(kind: "music" | "sfx" | "broll"): Promise<{ folder: string; files: LibraryFile[]; error?: string }>;
  // ---- tracked effects (follow hands / face)
  trackStatus(): Promise<TrackStatus | { error: string }>;
  /** Find the points in the project's main video and save them in the project file. */
  startTrack(projectPath: string): Promise<string>;
  cancelTrack(taskId: string): Promise<void>;
  onTrack(callback: (update: TrackUpdate) => void): () => void;
  /** Download model files (only after the user confirmed: see TrackStatus.models for the sources). */
  downloadTrackModels(kinds: ("hand" | "face" | "pose" | "segment")[]): Promise<TrackStatus | { error: string }>;
  // ---- B-roll
  startBroll(request: BrollRequest): Promise<string>;
  cancelBroll(taskId: string): Promise<void>;
  onBroll(callback: (update: BrollUpdate) => void): () => void;
  pickFolder(title: string): Promise<string | null>;
  /** Save a voice-over recorded in the app next to the project; returns its path. */
  saveRecording(projectPath: string, data: Uint8Array, extension: string): Promise<{ path?: string; error?: string }>;
  /** Transcribe start-end (timeline seconds) again and replace the captions there (saves the project). */
  retranscribe(projectPath: string, start: number, end: number): Promise<{ project?: Project; words?: number; error?: string }>;
  /** Another look for one graphic (the engine saves the project): by rules, or asking the AI. */
  /** Storyboard: another look for one scene's graphics (or new ones); the engine saves the project. */
  storyboardRegenerate(projectPath: string, sceneId: string, useAi: boolean, provider: Provider): Promise<{ project?: Project; notes?: string[]; error?: string }>;
  graphicsRegenerate(projectPath: string, clipId: string, useAi: boolean, provider: Provider): Promise<{ project?: Project; error?: string }>;
  /** Graphics on the face, off the screen, on the captions, hard to read (before export). */
  graphicsCheck(projectPath: string): Promise<{ issues: GraphicsIssue[]; error?: string }>;
  onJobChanged(callback: (job: Job) => void): () => void;
  onHistoryChanged(callback: (history: VideoHistory) => void): () => void;
}

declare global {
  interface Window {
    api: AppApi;
  }
}
