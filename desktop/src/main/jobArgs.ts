// Command-line arguments for one AI edit job, and a free output file name.
import * as fs from "node:fs";
import * as path from "node:path";
import type { Job, Settings } from "../shared/types";

export function modelFor(settings: Settings, provider: Job["provider"]): string {
  return provider === "anthropic" ? settings.anthropicModel : settings.groqModel;
}

export function jobArgs(job: Job, settings: Settings, files: { instructionFile: string; output: string }): string[] {
  const args = [
    "ai-edit", job.video,
    "--output", files.output,
    "--provider", job.provider,
    "--model", modelFor(settings, job.provider),
    "--transcribe-with", settings.transcribeWith,
    "--caption-punctuation", settings.captionPunctuation ?? "remove",
    ...(settings.captionStyle && settings.captionStyle !== "preset" ? ["--caption-style", settings.captionStyle] : []),
    ...(settings.soundEffects === "off" ? ["--sfx", "off"] : []),
    ...(settings.faceFinder === "off" ? ["--face-finder", "off"] : []),
    ...(settings.soundEffectsVolume !== undefined && settings.soundEffectsVolume !== 0.35 ? ["--sfx-volume", String(settings.soundEffectsVolume)] : []),
    "--instruction-file", files.instructionFile,
  ];
  if (!job.auto && job.mode !== "apply") args.push("--no-render");
  if (job.mode === "followup" && job.planFile) args.push("--previous-plan", job.planFile);
  if (job.mode === "apply" && job.planFile) args.push("--plan-file", job.planFile);
  if (job.maxGenMinutes !== undefined) args.push("--max-generation-minutes", String(job.maxGenMinutes));
  if (job.maxAiClips !== undefined) args.push("--max-ai-clips", String(job.maxAiClips));
  if (settings.brollFolder) args.push("--broll-library", settings.brollFolder);
  if (!settings.useStock) args.push("--no-stock");
  if (job.preset) args.push("--preset", job.preset);
  // With a preset, "auto" graphics means the preset's own style (the engine then decides).
  if (job.graphics && !(job.preset && job.graphics === "auto")) args.push("--graphics", job.graphics);
  if (job.format) args.push("--format", job.format);
  for (const [role, files] of Object.entries(job.formatInputs ?? {})) {
    for (const file of files) args.push("--input", `${role}=${file}`);
  }
  for (const item of job.items ?? []) if (item.trim()) args.push("--item", item.trim());
  for (const [role, seconds] of Object.entries(job.offsets ?? {})) {
    if (seconds) args.push("--offset", `${role}=${seconds}`);
  }
  if (job.transcriptFile) args.push("--transcript", job.transcriptFile);
  if (job.photos.length) args.push("--photos", ...job.photos);
  return args;
}

/** `<name>_ai.mp4`, or `<name>_ai_2.mp4`... if that (or its project file) exists or is taken. */
export function freeOutputPath(folder: string, video: string, taken: Set<string>): string {
  const stem = path.basename(video, path.extname(video));
  for (let n = 1; ; n++) {
    const candidate = path.join(folder, `${stem}_ai${n === 1 ? "" : `_${n}`}.mp4`);
    const projectFile = candidate.replace(/\.mp4$/, ".project.json");
    if (!taken.has(candidate) && !fs.existsSync(candidate) && !fs.existsSync(projectFile)) return candidate;
  }
}
