import { describe, expect, it } from "vitest";
import { layoutScaleAt } from "../../src/renderer/lib/timeline";
import type { Project } from "../../src/shared/types";

const project = {
  settings: { fps: 30 },
  tracks: [{ id: "fx", kind: "effect", clips: [{ id: "l", type: "layout", mode: "speaker_low", start: 1, duration: 2, scale: 0.6, fade: 0.4 }] }],
} as unknown as Project;

describe("speaker lower (preview)", () => {
  it("eases the speaker down while a card is up, like the render", () => {
    expect(layoutScaleAt(project, 0.5)).toBe(1);
    expect(layoutScaleAt(project, 2)).toBeCloseTo(0.6);
    const easing = layoutScaleAt(project, 1.2);
    expect(easing).toBeGreaterThan(0.6);
    expect(easing).toBeLessThan(1);
    expect(layoutScaleAt(project, 3.5)).toBe(1);
  });
});
