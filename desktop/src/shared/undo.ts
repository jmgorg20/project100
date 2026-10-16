// Undo/redo for the timeline editor: a list of whole projects (edits are pure, so each step
// is just the previous value). Changes made in quick succession with the same key (dragging a
// slider) become one step.

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  lastKey?: string;
  lastAt?: number;
}

export const UNDO_LIMIT = 200;
export const COALESCE_MS = 1000;

export function createHistory<T>(present: T): History<T> {
  return { past: [], present, future: [] };
}

export function pushHistory<T>(h: History<T>, next: T, key?: string, now = Date.now()): History<T> {
  if (next === h.present) return h;
  const merge = key !== undefined && key === h.lastKey && h.lastAt !== undefined && now - h.lastAt < COALESCE_MS;
  const past = merge ? h.past : [...h.past, h.present].slice(-UNDO_LIMIT);
  return { past, present: next, future: [], lastKey: key, lastAt: now };
}

export function undoHistory<T>(h: History<T>): History<T> {
  if (!h.past.length) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1], future: [h.present, ...h.future] };
}

export function redoHistory<T>(h: History<T>): History<T> {
  if (!h.future.length) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) };
}
