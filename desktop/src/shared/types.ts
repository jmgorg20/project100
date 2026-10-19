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

/** Effects that follow a tracked hand / face / body (see docs/tracking.md). */
export type TrackEffect = "glow" | "spark" | "aura" | "energy" | "clip";
export type TrackPointKind = "palm" | "wrist" | "thumb_tip" | "index_tip" | "middle_tip" | "ring_tip" | "pinky_tip" | "fingertips" | "face" | "body";
export type TrackHand = "left" | "right" | "any";

/** One tracked point: samples at start + i / fps. x, y: 0-1 across the source frame; c: confidence; s: size. */
export interface TrackPoint {
  x: number[];
  y: number[];
  c: number[];
  s?: number[];
}

export interface TrackData {
  fps: number;
  start?: number;
  source?: string;
  swap_hands?: boolean;
  points: Record<string, TrackPoint>;
}

export interface Clip {
  id: string;
  type: "video" | "image" | "zoom" | "grade" | "caption" | "audio" | "fx" | "trackfx" | "graphic" | "wipe";
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
  /** A second video beside you (split) or in a corner window (pip); see autoedit/formats. */
  layout?: {
    type: "split" | "pip";
    screen: string;
    /** split: the other video's share of the height (0.3-0.7). */
    ratio?: number;
    corner?: "top_left" | "top_right" | "bottom_left" | "bottom_right";
    /** pip: your window's width as a share of the frame (0.2-0.6). */
    size?: number;
    border?: string;
    animated?: boolean;
    /** Seconds the second video starts later (negative: earlier). */
    offset?: number;
  };
  /** Overlay: cut the person out (Clone, Green screen) or key out a colour. */
  mask?: { type: "person" | "chroma"; color?: string; similarity?: number; blend?: number };
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
  effect?: FxEffect | TrackEffect;
  /** trackfx: what to follow, which hand, how big, how steady, colour, and (effect "clip") how your clip is blended. */
  point?: TrackPointKind;
  hand?: TrackHand;
  size?: number;
  smooth?: number;
  color?: string;
  blend?: "screen" | "alpha";
  // captions
  style?: string | number;
  highlight_keywords?: boolean;
  overrides?: Record<string, unknown>;
  words?: Word[];
  /** B-roll: where it came from (library, stock, AI). */
  broll?: BrollMeta;
  // motion graphics (x / y are then the centre as fractions of the frame, 0-1)
  template?: string;
  params?: GraphicParams;
  /** A flash / whip / punch-in on the picture when the graphic starts. */
  attach?: { kind: AttachKind; intensity?: number };
  /** A locked clip cannot be moved, changed or deleted (and the AI does not redo it). */
  locked?: boolean;
  /** Why the AI placed it (style, mood, the spoken words). */
  director?: { style?: string; mood?: string; words?: string; importance?: number; reason?: string; kind?: string };
  // before/after wipe
  direction?: "right" | "left" | "down" | "up";
  sweep?: number;
  stop?: number;
  divider?: boolean;
}

export type AttachKind = "flash" | "whip" | "punch";

/** What a graphics template shows (see autoedit/graphics_catalog.json for what each one uses). */
export interface GraphicParams {
  text?: string;
  text2?: string;
  items?: string[];
  number?: number;
  prefix?: string;
  suffix?: string;
  image?: string;
  emoji?: string;
  icon?: string;
  font?: string;
  color?: string;
  accent?: string;
  bg?: string;
  size?: number;
  intensity?: number;
  align?: "left" | "center" | "right";
  case?: "" | "upper" | "lower" | "title";
  angle?: number;
  dir?: "left" | "right" | "up" | "down";
}

export interface Track {
  id: string;
  kind: "video" | "overlay" | "effect" | "graphics" | "caption" | "audio";
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
  /** Tracked points per media id (the speaker's hands, face and body). */
  tracking?: Record<string, TrackData>;
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

/** An effect the AI attaches to the speaker's hand, face or body. */
export interface PlanTrackedEffect {
  effect: Exclude<TrackEffect, "clip">;
  point: Exclude<TrackPointKind, "middle_tip" | "ring_tip" | "pinky_tip">;
  hand: TrackHand;
  at: number;
  duration: number;
  intensity: number;
  color: string;
  size: number;
  reason: string;
}

/** A short effect the AI plans (on_cut = a transition on the nearest jump cut). */
export interface PlanEffect {
  effect: FxEffect;
  at: number;
  duration: number;
  intensity: number;
  on_cut: boolean;
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
  /** Older plans have none. */
  effects?: PlanEffect[];
  /** Older plans have none. */
  tracked_effects?: PlanTrackedEffect[];
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
  /** Something left out without stopping the edit (e.g. one graphic that could not be drawn). */
  | { type: "warning"; message: string; stage?: string; clip?: string; path?: string }
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
  /** Motion graphics: "auto" (when the instruction asks), "off", or a style name. */
  graphics?: string;
  /** A preset (Viral TikTok, ...): its look is the default; an explicit format or graphics style wins. */
  preset?: string;
  /** Video format id (Reaction, Listicle, ...) or "auto" (the AI picks); unset = from your words. */
  format?: string;
  /** The format's other files by role, e.g. { source: [...] }; Listicle items; start offsets. */
  formatInputs?: Record<string, string[]>;
  items?: string[];
  offsets?: Record<string, number>;
}

/** One preset, as `python editor.py ui-data` lists it. */
export interface PresetInfo {
  id: string;
  name: string;
  tl: string;
  about: string;
  about_tl: string;
  format: string | null;
  graphics: string;
}

/** One video format, as `python editor.py ui-data` lists it. */
export interface FormatInfo {
  id: string;
  name: string;
  tl: string;
  about: string;
  about_tl: string;
  inputs: { role: string; kinds: string[]; required: boolean; multiple?: boolean; max?: number; label: string; tl: string }[];
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
  /** What was left out (with the file and the reason), the edit still finished. */
  warnings?: string[];
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
