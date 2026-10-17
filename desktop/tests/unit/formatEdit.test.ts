// Format layouts (split / picture-in-picture) and cut-outs (person / green screen) stay editable:
// the inspector's changes are clamped to the engine's ranges and the engine accepts the result.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { EditError, allowedProps, setClipProps } from "../../src/shared/edit";
import type { Project } from "../../src/shared/types";
import { sample } from "./edit.test";

const repo = path.resolve(__dirname, "..", "..", "..");
const python = process.platform === "win32" ? "python" : "python3";

function engineProblems(p: Project): string[] {
  const out = execFileSync(python, ["-c", "import json,sys; from autoedit.project import validate_project; print(json.dumps(validate_project(json.load(sys.stdin))))"], { cwd: repo, input: JSON.stringify(p), encoding: "utf-8" });
  return JSON.parse(out);
}

function withFormat(): Project {
  const p = sample();
  p.media.push({ id: "m4", kind: "video", path: "C:/Videos/source.mp4", duration: 20, width: 1080, height: 1920, has_audio: true });
  p.tracks[0].clips[0].layout = { type: "pip", screen: "m4", corner: "top_left", size: 0.36, border: "#ff3b6b", animated: true };
  p.tracks[1].clips.push({ id: "o2", type: "video", media: "m4", start: 0, duration: 2, in: 0, out: 2, x: 540, y: 960, width: 1080, height: 1920, mask: { type: "chroma", color: "#00ff00", similarity: 0.18, blend: 0.06 } });
  return p;
}

describe("format layouts and cut-outs", () => {
  it("only clips that have a layout / mask get those settings", () => {
    const p = withFormat();
    expect(allowedProps(p.tracks[0], p.tracks[0].clips[0]).has("layout")).toBe(true);
    expect(allowedProps(p.tracks[0], p.tracks[0].clips[1]).has("layout")).toBe(false);
    expect(allowedProps(p.tracks[1], p.tracks[1].clips[1]).has("mask")).toBe(true);
    expect(() => setClipProps(p, "v2", { layout: { type: "split", screen: "m4" } })).toThrow(EditError);
    expect(engineProblems(p)).toEqual([]);
  });

  it("clamps to the engine's ranges and keeps the other video", () => {
    let p = withFormat();
    p = setClipProps(p, "v1", { layout: { type: "pip", screen: "m1", size: 2, offset: 5000, corner: "bottom_right" } });
    expect(p.tracks[0].clips[0].layout).toMatchObject({ type: "pip", screen: "m4", size: 0.6, offset: 3600, corner: "bottom_right" });
    p = setClipProps(p, "v1", { layout: { type: "split", screen: "m4", ratio: 0.1, offset: 0 } });
    expect(p.tracks[0].clips[0].layout?.ratio).toBe(0.3);
    expect(p.tracks[0].clips[0].layout?.offset).toBeUndefined();
    p = setClipProps(p, "o2", { mask: { type: "chroma", similarity: 9, blend: -1 } });
    expect(p.tracks[1].clips[1].mask).toMatchObject({ similarity: 0.6, blend: 0, color: "#00ff00" });
    expect(engineProblems(p)).toEqual([]);
  });
});
