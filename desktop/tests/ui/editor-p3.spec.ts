// Phase 3 in the editor: B-roll found in your folder, on free stock or made with AI (results
// the real engine made: tests/ui/make_fixtures.py), find another, regenerate, replace, and the
// export's credits and AI label.
import { expect, test, type Page } from "@playwright/test";
import * as path from "node:path";
import type { BrollRequest } from "../../src/shared/api";
import type { Clip, Project } from "../../src/shared/types";
import { engineProblems, openEditor, savedAfter } from "./editorHelpers";
import { SHOTS } from "./helpers";

const brollOf = (p: Project): Clip[] => p.tracks.filter((t) => t.kind === "overlay").flatMap((t) => t.clips).filter((c) => c.broll);
const mediaOf = (p: Project, c: Clip) => p.media.find((m) => m.id === c.media)!;
const requests = (page: Page) => page.evaluate(() => (window as unknown as { brollRequests: BrollRequest[] }).brollRequests);

async function describeAndAdd(page: Page, what: { prompt?: string; search?: string; source?: string; look?: string }) {
  const panel = page.getByTestId("broll-panel");
  await panel.getByLabel("What to show").fill(what.prompt ?? "");
  await panel.getByLabel("Search words").fill(what.search ?? "");
  if (what.look) await panel.getByLabel("Look").selectOption(what.look);
  await panel.getByLabel("Where from").selectOption(what.source ?? "auto");
  return savedAfter(page, async () => {
    await panel.getByTestId("broll-add").click();
    await expect(page.getByTestId("broll-task")).toHaveCount(0, { timeout: 10_000 });
  });
}

