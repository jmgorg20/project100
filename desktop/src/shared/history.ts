// Version history per video: every finished AI edit is kept, so "Undo AI edit" is instant
// (no re-render) and "Redo" moves forward again. Pure functions; the main process stores it.
import type { VideoHistory, Version } from "./types";

export function emptyHistory(video: string): VideoHistory {
  return { video, versions: [], current: -1 };
}

/** Add a version and show it. Versions after the current one are kept (nothing is lost). */
export function addVersion(history: VideoHistory, version: Version): VideoHistory {
  const versions = [...history.versions, version];
  return { ...history, versions, current: versions.length - 1 };
}

export function canUndo(history: VideoHistory): boolean {
  return history.current >= 0;
}

export function canRedo(history: VideoHistory): boolean {
  return history.current < history.versions.length - 1;
}

/** Go back one AI edit; going back past the first shows the original video. */
export function undo(history: VideoHistory): VideoHistory {
  return canUndo(history) ? { ...history, current: history.current - 1 } : history;
}

export function redo(history: VideoHistory): VideoHistory {
  return canRedo(history) ? { ...history, current: history.current + 1 } : history;
}

export function currentVersion(history: VideoHistory): Version | null {
  return history.current >= 0 ? history.versions[history.current] ?? null : null;
}
