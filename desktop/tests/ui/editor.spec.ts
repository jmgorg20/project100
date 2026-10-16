// The timeline editor in Chromium with the stand-in bridge (?mock=1). The project is the
// engine's real AI-edit fixture; every project the editor saves is checked by the engine.
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import type { Project } from "../../src/shared/types";
import { SHOTS, open } from "./helpers";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");

async function openEditor(page: Page, query = "mock=1&consent=1&speed=4") {
  await open(page, query);
  await page.getByRole("button", { name: "Open project…" }).click();
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/);
}

const clipsOn = (page: Page, track: string) => page.getByTestId(`track-${track}`).getByTestId("clip");

const saveCount = (page: Page) => page.evaluate(() => (window as unknown as { savedProjects: unknown[] }).savedProjects.length);

/** Do something in the editor and return the project it saves next (autosave). */
async function savedAfter(page: Page, action: () => Promise<void>): Promise<Project> {
  const before = await saveCount(page);
  await action();
  await expect.poll(() => saveCount(page), { timeout: 5000 }).toBeGreaterThan(before);
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/);
  return page.evaluate(() => {
    const w = window as unknown as { savedProjects: { project: Project }[] };
    return w.savedProjects[w.savedProjects.length - 1].project;
  });
}

/** The engine's own validator (autoedit/project.py) on a project the editor saved. */
function engineProblems(project: Project): string[] {
  const out = execFileSync(python, ["-c", "import json,sys; from autoedit.project import validate_project; print(json.dumps(validate_project(json.load(sys.stdin))))"], {
    cwd: repo,
    input: JSON.stringify(project),
    encoding: "utf-8",
  });
  return JSON.parse(out);
}

const mainOf = (p: Project) => [...p.tracks.find((t) => t.kind === "video")!.clips].sort((a, b) => a.start - b.start);

async function editorLayoutProblems(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const problems: string[] = [];
    if (document.documentElement.scrollWidth > window.innerWidth) problems.push("page scrolls sideways");
    if (document.documentElement.scrollHeight > window.innerHeight + 1) problems.push("page scrolls down");
    const areas = [".ed-top", ".media-bin", ".ed-preview", ".ed-inspector", ".ed-timeline"].map((s) => [s, document.querySelector(s)!.getBoundingClientRect()] as const);
    for (const [s, r] of areas) {
      if (r.right > window.innerWidth + 1 || r.bottom > window.innerHeight + 1) problems.push(`${s} goes off screen`);
      if (r.width < 50 || r.height < 30) problems.push(`${s} is squashed`);
    }
    const [bin, prev, insp] = [areas[1][1], areas[2][1], areas[3][1]];
    if (bin.right > prev.left || prev.right > insp.left) problems.push("panels overlap");
    const stage = document.querySelector('[data-testid="stage"]')!.getBoundingClientRect();
    if (stage.height < window.innerHeight * 0.3) problems.push("the preview is too small");
    document.querySelectorAll(".ed-top button, .tl-toolbar button, .inspector button").forEach((b) => {
      if ((b as HTMLElement).scrollWidth > (b as HTMLElement).clientWidth + 1) problems.push(`button text cut off: ${b.textContent}`);
    });
    return problems;
  });
}

