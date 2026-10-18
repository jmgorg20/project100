// Phase 5 in the editor: the Templates tab (live previews, search, mood, favourites, add at the
// playhead), graphics on the preview and the timeline, editing a graphic (words, template,
// lock, another look, regenerate), the before/after wipe, and the export check. Every saved
// project is checked by the engine's own validator.
import { expect, test, type Page } from "@playwright/test";
import type { Clip, Project } from "../../src/shared/types";
import { engineProblems, openEditor, savedAfter } from "./editorHelpers";
import { SHOTS } from "./helpers";

const graphicsOf = (p: Project): Clip[] => p.tracks.filter((t) => t.kind === "graphics").flatMap((t) => t.clips).sort((a, b) => a.start - b.start);

async function openTemplates(page: Page) {
  await page.getByRole("tab", { name: "Graphics templates" }).click();
  await expect(page.getByTestId("templates-panel")).toBeVisible();
}

async function addTemplate(page: Page, id: string): Promise<Project> {
  await page.getByTestId("templates-panel").getByRole("searchbox").fill(id);
  return savedAfter(page, () => page.getByTestId(`tpl-${id}`).getByRole("button", { name: / at the playhead$/ }).click());
}

test.describe("graphics templates", () => {
  test("the Templates tab shows 30+ live previews, searches, filters by mood and keeps favourites", async ({ page }) => {
    await openEditor(page);
    await openTemplates(page);
    const cards = page.getByTestId("templates-panel").locator(".tpl-card");
    expect(await cards.count()).toBeGreaterThanOrEqual(30);
    // previews are real drawings of the templates, built when they scroll into view
    await page.getByTestId("tpl-pop-heavy").scrollIntoViewIfNeeded();
    await expect(page.getByTestId("tpl-pop-heavy").locator(".tpl-preview .gfx-tile")).toHaveCount(1);
    await expect(page.getByTestId("tpl-pop-heavy").locator(".tpl-preview")).toContainText("SALES");
    await page.getByTestId("templates-panel").getByRole("searchbox").fill("counter");
    await expect(cards).toHaveCount(1);
    await page.getByTestId("templates-panel").getByRole("searchbox").fill("");
    await page.getByLabel("Mood").selectOption("money");
    const money = await cards.count();
    expect(money).toBeGreaterThan(3);
    expect(money).toBeLessThan(42);
    await page.getByLabel("Mood").selectOption("");
    await page.getByRole("button", { name: "Add to favourites: Stamp" }).click();
    await page.getByRole("checkbox", { name: /only/ }).check();
    await expect(cards).toHaveCount(1);
    // favourites stay after a restart
    await page.reload();
    await openEditor(page);
    await openTemplates(page);
    await page.getByRole("checkbox", { name: /only/ }).check();
    await expect(page.getByTestId("tpl-stamp")).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/p5-templates.png` });
  });

  test("add at the playhead, see it on the preview and the timeline, edit its words", async ({ page }) => {
    await openEditor(page);
    await page.keyboard.press("Home");
    for (let i = 0; i < 2; i++) await page.keyboard.press("Shift+ArrowRight");
    await openTemplates(page);
    let saved = await addTemplate(page, "pop-heavy");
    let g = graphicsOf(saved);
    expect(g).toHaveLength(1);
    expect(g[0].start).toBeCloseTo(2, 2);
    expect(g[0].template).toBe("pop-heavy");
    expect(engineProblems(saved)).toEqual([]);
    await expect(page.getByTestId(`graphic-${g[0].id}`)).toBeVisible();
    await expect(page.locator(`[data-clip="${g[0].id}"]`)).toBeVisible();
    // the inspector shows it (it was selected when added); change its words
    await expect(page.getByTestId("inspector")).toContainText("Heavy pop");
    saved = await savedAfter(page, () => page.getByTestId("graphic-text").fill("SOBRANG *GALING* NITO"));
    g = graphicsOf(saved);
    expect(g[0].params?.text).toBe("SOBRANG *GALING* NITO");
    await expect(page.getByTestId(`graphic-${g[0].id}`)).toContainText("GALING");
    // colours and size
    saved = await savedAfter(page, () => page.getByLabel("accent colour").fill("#00ff88"));
    expect(graphicsOf(saved)[0].params?.accent).toBe("#00ff88");
    // a flash on the picture when it starts
    saved = await savedAfter(page, async () => void (await page.getByLabel("Emphasis transition").selectOption("flash")));
    expect(graphicsOf(saved)[0].attach?.kind).toBe("flash");
    expect(engineProblems(saved)).toEqual([]);
    await page.screenshot({ path: `${SHOTS}/p5-graphic-inspector.png` });
  });

  test("another look never repeats a neighbour; lock blocks changes; regenerate asks the engine", async ({ page }) => {
    await openEditor(page);
    await openTemplates(page);
    await page.keyboard.press("Home");
    let saved = await addTemplate(page, "pop-heavy");
    for (let i = 0; i < 3; i++) await page.keyboard.press("Shift+ArrowRight");
    saved = await addTemplate(page, "stamp");
    for (let i = 0; i < 3; i++) await page.keyboard.press("Shift+ArrowRight");
    saved = await addTemplate(page, "glow-blur-in");
    const [a, b, c] = graphicsOf(saved);
    await page.locator(`[data-clip="${b.id}"]`).click();
    for (let i = 0; i < 4; i++) {
      saved = await savedAfter(page, () => page.getByTestId("another-look").click());
      const now = graphicsOf(saved);
      expect(now[1].template).not.toBe(now[0].template);
      expect(now[1].template).not.toBe(now[2].template);
      expect(now[1].params?.text).toBe(b.params?.text);
    }
    expect(engineProblems(saved)).toEqual([]);
    // lock: no delete, no move, fields disabled
    saved = await savedAfter(page, () => page.getByTestId("lock").check());
    expect(graphicsOf(saved)[1].locked).toBe(true);
    await expect(page.getByTestId("another-look")).toBeDisabled();
    await page.keyboard.press("Delete");
    await expect(page.getByTestId("toast")).toContainText(/locked/i);
    expect(graphicsOf(saved).map((x) => x.id)).toContain(b.id);
    await page.locator(`[data-clip="${b.id}"]`).click();
    saved = await savedAfter(page, () => page.getByTestId("lock").uncheck());
    // regenerate through the engine (the stand-in bridge makes another look)
    await page.locator(`[data-clip="${c.id}"]`).click();
    const before = graphicsOf(saved)[2].template;
    await page.getByTestId("regenerate").click();
    await expect.poll(async () => (await page.evaluate(() => (window as unknown as { graphicsRegenerated: unknown[] }).graphicsRegenerated.length))).toBe(1);
    await expect(page.getByTestId("inspector")).not.toContainText(`Graphic: ${before === "glow-blur-in" ? "Glow blur-in" : "x"}`);
    void a;
  });

  test("before/after wipe from the Effects tab, and the export check warns about the face", async ({ page }) => {
    await openEditor(page);
    await page.getByRole("tab", { name: "Effects", exact: true }).click();
    let saved = await savedAfter(page, () => page.getByRole("button", { name: "Before/after wipe" }).click());
    const wipe = saved.tracks.flatMap((t) => t.clips).find((c) => c.type === "wipe")!;
    expect(wipe.grade).toBe("orange_teal");
    expect(engineProblems(saved)).toEqual([]);
    saved = await savedAfter(page, async () => void (await page.getByLabel("Wipe direction").selectOption("down")));
    expect(saved.tracks.flatMap((t) => t.clips).find((c) => c.type === "wipe")!.direction).toBe("down");
    // the preview shows the graded side once the line has moved
    await page.keyboard.press("Home");
    for (let i = 0; i < 30; i++) await page.keyboard.press("ArrowRight");
    await expect(page.getByTestId("wipe-layer")).toBeVisible();
    // a graphic placed on the face: the export dialog warns before exporting
    await openTemplates(page);
    saved = await addTemplate(page, "stamp");
    saved = await savedAfter(page, () => page.getByLabel("Up / down").fill("0.3"));
    await page.getByTestId("export").click();
    await expect(page.getByTestId("graphics-check")).toContainText("covers the speaker's face");
    await page.screenshot({ path: `${SHOTS}/p5-export-check.png` });
  });

  test("the AI panel offers the graphics styles", async ({ page }) => {
    await page.goto("/?mock=1&consent=1");
    const select = page.getByTestId("graphics-style");
    await expect(select).toBeVisible();
    await expect(select.locator("option")).toHaveCount(8);
    await select.selectOption("promoter");
    await expect(select).toHaveValue("promoter");
  });

  test("the AI panel's video format menu asks for the format's files and sends them", async ({ page }) => {
    await page.goto("/?mock=1&consent=1");
    await page.getByRole("button", { name: "Add videos" }).click();
    const select = page.getByTestId("format-select");
    await expect(select.locator("option")).toHaveCount(15);       // from my words, AI picks, 13 formats
    await select.selectOption("reaction");
    await expect(page.getByTestId("format-about")).toContainText("small window");
    await expect(page.getByTestId("format-missing")).toContainText("The video you react to");
    await expect(page.getByTestId("run")).toBeDisabled();
    await page.getByRole("button", { name: "Choose: The video you react to" }).click();
    await expect(page.getByTestId("format-role-source")).toContainText("reaction_source.mp4");
    await expect(page.getByTestId("format-missing")).toHaveCount(0);
    await page.getByLabel("Second video offset").fill("1.5");
    await page.screenshot({ path: `${SHOTS}/p5-format-picker.png` });
    await page.getByTestId("run").click();
    const requests = await page.evaluate(() => (window as unknown as { lastJobRequests: unknown[] }).lastJobRequests);
    expect(requests[0]).toMatchObject({
      format: "reaction", formatInputs: { source: ["C:/Videos/reaction_source.mp4"] }, offsets: { source: 1.5 },
    });
  });

  test("Listicle items go with the job, and no format sends nothing extra", async ({ page }) => {
    await page.goto("/?mock=1&consent=1");
    await page.getByRole("button", { name: "Add videos" }).click();
    await page.getByTestId("format-select").selectOption("listicle");
    await expect(page.getByTestId("format-picker").getByRole("button", { name: /^Choose/ })).toHaveCount(0);
    await page.getByTestId("format-items").fill("Mag-ipon\n\nMag-invest");
    await page.getByTestId("run").click();
    let requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
    expect(requests[0]).toMatchObject({ format: "listicle", items: ["Mag-ipon", "Mag-invest"] });
    await page.goto("/?mock=1&consent=1");
    await page.getByRole("button", { name: "Add videos" }).click();
    await page.getByTestId("run").click();
    requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
    expect(requests[0].format).toBeUndefined();
  });
});
