// Path helpers shared by the main process and the window (no Node modules: the window has none).

/** True for "C:\\x", "C:/x", "\\\\server\\x" and "/x". */
export function isAbsolutePath(p: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith("\\\\") || p.startsWith("/");
}

/** The folder part of a path (either kind of slash). */
export function dirName(p: string): string {
  const i = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return i <= 0 ? p.slice(0, i + 1) : p.slice(0, i);
}

export function baseName(p: string): string {
  return p.split(/[\\/]/).pop() ?? p;
}

/** A media path from a project file: relative paths start from the project's folder. */
export function resolveMediaPath(projectPath: string, mediaPath: string): string {
  if (isAbsolutePath(mediaPath)) return mediaPath;
  const sep = projectPath.includes("\\") && !projectPath.includes("/") ? "\\" : "/";
  return `${dirName(projectPath)}${sep}${mediaPath.replace(/[\\/]/g, sep)}`;
}

/** "C:\\Videos\\talk_edited.project.json" -> "C:\\Videos\\talk_edited_export.mp4" (next to it). */
export function exportPathFor(projectPath: string, n = 1): string {
  const base = projectPath.replace(/\.project\.json$/i, "").replace(/\.json$/i, "");
  return `${base}_export${n > 1 ? `_${n}` : ""}.mp4`;
}

/** "talk.project.json" -> "talk.before-editing.project.json" */
export function backupPathFor(projectPath: string): string {
  return projectPath.replace(/(\.project)?\.json$/i, "") + ".before-editing.project.json";
}
