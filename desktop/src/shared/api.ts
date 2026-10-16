// What the window can ask the main process (exposed as window.api by the preload script).
import type {
  ContentType, Cost, GenStatus, GenTaskUpdate, Job, JobRequest, KeysStatus, Plan, Provider, Settings, VideoHistory,
} from "./types";

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
  setKey(provider: Provider, key: string): Promise<KeysStatus>;
  clearKey(provider: Provider): Promise<KeysStatus>;
  pickVideos(): Promise<string[]>;
  pickPhotos(): Promise<string[]>;
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
  onJobChanged(callback: (job: Job) => void): () => void;
  onHistoryChanged(callback: (history: VideoHistory) => void): () => void;
}

declare global {
  interface Window {
    api: AppApi;
  }
}
