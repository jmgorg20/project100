// Phase 2 in the editor: captions, vocabulary, effects and transitions, sound settings,
// your music folder, and recording a voice-over (Chromium's fake microphone).
import { expect, test, type Page } from "@playwright/test";
import * as path from "node:path";
import type { Project } from "../../src/shared/types";
import { clipsOn, engineProblems, mainOf, openEditor, savedAfter } from "./editorHelpers";
import { SHOTS } from "./helpers";

const captionsOf = (p: Project) => p.tracks.filter((t) => t.kind === "caption").flatMap((t) => t.clips).sort((a, b) => a.start - b.start);
const effectsOf = (p: Project) => p.tracks.filter((t) => t.kind === "effect").flatMap((t) => t.clips);

async function selectFirstCaptionFromThePicture(page: Page) {
  await page.keyboard.press("Shift+ArrowRight"); // 1 s: the first caption is on screen
  await page.keyboard.press("ArrowLeft");
  await page.getByTestId("caption").click();
  await expect(page.getByTestId("caption-editor")).toBeVisible();
}

test.describe("editor: captions, sound and effects", () => {
  test.beforeEach(async ({ page }) => page.setViewportSize({ width: 1440, height: 900 }));

  test("click a caption on the picture, change its words, highlight, emoji, style and place", async ({ page }) => {
    await openEditor(page);
    await selectFirstCaptionFromThePicture(page);
    const editor = page.getByTestId("caption-editor");
    const first = editor.getByLabel("Word 1", { exact: true });
    let saved = await savedAfter(page, async () => {
      await first.fill("Hello");
      await first.press("Enter");
    });
    expect(engineProblems(saved)).toEqual([]);
    expect(captionsOf(saved)[0].words![0].text).toBe("Hello");

    saved = await savedAfter(page, () => editor.getByRole("button", { name: "Highlight word 2" }).click());
    expect(captionsOf(saved)[0].words![1].highlight).toBe(true);
    await editor.getByLabel("Word 2", { exact: true }).focus();
    saved = await savedAfter(page, () => editor.getByRole("button", { name: "Add 🔥" }).click());
    expect(captionsOf(saved)[0].words![1].text).toMatch(/🔥$/);

    saved = await savedAfter(page, async () => {
      await editor.getByLabel("Caption style").selectOption("one_word");
    });
    expect(captionsOf(saved)[0].style).toBe("one_word");
    expect(captionsOf(saved)[1].style).not.toBe("one_word"); // only this caption
    await editor.getByText("Change every caption").click();
    saved = await savedAfter(page, async () => {
      await editor.getByLabel("Caption place").selectOption("top");
    });
    expect(captionsOf(saved).every((c) => (c.overrides as { zone?: string })?.zone === "top")).toBe(true);
    expect(engineProblems(saved)).toEqual([]);
    await page.screenshot({ path: path.join(SHOTS, "editor-captions.png") });
  });

  test("listen again replaces the captions in that part, and undo brings them back", async ({ page }) => {
    await openEditor(page);
    await selectFirstCaptionFromThePicture(page);
    const before = captionsOf(await page.evaluate(() => fetch("/fixtures/demo.project.json").then((r) => r.json())));
    await page.getByRole("button", { name: /Listen again/ }).click();
    await expect(page.getByTestId("toast")).toContainText("Listened again: 2 words");
    await expect(page.getByTestId("timeline").getByText("Pakinggan ulit")).toBeVisible();
    await page.keyboard.press("Control+z");
    await expect(page.getByTestId("timeline").getByText("Pakinggan ulit")).toHaveCount(0);
    await expect(page.getByTestId("timeline").getByText(before[0].words!.map((w) => w.text).join(" "))).toBeVisible();
  });

  test("your words and corrections are saved and fix this video's captions", async ({ page }) => {
    await openEditor(page);
    await page.getByTestId("open-vocabulary").click();
    const dialog = page.getByTestId("vocabulary");
    await expect(dialog).toContainText("GCash");
    await dialog.getByLabel("Wrong 2").fill("kumusta");
    await dialog.getByLabel("Right 2").fill("Kumusta po");
    await dialog.getByLabel("Words").fill("Ate Rose, Meralco");
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    const saved = await savedAfter(page, () => dialog.getByTestId("vocab-apply").click());
    await expect(page.getByTestId("toast")).toContainText("Fixed 1 caption");
    expect(captionsOf(saved)[0].words!.map((w) => w.text)[0]).toBe("Kumusta po");
    const vocab = await page.evaluate(() => (window as unknown as { vocabulary: unknown }).vocabulary);
    expect(vocab).toEqual({
      words: ["GCash", "Shopee", "Ate Rose", "Meralco"],
      corrections: [{ from: "g cash", to: "GCash" }, { from: "kumusta", to: "Kumusta po" }],
    });
  });

  test("effects, transitions, zooms, colour and a speed ramp are clips the engine accepts", async ({ page }) => {
    await openEditor(page);
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    await page.keyboard.press("Shift+ArrowRight");
    let saved = await savedAfter(page, () => page.getByTestId("effects-list").getByRole("button", { name: "Flash", exact: true }).click());
    const flash = effectsOf(saved).find((c) => c.type === "fx" && c.effect === "flash")!;
    expect(flash).toMatchObject({ start: 1, duration: 0.3 });
    // The preview shows the flash at its peak.
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("fx-layer")).toBeVisible();
    saved = await savedAfter(page, () => page.getByTestId("inspector").getByTestId("intensity").fill("1"));
    expect(effectsOf(saved).find((c) => c.effect === "flash")!.intensity).toBe(1);

    saved = await savedAfter(page, () => page.getByRole("button", { name: "Whip blur transition" }).click());
    const cuts = mainOf(saved).slice(1).map((c) => c.start);
    const whip = effectsOf(saved).find((c) => c.effect === "whip")!;
    expect(cuts.some((cut) => Math.abs(whip.start + whip.duration / 2 - cut) < 0.01)).toBe(true);

    saved = await savedAfter(page, () => page.getByRole("button", { name: "Smooth zoom" }).click());
    expect(effectsOf(saved).some((c) => c.type === "zoom" && (c.ease ?? 0) > 0)).toBe(true);
    await page.getByText("Whole video").click();
    saved = await savedAfter(page, () => page.getByRole("button", { name: "orange teal" }).click());
    expect(effectsOf(saved).some((c) => c.type === "grade" && c.grade === "orange_teal" && c.start === 0)).toBe(true);

    const mainBefore = mainOf(saved).length;
    await clipsOn(page, "main").first().click();
    saved = await savedAfter(page, async () => {
      await page.getByLabel("Speed ramp").selectOption("bullet");
    });
    expect(mainOf(saved).length).toBe(mainBefore + 2);
    expect(mainOf(saved).slice(0, 3).map((c) => c.speed ?? 1)).toEqual([1, 0.4, 1]);
    expect(engineProblems(saved)).toEqual([]);
    await page.screenshot({ path: path.join(SHOTS, "editor-effects.png") });
  });

  test("sound settings, your music folder, and a recorded voice-over", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4&music=1");
    let saved = await savedAfter(page, () => page.getByTestId("ducking").fill("0.6"));
    saved = await savedAfter(page, () => page.getByTestId("denoise").fill("0.4"));
    expect(saved.settings.audio).toMatchObject({ ducking: 0.6, denoise: 0.4 });

    await page.getByRole("tab", { name: "Music" }).click();
    const library = page.getByTestId("library-music");
    await expect(library.getByTestId("library-item")).toHaveCount(2);
    await library.getByLabel("Search music").fill("tone");
    await expect(library.getByTestId("library-item")).toHaveCount(1);
    saved = await savedAfter(page, () => library.getByRole("button", { name: "Add tone.wav" }).click());
    expect(saved.tracks.find((t) => t.role === "music")!.clips).toHaveLength(1);

    await page.getByRole("tab", { name: "Sound effects" }).click();
    await page.getByTestId("library-sfx").getByRole("button", { name: "Choose folder" }).click();
    await expect(page.getByTestId("library-sfx")).toContainText("C:/Users/me/Sounds");

    // Record: the fake microphone plays a tone, so the level meter moves.
    await clipsOn(page, "music").first().click();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "🎙 Record a voice-over" }).click();
    const rec = page.getByTestId("recorder");
    await expect.poll(async () => Number(await rec.getByTestId("meter").getAttribute("aria-valuenow")), { timeout: 10_000 }).toBeGreaterThan(0);
    await rec.getByRole("button", { name: "● Record" }).click();
    await expect(rec.getByTestId("countdown")).toBeVisible();
    await expect(rec.getByTestId("recording")).toBeVisible({ timeout: 5000 });
    await page.waitForTimeout(800);
    await rec.getByRole("button", { name: "■ Stop" }).click();
    await expect(rec.getByTestId("take")).toBeVisible();
    saved = await savedAfter(page, () => rec.getByTestId("use-take").click());
    expect(saved.tracks.find((t) => t.role === "voiceover")!.clips).toHaveLength(1);
    expect(await page.evaluate(() => (window as unknown as { recordings: number[] }).recordings[0])).toBeGreaterThan(1000);
    expect(engineProblems(saved)).toEqual([]);
  });

  test("layout with the new panels at 1280x800", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openEditor(page);
    for (const tab of ["Media", "B-roll", "Music", "Sound effects", "Effects"]) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
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
      expect(problems, tab).toEqual([]);
    }
    await page.screenshot({ path: path.join(SHOTS, "editor-effects-1280.png") });
  });
});
