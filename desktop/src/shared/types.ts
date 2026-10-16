// Types shared by the Electron main process and the renderer.
// The Project shape mirrors autoedit/project.schema.json (only the parts the app reads).

export type Provider = "groq" | "anthropic";
/** Free stock sites for B-roll (your own free key). */
export type StockProvider = "pexels" | "pixabay";
export type KeyName = Provider | StockProvider;

export type BrollStyle = "realistic" | "cartoon" | "drawing" | "low_poly" | "stylized_3d" | "anime";
export type BrollSource = "library" | "pexels" | "pixabay" | "ai" | "file";

/** Where a B-roll clip came from (autoedit/project.schema.json, $defs/broll). */
export interface BrollMeta {
  source: BrollSource;
  kind?: "image" | "video";
  prompt?: string;
  search?: string;
  style?: BrollStyle;
  position?: "full" | "top" | "center";
  /** Made with AI: label it where the platform asks. */
  ai_generated?: boolean;
  tier?: string;
  stock_id?: string;
  author?: string;
  page?: string;
  license?: string;
  license_url?: string;
  credit?: string;
}

export interface Word {
  text: string;
  start: number;
  end: number;
  highlight?: boolean;
}

export type FxEffect = "shake" | "flash" | "dip" | "glitch" | "whip";

export interface Clip {
  id: string;
  type: "video" | "image" | "zoom" | "grade" | "caption" | "audio" | "fx";
  start: number;
  duration: number;
  media?: string;
  in?: number;
  out?: number;
  volume?: number;
  fit?: "fill" | "blur";
  label?: string;
  /** Playback speed (0.25-4): the clip shows (out - in) / speed seconds of the source. */
  speed?: number;
  fade_in?: number;
  fade_out?: number;
  /** Reframe for "fill": zoom (1-4) and which part stays in view (0 = left/top, 1 = right/bottom). */
  crop?: { zoom?: number; x?: number; y?: number };
  layout?: { type: "split" | "pip"; screen: string };
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
  /** Zoom: seconds to grow smoothly from 100% (0 = jump in). */
  ease?: number;
  grade?: string;
  /** Grade and fx: 0-1. */
  intensity?: number;
  effect?: FxEffect;
  // captions
  style?: string | number;
  highlight_keywords?: boolean;
  overrides?: Record<string, unknown>;
  words?: Word[];
  /** B-roll: where it came from (library, stock, AI). */
  broll?: BrollMeta;
}

export interface Track {
  id: string;
  kind: "video" | "overlay" | "effect" | "caption" | "audio";
  name?: string;
  role?: string;
  muted?: boolean;
  hidden?: boolean;
  locked?: boolean;
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
  settings: {
    width: number;
    height: number;
    fps: number;
    background?: string;
    audio?: { normalize?: boolean; loudness?: number; true_peak?: number; ducking?: number; denoise?: number };
    fonts?: Record<string, string>;
  };
  media: Media[];
  tracks: Track[];
  transcript?: unknown;
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

/** B-roll the AI plans: from your library, free stock, or made with AI (WanGP). */
export interface PlanAiClip {
  kind: "image" | "video";
  prompt: string;
  search?: string;
  style?: BrollStyle;
  source?: "auto" | "library" | "stock" | "ai";
  at: number;
  duration: number;
  position: "full" | "top" | "center";
  reason: string;
}

export interface PlanVoiceover {
  text: string;
  at: number;
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
  ai_clips?: PlanAiClip[];
  voiceovers?: PlanVoiceover[];
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
  /** Per video: stop AI generation after this many minutes / make at most this many clips. */
  maxGenMinutes?: number;
  maxAiClips?: number;
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
  /** Your own music and sound-effect folders (the app never ships music). */
  musicFolder: string;
  sfxFolder: string;
  /** Your own B-roll clips and pictures (file and folder names say what they show). */
  brollFolder: string;
  /** Search Pexels/Pixabay for B-roll when a key is saved. */
  useStock: boolean;
}

export interface KeyStatus {
  set: boolean;
  hint: string;
}

export interface KeysStatus {
  encryptionAvailable: boolean;
  groq: KeyStatus;
  anthropic: KeyStatus;
  pexels: KeyStatus;
  pixabay: KeyStatus;
}

// ---------------------------------------------------------------- AI generation (WanGP)

export type ContentType = "image" | "video" | "voice";
export const CONTENT_TYPES: ContentType[] = ["image", "video", "voice"];

export interface BenchmarkResult {
  success: boolean;
  reason: string;
  seconds: number;
  peak_vram_mb: number | null;
  out_of_memory: boolean;
  error: string;
  date: string;
  wangp_version?: string;
}

export interface TierRow {
  name: string;
  label: string;
  template: string;
  vram_gb: number | null;
  model_type: string | null;
  model_name: string | null;
  installed: boolean;
  status: string;
  disabled_reason: string | null;
  links: string[];
  avg_seconds: number | null;
  runs: number;
  benchmark: BenchmarkResult | null;
}

export interface HardwareProfile {
  gpus: { name: string; vram_mb: number | null; driver: string | null; source: string }[];
  ram_mb: number | null;
  disk_free_mb: Record<string, number | null>;
  os: string;
  detected_at: string;
  key: string;
  notes: string[];
}

export interface GenStatus {
  settings_file: string;
  templates_folder: string;
  problems: string[];
  setup_problems: string[];
  wangp: { folder: string; python: string; version: string | null; checked_at: string | null; error: string | null };
  hardware: HardwareProfile;
  hardware_summary: string;
  hardware_changed: boolean;
  previous_hardware: string | null;
  tiers: Record<ContentType, TierRow[]>;
  choices: Record<ContentType, { preview: string | null; order: string[] }>;
  recommendations: Record<
    ContentType,
    { tier: string | null; tier_seconds: number | null; could_download: { model_type: string; name: string; family: string | null; status: string; links: string[] }[] }
  >;
  default_tier: Record<ContentType, string | null>;
  pinned_tier: Record<ContentType, string | null>;
  limits: { max_generation_minutes: number; max_ai_clips: number; job_timeout_minutes: number };
}

export interface CompareResult {
  tier: string;
  label: string;
  model_name: string | null;
  success: boolean;
  reason: string;
  seconds: number;
  peak_vram_mb: number | null;
  error: string;
  output: string | null;
}

/** An event from a benchmark or compare run (engine JSON lines), or its end. */
export interface GenTaskUpdate {
  taskId: string;
  event?: { type: string; [key: string]: unknown };
  done?: boolean;
  code?: number | null;
  cancelled?: boolean;
  startError?: string;
}
