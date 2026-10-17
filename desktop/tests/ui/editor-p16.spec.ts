// Phase 1.6 in the editor: effects that follow the speaker's hand, face or body. The preview's
// glow is compared with where the real engine drew it (fixtures made by
// tests/ui/make_fixtures.py: a synthetic track, no hands are detected here), and the
// follow / set-up flows run against the stand-in bridge.
import { expect, test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import type { Clip, Project } from "../../src/shared/types";
import { clipsOn, engineProblems, openEditor, savedAfter } from "./editorHelpers";
import { FIXTURES, SHOTS } from "./helpers";

const tracked = (p: Project): Clip[] => p.tracks.filter((t) => t.kind === "effect").flatMap((t) => t.clips).filter((c) => c.type === "trackfx");

async function seek(page: Page, seconds: number) {
  await page.keyboard.press("Home");
  const whole = Math.floor(seconds + 1e-9);
  for (let i = 0; i < whole; i++) await page.keyboard.press("Shift+ArrowRight");
  const frames = Math.round((seconds - whole) * 30);
  for (let i = 0; i < frames; i++) await page.keyboard.press("ArrowRight");
}

/** Centre of the light the preview draws, in 1080x1920 canvas pixels, and how much light there is. */
async function previewLight(page: Page) {
  return page.evaluate(() => {
    const canvas = document.querySelector('[data-testid="trackfx-layer"]') as HTMLCanvasElement | null;
    if (!canvas) return null;
    const ctx = canvas.getContext("2d")!;
    const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    let sum = 0;
    let sx = 0;
    let sy = 0;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        const v = (data[i] + data[i + 1] + data[i + 2]) * (data[i + 3] / 255);
        if (v > 12) {
          sum += v;
          sx += x * v;
          sy += y * v;
        }
      }
    }
    return sum ? { x: (sx / sum) * 2, y: (sy / sum) * 2, light: sum } : { x: null, y: null, light: 0 };
  });
}