test.describe("editor: B-roll", () => {
  test.beforeEach(async ({ page }) => page.setViewportSize({ width: 1440, height: 900 }));

  test("from your folder, find another, then AI; regenerate, replace with a file, undo", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4&broll=1");
    await page.keyboard.press("Shift+ArrowRight"); // the playhead at 1 s
    await page.getByRole("tab", { name: "B-roll" }).click();
    await expect(page.getByTestId("broll-item")).toHaveCount(3);
    await page.getByLabel("Search B-roll").fill("coffee cup");
    await expect(page.getByTestId("broll-item")).toHaveCount(1);
    let saved = await describeAndAdd(page, { prompt: "a steaming cup of coffee", search: "coffee cup" });
    let [clip] = brollOf(saved);
    expect(clip).toMatchObject({ start: 1, duration: 3, label: "Library: coffee cup", broll: { source: "library", position: "full", style: "realistic" } });
    expect(mediaOf(saved, clip).path).toBe("C:/Videos/broll/broll_library1.png");
    expect(engineProblems(saved)).toEqual([]);
    const inspector = page.getByTestId("inspector");
    await expect(inspector.getByTestId("broll-source")).toContainText("From your B-roll library");
    await page.screenshot({ path: path.join(SHOTS, "editor-broll.png") });

    // Find another: the same description, without the file it has now.
    saved = await savedAfter(page, async () => {
      await inspector.getByRole("button", { name: "Find another · Iba pa" }).click();
      await expect(inspector.getByTestId("broll-task")).toHaveCount(0, { timeout: 10_000 });
    });
    [clip] = brollOf(saved);
    expect(mediaOf(saved, clip).path).toBe("C:/Videos/broll/broll_library2.png");
    let last = (await requests(page)).at(-1)!;
    expect(last).toMatchObject({ source: "auto", search: "coffee cup", prompt: "a steaming cup of coffee", newVersion: true, duration: 3 });
    expect(last.exclude).toContain("C:/Videos/broll/broll_library1.png");

    // Nothing else in the folder and no stock key: AI makes it, and it is labelled.
    saved = await savedAfter(page, async () => {
      await inspector.getByRole("button", { name: "Find another · Iba pa" }).click();
      await expect(inspector.getByTestId("broll-task")).toBeVisible();
      await expect(inspector.getByTestId("broll-task")).toHaveCount(0, { timeout: 10_000 });
    });
    [clip] = brollOf(saved);
    expect(clip.broll).toMatchObject({ source: "ai", ai_generated: true, tier: "Draft" });
    await expect(inspector).toContainText("Made with AI");
    await expect(page.getByTestId("timeline").locator(".badge-ai")).toBeVisible();

    await inspector.getByLabel("Regenerate quality").selectOption("draft");
    await inspector.getByRole("button", { name: "Regenerate with AI · Gawin ulit" }).click();
    await expect(inspector.getByTestId("broll-task")).toHaveCount(0, { timeout: 10_000 });
    last = (await requests(page)).at(-1)!;
    expect(last).toMatchObject({ source: "ai", quality: "draft", newVersion: true });

    // Your own file instead (a video): it keeps its place; undo brings the AI picture back.
    saved = await savedAfter(page, () => inspector.getByRole("button", { name: "Replace with a file…" }).click());
    [clip] = brollOf(saved);
    expect(clip).toMatchObject({ type: "video", in: 0, broll: { source: "file", ai_generated: false } });
    expect(mediaOf(saved, clip).path).toBe("C:/Videos/demo_talk_2.mp4");
    expect(engineProblems(saved)).toEqual([]);
    saved = await savedAfter(page, () => page.keyboard.press("Control+z"));
    expect(brollOf(saved)[0].broll?.source).toBe("ai");

    // Editing the description is kept on the clip (for the next search).
    saved = await savedAfter(page, async () => {
      await inspector.getByLabel("B-roll look").selectOption("cartoon");
    });
    expect(brollOf(saved)[0].broll?.style).toBe("cartoon");

    // A file from your folder, added by hand.
    await page.getByLabel("Search B-roll").fill("jeepney");
    saved = await savedAfter(page, () => page.getByRole("button", { name: "Add jeepney street.png as B-roll" }).click());
    expect(brollOf(saved).some((c) => c.label === "Library: jeepney street")).toBe(true);
    expect(engineProblems(saved)).toEqual([]);
  });

  test("free stock with your key: credit and licence; the export lists credits and the AI label", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=4");
    await page.getByRole("button", { name: "Back to the AI edit" }).click();
    await page.getByRole("button", { name: "Settings" }).click();
    const settings = page.getByRole("dialog", { name: "Settings" });
    await settings.getByLabel(/Pixabay API key/).fill("my-free-pixabay-key");
    await settings.locator("#key-pixabay").locator("..").getByRole("button", { name: "Save" }).click();
    await expect(settings.locator("#key-pixabay")).toHaveAttribute("placeholder", /Saved/);
    await page.screenshot({ path: path.join(SHOTS, "settings-broll.png") });
    await settings.getByRole("button", { name: "Save", exact: true }).last().click();

    await page.getByRole("button", { name: "Open project…" }).click();
    await expect(page.getByTestId("timeline")).toBeVisible();
    await page.getByRole("tab", { name: "B-roll" }).click();
    await expect(page.getByTestId("broll-panel")).toContainText("Free stock: Pixabay");
    let saved = await describeAndAdd(page, { search: "mountain sunrise", source: "stock" });
    const stock = brollOf(saved).find((c) => c.broll?.source === "pixabay")!;
    expect(stock.broll).toMatchObject({ author: "Maria_Santos", license: "Pixabay Content License", stock_id: "pixabay-4521" });
    const inspector = page.getByTestId("inspector");
    await expect(inspector).toContainText("Photo by Maria_Santos on Pixabay");
    await expect(inspector.getByRole("link", { name: "Pixabay Content License" })).toHaveAttribute("href", "https://pixabay.com/service/license-summary/");
    await expect(inspector.getByRole("link", { name: "Source page" })).toHaveAttribute("href", "https://pixabay.com/photos/4521/");

    await page.keyboard.press("End");
    saved = await describeAndAdd(page, { prompt: "a robot waving", source: "ai", look: "cartoon" });
    expect(brollOf(saved).filter((c) => c.broll?.ai_generated)).toHaveLength(1);
    expect((await requests(page)).at(-1)).toMatchObject({ style: "cartoon", source: "ai" });
    expect(engineProblems(saved)).toEqual([]);

    await page.getByTestId("export").click();
    const dialog = page.getByTestId("export-dialog");
    await expect(dialog.getByTestId("export-ai-label")).toContainText("1 B-roll clip was made with AI");
    await expect(dialog.locator("#export-credit-text")).toHaveValue("Credits: Photo by Maria_Santos on Pixabay (https://pixabay.com/photos/4521/)");
    await page.waitForTimeout(400); // the dialog's fade-in
    await page.screenshot({ path: path.join(SHOTS, "export-credits.png") });
  });

  test("cancel while AI is making it: nothing is added", async ({ page }) => {
    await openEditor(page, "mock=1&consent=1&speed=1");
    await page.getByRole("tab", { name: "B-roll" }).click();
    const panel = page.getByTestId("broll-panel");
    await panel.getByLabel("What to show").fill("a robot waving");
    await panel.getByLabel("Where from").selectOption("ai");
    const before = await page.evaluate(() => (window as unknown as { savedProjects: unknown[] }).savedProjects.length);
    await panel.getByTestId("broll-add").click();
    await expect(panel.getByTestId("broll-task")).toContainText("Making AI clips");
    await panel.getByTestId("broll-task").getByRole("button", { name: "Cancel" }).click();
    await expect(panel.getByTestId("broll-task")).toHaveCount(0, { timeout: 5000 });
    await expect(panel.getByTestId("broll-add")).toBeVisible();
    await page.waitForTimeout(600);
    expect(await page.evaluate(() => (window as unknown as { savedProjects: unknown[] }).savedProjects.length)).toBe(before);
    // Only your folder, and there is none: a plain message, no clip.
    await panel.getByLabel("Where from").selectOption("library");
    await panel.getByTestId("broll-add").click();
    await expect(page.getByTestId("toast")).toContainText("No B-roll found");
  });
});