test.describe("timeline editor", () => {
  for (const size of [{ width: 1280, height: 800 }, { width: 1920, height: 1080 }]) {
    test(`layout at ${size.width}x${size.height}`, async ({ page }) => {
      await page.setViewportSize(size);
      await openEditor(page);
      await expect(clipsOn(page, "main")).toHaveCount(3);
      await expect(page.getByTestId("filmstrip").first()).toBeVisible();
      await expect(page.getByTestId("waveform").first()).toBeVisible();
      expect(await editorLayoutProblems(page)).toEqual([]);
      await clipsOn(page, "main").first().click();
      await expect(page.getByTestId("inspector")).toContainText("Main video clip");
      expect(await editorLayoutProblems(page)).toEqual([]);
      await page.screenshot({ path: path.join(SHOTS, `editor-${size.width}.png`) });
    });
  }

  test("opens the AI result from its summary, and goes back", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "mock=1&consent=1&speed=4");
    await page.getByRole("button", { name: "Add videos" }).click();
    await page.getByTestId("run").click();
    await expect(page.getByTestId("summary")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("open-editor").click();
    await expect(page.getByTestId("timeline")).toBeVisible();
    await page.getByRole("button", { name: "Back to the AI edit" }).click();
    await expect(page.getByTestId("summary")).toBeVisible();
  });

  test("split, delete with ripple, undo and redo with the keyboard; saves a valid project", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page);
    const before = mainOf(await page.evaluate(() => fetch("/fixtures/demo.project.json").then((r) => r.json())));
    await page.keyboard.press("Shift+ArrowRight"); // playhead to 1 s
    await expect(page.getByTestId("time")).toHaveText(/^0:01\.0/);
    let saved = await savedAfter(page, () => page.keyboard.press("s"));
    await expect(clipsOn(page, "main")).toHaveCount(4);
    expect(engineProblems(saved)).toEqual([]);
    expect(mainOf(saved).map((c) => c.start)).toContain(1);

    await page.keyboard.press("Control+z");
    await expect(clipsOn(page, "main")).toHaveCount(3);
    await page.keyboard.press("Control+Shift+z");
    await expect(clipsOn(page, "main")).toHaveCount(4);

    // Delete the first main clip: everything after it moves back (the gap closes).
    await clipsOn(page, "main").first().click();
    saved = await savedAfter(page, () => page.keyboard.press("Delete"));
    await expect(clipsOn(page, "main")).toHaveCount(3);
    expect(engineProblems(saved)).toEqual([]);
    expect(mainOf(saved)[0].start).toBe(0);
    const total = (p: Project) => mainOf(p).reduce((s, c) => s + c.duration, 0);
    expect(total(saved)).toBeCloseTo(total({ tracks: [{ kind: "video", clips: before }] } as unknown as Project) - 1, 3);
  });

  test("trim by dragging an edge (snapping), and reorder the main video by dragging", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page);
    const first = clipsOn(page, "main").first();
    const box = (await first.boundingBox())!;
    await first.click();
    const handle = first.getByTestId("trim-end");
    const h = (await handle.boundingBox())!;
    let saved = await savedAfter(page, async () => {
      await page.mouse.move(h.x + 4, h.y + h.height / 2);
      await page.mouse.down();
      await page.mouse.move(h.x - box.width / 3, h.y + h.height / 2, { steps: 8 });
      await page.mouse.up();
    });
    expect(engineProblems(saved)).toEqual([]);
    const trimmed = mainOf(saved)[0];
    expect(trimmed.duration).toBeLessThan(box.width / (await pps(page)) - 0.2);

    // Drag the first clip to the end of the main video.
    const ids = mainOf(saved).map((c) => c.id);
    const b = (await clipsOn(page, "main").first().boundingBox())!;
    const last = (await clipsOn(page, "main").last().boundingBox())!;
    saved = await savedAfter(page, async () => {
      await page.mouse.move(b.x + 10, b.y + b.height / 2);
      await page.mouse.down();
      await page.mouse.move(last.x + last.width - 5, b.y + b.height / 2, { steps: 10 });
      await expect(page.getByTestId("insert-line")).toBeVisible();
      await page.mouse.up();
    });
    expect(engineProblems(saved)).toEqual([]);
    expect(mainOf(saved).map((c) => c.id)).toEqual([...ids.slice(1), ids[0]]);
  });

  test("clip settings: speed, volume, fades and reframe; preview follows", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page);
    const clip = clipsOn(page, "main").first();
    const w0 = (await clip.boundingBox())!.width;
    await clip.click();
    const inspector = page.getByTestId("inspector");
    await inspector.getByRole("button", { name: "2x" }).click();
    await expect(clip).toContainText("2x");
    expect((await clip.boundingBox())!.width).toBeCloseTo(w0 / 2, -1);
    await inspector.getByTestId("volume").fill("1.5");
    await inspector.getByTestId("fade-in").fill("0.3");
    await inspector.getByTestId("crop-zoom").fill("1.5");
    const saved = await savedAfter(page, () => inspector.getByTestId("crop-x").fill("0.2"));
    expect(engineProblems(saved)).toEqual([]);
    expect(mainOf(saved)[0]).toMatchObject({ speed: 2, volume: 1.5, fade_in: 0.3, crop: { zoom: 1.5, x: 0.2, y: 0.5 } });
    // The preview plays this clip twice as fast and shows the reframed picture.
    const video = page.getByTestId("main-video");
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.playbackRate)).toBe(2);
    await expect(video).toHaveClass(/framed/);
    // One undo step per slider drag, not one per pixel.
    for (let i = 0; i < 4; i++) await page.keyboard.press("Control+z");
    await expect(clip).not.toContainText("2x");
    await page.screenshot({ path: path.join(SHOTS, "editor-inspector.png") });
  });

  test("move a clip; dropping it on a busy spot puts it on a new track", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page);
    const caption = clipsOn(page, "captions").first();
    const c = (await caption.boundingBox())!;
    const later = (await clipsOn(page, "captions").nth(1).boundingBox())!;
    const saved = await savedAfter(page, async () => {
      await page.mouse.move(c.x + 10, c.y + c.height / 2);
      await page.mouse.down();
      await page.mouse.move(later.x + 20, c.y + c.height / 2, { steps: 8 });
      await page.mouse.up();
    });
    expect(engineProblems(saved)).toEqual([]);
    expect(saved.tracks.filter((t) => t.kind === "caption").length).toBe(2);
    await expect(page.getByTestId("timeline").getByText("Captions 2")).toBeVisible();
  });

  test("import media, add sound and B-roll, lock a track", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page);
    await page.getByTestId("media-bin").getByRole("button", { name: "Import" }).click();
    await expect(page.getByTestId("toast")).toContainText("broken.mp4");
    await expect(page.getByTestId("media-item")).toHaveCount(4);
    await page.getByRole("button", { name: "Add tone.wav as sound" }).click();
    await expect(clipsOn(page, "music")).toHaveCount(1);
    await expect(clipsOn(page, "music").getByTestId("waveform")).toBeVisible();
    let saved = await savedAfter(page, () => page.getByRole("button", { name: "Add demo_talk_2.mp4 as B-roll" }).click());
    expect(engineProblems(saved)).toEqual([]);
    // The photo track is busy at the playhead, so the B-roll goes on a second overlay track.
    expect(saved.tracks.filter((t) => t.kind === "overlay").flatMap((t) => t.clips)).toHaveLength(2);
    await expect(page.getByTestId("timeline").getByText("Photos 2")).toBeVisible();

    // A locked track does not change.
    saved = await savedAfter(page, () => page.getByRole("button", { name: "Lock Video" }).click());
    await page.keyboard.press("Shift+ArrowRight");
    // Splits the other tracks under the playhead, not the locked video.
    saved = await savedAfter(page, () => page.getByTestId("split").click());
    expect(mainOf(saved)).toHaveLength(3);
    expect(engineProblems(saved)).toEqual([]);
    expect(saved.tracks.find((t) => t.kind === "video")!.locked).toBe(true);
  });

  test("export: options, progress, done; and cancel", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await openEditor(page, "mock=1&consent=1&speed=2");
    await page.keyboard.press("Control+e");
    const dialog = page.getByTestId("export-dialog");
    await expect(dialog.getByTestId("export-path")).toHaveText("demo_talk_ai_export.mp4");
    await dialog.getByLabel("Size").selectOption("1280");
    await dialog.getByLabel("Frames per second").selectOption("25");
    await dialog.getByLabel("Quality").selectOption("small");
    await dialog.getByRole("button", { name: "Change…" }).click();
    await expect(dialog.getByTestId("export-path")).toHaveText("my video export.mp4");
    await dialog.getByTestId("export-start").click();
    await expect(dialog.getByTestId("export-progress")).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, "editor-export.png") });
    await expect(dialog.getByTestId("export-done")).toBeVisible({ timeout: 10_000 });
    const exports = await page.evaluate(() => (window as unknown as { exports: unknown[] }).exports);
    expect(exports[0]).toMatchObject({ projectPath: "C:/Videos/demo_talk_ai.project.json", output: "C:/Videos/my video export.mp4", height: 1280, fps: 25, crf: 26, speed: "fast" });
    await dialog.getByRole("button", { name: "Show in folder" }).click();
    expect(await page.evaluate(() => (window as unknown as { shownInFolder: string[] }).shownInFolder)).toEqual(["C:/Videos/my video export.mp4"]);

    await dialog.getByTestId("export-start").click();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toContainText("Export cancelled");
  });

  test("shortcuts help, save failure and a broken project are explained", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openEditor(page);
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toContainText("Hatiin sa playhead");
    await page.keyboard.press("Escape");

    await open(page, "mock=1&consent=1&saveFail=1");
    await page.getByRole("button", { name: "Open project…" }).click();
    await expect(page.getByTestId("timeline")).toBeVisible();
    await page.keyboard.press("Shift+ArrowRight");
    await page.keyboard.press("s");
    await expect(page.getByTestId("save-state")).toHaveText("Not saved!");

    await open(page, "mock=1&consent=1&project=broken");
    await page.getByRole("button", { name: "Open project…" }).click();
    await expect(page.getByRole("alert")).toContainText("unknown media 'nope'");
  });
});

async function pps(page: Page): Promise<number> {
  const ticks = page.locator(".tick");
  const a = (await ticks.nth(0).boundingBox())!;
  const b = (await ticks.nth(1).boundingBox())!;
  const step = await ticks.nth(1).innerText();
  const seconds = step.includes(":") ? Number(step.split(":")[0]) * 60 + Number(step.split(":")[1]) : Number(step);
  return (b.x - a.x) / seconds;
}