test.describe("editor: tracked effects", () => {
  test.beforeEach(async ({ page }) => page.setViewportSize({ width: 1440, height: 900 }));

  test("the preview's glow lands where the engine drew it, and fades out when the point is lost", async ({ page }) => {
    const engine = JSON.parse(fs.readFileSync(path.join(FIXTURES, "trackfx.json"), "utf-8")).cases as { time: number; x: number | null; y: number | null; light: number }[];
    await openEditor(page, "mock=1&consent=1&speed=4&project=trackfx");
    await expect(clipsOn(page, "effects").first()).toBeVisible();
    const seen: Record<number, Awaited<ReturnType<typeof previewLight>>> = {};
    for (const c of engine) {
      await seek(page, c.time);
      await expect(page.getByTestId("time")).toContainText(`0:0${Math.floor(c.time)}`);
      seen[c.time] = await previewLight(page);
      if (c.x === null) {
        expect(seen[c.time]?.light ?? 0, `nothing at ${c.time}s`).toBe(0);
      } else {
        const got = seen[c.time]!;
        expect(got.x, `x at ${c.time}s`).toBeCloseTo(c.x, -1.3); // within about 10 px (the look differs a little, the place does not)
        expect(Math.abs(got.y! - c.y!), `y at ${c.time}s`).toBeLessThan(12);
      }
    }
    // Lost at 1.6 s: dimmer at 1.7 s, gone by 2.0 s, back at 2.6 s, like the engine's frames.
    expect(seen[1.7]!.light).toBeLessThan(seen[1.5]!.light);
    expect(seen[2.0]?.light ?? 0).toBe(0);
    expect(seen[2.6]!.light).toBeGreaterThan(0.6 * seen[1.5]!.light);
    await seek(page, 1.2);
    await page.screenshot({ path: path.join(SHOTS, "editor-trackfx.png") });
  });

  test("add an effect, follow my hands, and see how well it was found", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4");
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    const section = page.getByTestId("tracked-section");
    await expect(section.getByTestId("track-not-ready")).toHaveCount(0); // tracking is ready in this run
    await page.keyboard.press("Shift+ArrowRight");
    let saved = await savedAfter(page, () => section.getByRole("button", { name: "Tracked Glow" }).click());
    expect(tracked(saved)).toHaveLength(1);
    expect(tracked(saved)[0]).toMatchObject({ effect: "glow", point: "index_tip", hand: "any", start: 1 });
    expect(engineProblems(saved)).toEqual([]);
    await expect(page.getByTestId("toast")).toContainText("Follow my hands");
    // Nothing to follow yet: said in the panel, the clip's settings and the export.
    await expect(section.getByTestId("track-untracked")).toContainText("1 tracked effect has nothing to follow");
    const inspector = page.getByTestId("inspector");
    await expect(inspector.getByTestId("track-state")).toContainText("has not been followed yet");
    await page.getByTestId("export").click();
    await expect(page.getByTestId("export-untracked")).toContainText("will not show");
    await page.getByRole("button", { name: "Close", exact: true }).click();

    // Follow: progress, cancel works, then the points are in the project.
    await section.getByTestId("track-follow").click();
    await expect(section.getByTestId("track-task")).toContainText("Following");
    await section.getByTestId("track-task").getByRole("button", { name: "Cancel" }).click();
    await expect(section.getByTestId("track-task")).toHaveCount(0, { timeout: 5000 });
    expect(await page.evaluate(() => (window as unknown as { savedProjects: { project: Project }[] }).savedProjects.every((x) => !x.project.tracking))).toBe(true);
    saved = await savedAfter(page, async () => {
      await section.getByTestId("track-follow").click();
      await expect(section.getByTestId("track-task")).toHaveCount(0, { timeout: 15_000 });
    });
    expect(Object.keys(saved.tracking ?? {})).toHaveLength(1);
    expect(engineProblems(saved)).toEqual([]);
    await expect(page.getByTestId("toast")).toContainText("Followed: right index tip 93%");
    await expect(section.getByTestId("track-untracked")).toHaveCount(0);
    await expect(section.getByTestId("track-follow")).toContainText("Follow again");
    await expect(inspector.getByTestId("track-state")).toContainText("Found in 100% of this moment");
    // The preview now draws the glow where the track says.
    await seek(page, 1.5);
    await expect(page.getByTestId("trackfx-layer")).toBeVisible();
    const light = await previewLight(page);
    expect(light!.light).toBeGreaterThan(0);
    // One undo step takes the points back out.
    await page.keyboard.press("Control+z");
    await expect(section.getByTestId("track-untracked")).toBeVisible();
  });

  test("which hand, which point, strength, size, steadiness, colour: valid clips the engine accepts", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4&project=trackfx");
    await seek(page, 1.5);
    await clipsOn(page, "effects").first().click();
    const inspector = page.getByTestId("inspector");
    await expect(inspector).toContainText("Tracked effect: Glow");
    await expect(inspector.getByTestId("track-state")).toContainText("Found in");
    let saved = await savedAfter(page, async () => {
      await inspector.getByLabel("Which hand").selectOption("left");
    });
    expect(tracked(saved)[0].hand).toBe("left");
    await expect(inspector.getByTestId("track-state")).toContainText("This point was not saved");   // only the right hand was tracked
    saved = await savedAfter(page, async () => {
      await inspector.getByLabel("Follows", { exact: true }).selectOption("face");
    });
    expect(tracked(saved)[0].point).toBe("face");
    await expect(inspector.getByLabel("Which hand")).toHaveCount(0);                                // a face has no hand
    saved = await savedAfter(page, async () => {
      await inspector.getByLabel("Tracked effect").selectOption("aura");
    });
    expect(tracked(saved)[0].effect).toBe("aura");
    await expect(page.getByTestId("trackfx-layer")).toHaveAttribute("data-effects", "aura");
    saved = await savedAfter(page, () => inspector.getByTestId("tfx-size").fill("2"));
    saved = await savedAfter(page, () => inspector.getByTestId("tfx-smooth").fill("0.9"));
    saved = await savedAfter(page, () => inspector.getByTestId("intensity").fill("0.4"));
    saved = await savedAfter(page, () => inspector.getByTestId("tfx-color").fill("#ff2200"));
    expect(tracked(saved)[0]).toMatchObject({ size: 2, smooth: 0.9, intensity: 0.4, color: "#ff2200", effect: "aura", point: "face" });
    saved = await savedAfter(page, () => inspector.getByRole("button", { name: "Own colour" }).click());
    expect("color" in tracked(saved)[0]).toBe(false);
    expect(engineProblems(saved)).toEqual([]);
    // Its start and end are the clip's edges on the timeline: trim and move like any effect.
    const clip = clipsOn(page, "effects").first();
    const box = (await clip.boundingBox())!;
    const before = tracked(saved)[0];
    saved = await savedAfter(page, async () => {
      await page.mouse.move(box.x + box.width - 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width - 80, box.y + box.height / 2, { steps: 6 });
      await page.mouse.up();
    });
    expect(tracked(saved)[0].duration).toBeLessThan(before.duration - 0.2);
    expect(engineProblems(saved)).toEqual([]);
  });

  test("your own clip: pick a file, background type, and it is a valid effect", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4&project=trackfx");
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    const saved = await savedAfter(page, () => page.getByTestId("tracked-section").getByRole("button", { name: "Tracked Your own clip" }).click());
    const clip = tracked(saved).find((c) => c.effect === "clip")!;
    expect(clip).toMatchObject({ blend: "screen" });
    expect(saved.media.find((m) => m.id === clip.media)).toBeTruthy();
    expect(engineProblems(saved)).toEqual([]);
    const inspector = page.getByTestId("inspector");
    const after = await savedAfter(page, async () => {
      await inspector.getByLabel("Effect clip background").selectOption("alpha");
    });
    expect(tracked(after).find((c) => c.effect === "clip")!.blend).toBe("alpha");
  });

  test("set up: what is missing is explained, and a model is downloaded only after you confirm", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4&track=none");
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    const section = page.getByTestId("tracked-section");
    await expect(section.getByTestId("track-not-ready")).toContainText("not installed");
    await expect(section.getByTestId("track-follow")).toBeDisabled();
    await section.getByTestId("track-setup-open").click();
    const dialog = page.getByTestId("track-setup");
    await expect(dialog.getByTestId("track-install-command")).toHaveText("python -m pip install mediapipe");
    await expect(dialog.getByTestId("track-download")).toBeDisabled();       // the package comes first
    await page.screenshot({ path: path.join(SHOTS, "track-setup-none.png") });
    await page.getByRole("button", { name: "Close", exact: true }).click();

    await page.goto("/");
    await openEditor(page, "mock=1&consent=1&speed=4&track=models");
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    await expect(page.getByTestId("track-not-ready")).toContainText("hand model is not downloaded");
    await page.getByTestId("track-setup-open").click();
    const d2 = page.getByTestId("track-setup");
    await expect(d2.getByTestId("track-model-hand")).toContainText("not downloaded");
    await d2.getByTestId("track-download").click();
    await expect(d2.getByTestId("track-confirm")).toContainText("hand_landmarker.task");
    await expect(d2.getByTestId("track-confirm")).toContainText("their own terms");
    await d2.getByTestId("track-confirm").getByRole("button", { name: "Cancel" }).click();     // no
    expect(await page.evaluate(() => (window as unknown as { trackDownloads: string[][] }).trackDownloads)).toEqual([]);
    await page.screenshot({ path: path.join(SHOTS, "track-setup-models.png") });
    await d2.getByTestId("track-download").click();
    await d2.getByTestId("track-confirm-yes").click();                                         // yes
    await expect(d2).toContainText("Ready");
    expect(await page.evaluate(() => (window as unknown as { trackDownloads: string[][] }).trackDownloads)).toEqual([["hand", "face"]]);
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(page.getByTestId("track-not-ready")).toHaveCount(0);
    await expect(page.getByTestId("track-follow")).toBeEnabled();
  });

  test("the Effects tab still fits at 1280x800", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openEditor(page, "mock=1&consent=1&speed=4&track=models");
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    const problems = await page.evaluate(() => {
      const out: string[] = [];
      if (document.documentElement.scrollWidth > window.innerWidth) out.push("page scrolls sideways");
      const panel = document.querySelector('[data-testid="left-panel"]')!.getBoundingClientRect();
      document.querySelectorAll('[data-testid="left-panel"] button').forEach((b) => {
        const r = b.getBoundingClientRect();
        if (r.width && (r.right > panel.right + 1 || r.left < panel.left - 1)) out.push(`${b.textContent} sticks out`);
        if ((b as HTMLElement).scrollWidth > (b as HTMLElement).clientWidth + 1) out.push(`cut off: ${b.textContent}`);
      });
      return out;
    });
    expect(problems).toEqual([]);
    await page.getByTestId("tracked-section").scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(SHOTS, "editor-tracked-1280.png") });
  });
});
