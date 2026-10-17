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
    "--instruction-file", files.instructionFile,
  ];
  if (!job.auto && job.mode !== "apply") args.push("--no-render");
  if (job.mode === "followup" && job.planFile) args.push("--previous-plan", job.planFile);
  if (job.mode === "apply" && job.planFile) args.push("--plan-file", job.planFile);
  if (job.maxGenMinutes !== undefined) args.push("--max-generation-minutes", String(job.maxGenMinutes));
  if (job.maxAiClips !== undefined) args.push("--max-ai-clips", String(job.maxAiClips));
  if (settings.brollFolder) args.push("--broll-library", settings.brollFolder);
  if (!settings.useStock) args.push("--no-stock");
  if (job.graphics) args.push("--graphics", job.graphics);
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
