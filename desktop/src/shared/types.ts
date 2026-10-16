// Types shared by the Electron main process and the renderer.
// The Project shape mirrors autoedit/project.schema.json (only the parts the app reads).

export type Provider = "groq" | "anthropic";

export interface Word {
  text: string;
  start: number;
  end: number;
  highlight?: boolean;
}

export interface Clip {
  id: string;
  type: "video" | "image" | "zoom" | "grade" | "caption" | "audio";
  start: number;
  duration: number;
  media?: string;
  in?: number;
  out?: number;
  volume?: number;
  fit?: "fill" | "blur";
  // overlay
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  opacity?: number;
  animation?: "none" | "pop";
  // effects
  amount?: number;
  anchor_y?: number;
  grade?: string;
  // captions
  style?: string | number;
  highlight_keywords?: boolean;
  overrides?: Record<string, unknown>;
  words?: Word[];
}

export interface Track {
  id: string;
  kind: "video" | "overlay" | "effect" | "caption" | "audio";
  name?: string;
  role?: string;
  muted?: boolean;
  hidden?: boolean;
  clips: Clip[];
}

export interface Media {
  id: string;
  kind: "video" | "image" | "audio";
  path: string;
  name?: string;
  duration: number;
  width?: number;
  height?: number;
  has_audio?: boolean;
}

export interface Project {
  format: "autoedit-project";
  version: number;
  name?: string;
  settings: { width: number; height: number; fps: number; background?: string };
  media: Media[];
  tracks: Track[];
  meta?: Record<string, unknown>;
}

export interface PlanRange {
  start: number;
  end: number;
  reason?: string;
  amount?: number;
  grade?: string;
}

export interface PlanPhoto {
  file: string;
  at: number;
  duration: number;
  position: "top" | "center";
  reason: string;
}

export interface Plan {
  summary: string;
  style: string;
  grade: string;
  pacing: { silence_threshold: number; remove_fillers: boolean };
  zoom: { enabled: boolean; amount: number };
  captions: {
    enabled: boolean;
    size_scale: number;
    position: "lower" | "center" | "top" | null;
    highlight_words: string[];
  };
  cuts: PlanRange[];
  zooms: PlanRange[];
  grades: PlanRange[];
  photos: PlanPhoto[];
  notes: string[];
}

export interface Cost {
  transcription: number | null;
  plan: number | null;
  total: number | null;
  currency: "USD";
  provider: Provider;
  model: string;
  paid_provider: boolean;
  usage?: { input_tokens: number; output_tokens: number };
  transcript_cached?: boolean;
  plan_cached?: boolean;
}

export interface Summary {
  headline: string;
  details: string[];
  fallback: boolean;
  duration_before: number;
  duration_after: number;
  cost?: Cost;
  cost_text?: string;
}

/** One JSON line from `python editor.py --json ...`. */
export type EngineEvent =
  | { type: "stage"; stage: string; label: string }
  | { type: "progress"; stage: string; percent: number }
  | { type: "log"; message: string; stream?: "stderr" }
  | { type: "transcript"; words: number; cached: boolean; text: string }
  | {
      type: "plan";
      plan: Plan;
      fallback: boolean;
      reason: string;
      cached: boolean;
      given: boolean;
      model: string | null;
      cost: number | null;
      attempts: { attempt: number; problems: string[] }[];
      baseline: Plan;
    }
  | { type: "project"; stage: string; project: Project }
  | ({ type: "summary" } & Summary)
  | { type: "item"; index: number; total: number; video: string }
  | { type: "item_error"; index: number; video: string; message: string }
  | { type: "result"; [key: string]: unknown }
  | { type: "error"; message: string }
  | { type: "cancelled" };

export type JobMode = "new" | "followup" | "apply";
export type JobStatus = "queued" | "running" | "review" | "done" | "failed" | "cancelled" | "dismissed";

export interface JobRequest {
  video: string;
  photos: string[];
  instruction: string;
  provider: Provider;
  auto: boolean;
  mode: JobMode;
  /** followup: the plan file to change; apply: the plan to use as is. */
  planFile?: string;
}

export interface Job extends JobRequest {
  id: string;
  status: JobStatus;
  stage?: string;
  stageLabel?: string;
  percent?: number;
  stagesDone: string[];
  transcriptWords?: number;
  transcriptCached?: boolean;
  plan?: Plan;
  /** The preset edit's plan: what each AI change is compared with in the review list. */
  planBaseline?: Plan;
  planFallback?: boolean;
  planReason?: string;
  planCached?: boolean;
  project?: Project;
  summary?: Summary;
  output?: string;
  projectFile?: string;
  planFileOut?: string;
  error?: string;
  log: string[];
  createdAt: number;
}

export interface Version {
  id: string;
  jobId: string;
  instruction: string;
  mode: JobMode;
  output: string;
  projectFile: string;
  planFile: string;
  summary?: Summary;
  createdAt: number;
}

export interface VideoHistory {
  video: string;
  versions: Version[];
  /** Index into versions of what is shown; -1 = the original video (no AI edit). */
  current: number;
}

export interface Settings {
  pythonPath: string;
  engineDir: string;
  outputDir: string;
  provider: Provider;
  groqModel: string;
  anthropicModel: string;
  transcribeWith: "groq" | "local";
  autoMode: boolean;
  consentAccepted: boolean;
}

export interface KeyStatus {
  set: boolean;
  hint: string;
}

export interface KeysStatus {
  encryptionAvailable: boolean;
  groq: KeyStatus;
  anthropic: KeyStatus;
}
