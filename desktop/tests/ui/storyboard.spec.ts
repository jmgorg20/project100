// The storyboard: the edit as scenes before rendering. Approve all, regenerate one scene, replace
// its footage, change its words, lock it; every change is a normal timeline edit that the
// engine's own validator accepts.
import { expect, test, type Page } from "@playwright/test";
import type { Project } from "../../src/shared/types";
import { engineProblems, openEditor, savedAfter } from "./editorHelpers";
import { SHOTS, open } from "./helpers";

async function openStoryboard(page: Page) {
  await openEditor(page, "mock=1&consent=1&speed=4&project=storyboard");
  await page.getByTestId("toggle-storyboard").click();
  await expect(page.getByTestId("storyboard")).toBeVisible();
}

const captionsOf = (p: Project) => p.tracks.filter((t) => t.kind === "caption").flatMap((t) => t.clips).sort((a, b) => a.start - b.start);

test.describe("storyboard", () => {
  test("shows each scene: purpose, length, source, words, graphics, transition, sounds, colour", async ({ page }) => {
    await openStoryboard(page);
    await expect(page.locator(".sb-card")).toHaveCount(3);
    const s1 = page.getByTestId("scene-s1");
    await expect(s1).toContainText("Hook");
    await expect(s1).toContainText("Alam niyo ba ito? Simple lang.");
    await expect(s1).toContainText("demo_talk.mp4");
    const s2 = page.getByTestId("scene-s2");
    await expect(s2).toContainText("Proof / numbers");
    await expect(s2.getByTestId("scene-graphics")).toHaveText("stamp");
    await expect(s2).toContainText("B-roll: github_logo.png");
    await expect(page.getByTestId("scene-s3")).toContainText("Call to action");
    await page.screenshot({ path: `${SHOTS}/p5-storyboard.png` });
  });

  test("edit a scene's words and lock a scene: normal timeline edits", async ({ page }) => {
    await openStoryboard(page);
    const s2 = page.getByTestId("scene-s2");
    await s2.getByRole("button", { name: "Edit words" }).click();
    await s2.getByRole("textbox", { name: "Words of scene 2" }).fill("Una, mag-budget ng *500* kada linggo.");
    let saved = await savedAfter(page, () => s2.getByRole("button", { name: "Save words" }).click());
    await expect(s2.getByTestId("scene-text")).toHaveText("Una, mag-budget ng *500* kada linggo.");
    expect(captionsOf(saved).flatMap((c) => c.words!.map((w) => w.text)).join(" ")).toContain("mag-budget ng *500* kada linggo.");
    expect(engineProblems(saved)).toEqual([]);
    await expect(page.locator(".sb-card")).toHaveCount(3);          // the scenes stay as they were

    saved = await savedAfter(page, () => s2.getByRole("button", { name: "Lock" }).click());
    const locked = saved.tracks.flatMap((t) => t.clips).filter((c) => c.locked).map((c) => c.id).sort();
    expect(locked).toEqual(expect.arrayContaining(["gx1", "o6", "t3", "t4"]));
    expect(locked).not.toContain("v1");                             // your main video stays editable
    expect(engineProblems(saved)).toEqual([]);
    await expect(s2.getByRole("button", { name: "Edit words" })).toBeDisabled();
    await expect(s2.getByRole("button", { name: "Regenerate" })).toBeDisabled();
    await page.getByTestId("toggle-storyboard").click();             // the timeline shows the locks
    await expect(page.getByTestId("timeline")).toBeVisible();
    await expect(page.locator(".lock-badge").first()).toBeVisible();
  });

  test("regenerate one scene, replace its footage, then approve all and render", async ({ page }) => {
    await openStoryboard(page);
    const s2 = page.getByTestId("scene-s2");
    await s2.getByRole("button", { name: "Regenerate" }).click();
    await expect(s2.getByTestId("scene-graphics")).not.toHaveText("stamp");
    expect(await page.evaluate(() => (window as unknown as { scenesRegenerated: unknown[] }).scenesRegenerated)).toEqual([{ scene: "s2", ai: false }]);
    // A scene without graphics gets one there (here: scene 3).
    const s3 = page.getByTestId("scene-s3");
    await s3.getByRole("button", { name: "Regenerate" }).click();
    await expect(s3.getByTestId("scene-graphics")).toHaveText("pop-heavy");

    const saved = await savedAfter(page, () => s2.getByRole("button", { name: "Replace footage" }).click());
    const broll = saved.tracks.filter((t) => t.kind === "overlay").flatMap((t) => t.clips);
    expect(broll.find((c) => c.id === "o6")!.media).not.toBe("m2");
    expect(engineProblems(saved)).toEqual([]);

    const approved = await savedAfter(page, () => page.getByTestId("approve-all").click());
    expect((approved.meta as { storyboard: { approved: boolean; starts: number[] } }).storyboard).toMatchObject({ approved: true, starts: [0, 2.8, 6] });
    await expect(page.getByRole("dialog")).toBeVisible();           // straight to export
  });

  test("the AI result opens straight into the storyboard", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, "mock=1&consent=1&speed=4");
    await page.getByRole("button", { name: "Add videos" }).click();
    await page.getByTestId("run").click();
    await expect(page.getByTestId("summary")).toBeVisible({ timeout: 30_000 });
    await page.getByTestId("open-storyboard").click();
    await expect(page.getByTestId("storyboard")).toBeVisible();
    await expect(page.locator(".sb-card").first()).toContainText("Hook");
  });

  test("presets: the eight looks, and Faceless asks for its voice-over and B-roll", async ({ page }) => {
    await open(page, "mock=1&consent=1&speed=4");
    await page.getByRole("button", { name: "Add videos" }).click();
    const select = page.getByTestId("preset");
    await expect(select.locator("option")).toHaveCount(9);
    await expect(select.locator("option[value=premium_editorial_viral]")).toHaveText(/^PREMIUM EDITORIAL VIRAL · .*magasin/);
    await select.selectOption("viral_tiktok");
    await expect(page.getByTestId("preset-about")).toContainText("Fast cuts");
    await page.getByTestId("run").click();
    let requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
    expect(requests[0]).toMatchObject({ preset: "viral_tiktok" });
    await select.selectOption("faceless_automation");
    await expect(page.getByTestId("format-select")).toHaveValue("voiceover_broll");
    await expect(page.getByTestId("format-missing")).toContainText("B-roll");
    await expect(page.getByTestId("run")).toBeDisabled();
    await page.getByRole("button", { name: "Choose: Voice-over or narration" }).click();
    await page.getByRole("button", { name: /^Choose: .*B-roll/ }).click();
    await page.getByTestId("run").click();
    requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({ preset: "faceless_automation", format: "voiceover_broll", video: "C:/Videos/vo.wav" });
  });
});
