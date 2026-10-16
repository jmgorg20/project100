// Keyboard shortcuts of the timeline editor (CapCut-like). Pure: key event -> action name.

export type Action =
  | "play"
  | "split"
  | "delete"
  | "undo"
  | "redo"
  | "frameBack"
  | "frameForward"
  | "secondBack"
  | "secondForward"
  | "prevEdit"
  | "nextEdit"
  | "home"
  | "end"
  | "zoomIn"
  | "zoomOut"
  | "zoomFit"
  | "snapping"
  | "save"
  | "export"
  | "deselect"
  | "help";

export interface KeyLike {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

export function actionFor(e: KeyLike): Action | null {
  const mod = Boolean(e.ctrlKey || e.metaKey);
  const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (mod) {
    if (k === "z") return e.shiftKey ? "redo" : "undo";
    if (k === "y") return "redo";
    if (k === "b") return "split";
    if (k === "s") return "save";
    if (k === "e") return "export";
    if (k === "0") return "zoomFit";
    if (k === "=" || k === "+") return "zoomIn";
    if (k === "-") return "zoomOut";
    return null;
  }
  if (e.altKey) return null;
  switch (k) {
    case " ":
    case "k":
      return "play";
    case "s":
      return "split";
    case "Delete":
    case "Backspace":
      return "delete";
    case "ArrowLeft":
      return e.shiftKey ? "secondBack" : "frameBack";
    case "ArrowRight":
      return e.shiftKey ? "secondForward" : "frameForward";
    case "ArrowUp":
      return "prevEdit";
    case "ArrowDown":
      return "nextEdit";
    case "Home":
      return "home";
    case "End":
      return "end";
    case "=":
    case "+":
      return "zoomIn";
    case "-":
      return "zoomOut";
    case "n":
      return "snapping";
    case "Escape":
      return "deselect";
    case "?":
      return "help";
    default:
      return null;
  }
}

/** For the help panel: [keys, what it does (English), Taglish hint]. */
export const SHORTCUTS: [string, string, string][] = [
  ["Space / K", "Play or pause", "I-play o i-pause"],
  ["S / Ctrl+B", "Split at the playhead", "Hatiin sa playhead"],
  ["Delete", "Delete the selected clips (the gap closes)", "Burahin ang napiling clip"],
  ["Ctrl+Z / Ctrl+Shift+Z", "Undo / redo", "Ibalik / ulitin"],
  ["← / →", "One frame back / forward", "Isang frame"],
  ["Shift+← / Shift+→", "One second back / forward", "Isang segundo"],
  ["↑ / ↓", "Previous / next cut", "Nakaraan / susunod na hiwa"],
  ["Home / End", "Start / end", "Simula / dulo"],
  ["+ / −  ·  Ctrl+0", "Zoom the timeline in / out · fit", "Palakihin / paliitin ang timeline"],
  ["N", "Snapping on / off", "Snapping"],
  ["Ctrl+S", "Save now (it also saves by itself)", "I-save ngayon"],
  ["Ctrl+E", "Export the video", "I-export"],
  ["Esc", "Clear the selection", "Alisin ang pagpili"],
];

/** True when a key press is meant for a text field, not the editor. */
export function typingInto(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLInputElement) return !["range", "checkbox", "radio", "button"].includes(target.type);
  return false;
}
