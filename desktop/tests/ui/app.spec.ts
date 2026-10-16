import { expect, test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

const FIXTURES = path.join(__dirname, "fixtures");
const SHOTS = path.join(__dirname, "screenshots");
const TYPES: Record<string, string> = { ".mp4": "video/mp4", ".webm": "video/webm", ".png": "image/png", ".json": "application/json" };

async function open(page: Page, query = "mock=1&consent=1&speed=3") {
  await page.route("**/fixtures/**", async (route) => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop() ?? "");
    const file = path.join(FIXTURES, name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404 });
    const body = fs.readFileSync(file);
    const contentType = TYPES[path.extname(name)] ?? "application/octet-stream";
    // Videos can only seek when the server answers Range requests (file:// in Electron does).
    const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()["range"] ?? "");
    if (!range) return route.fulfill({ body, contentType, headers: { "Accept-Ranges": "bytes" } });
    const start = Number(range[1]);
    const end = range[2] ? Math.min(Number(range[2]), body.length - 1) : body.length - 1;
    await route.fulfill({
      status: 206,
      body: body.subarray(start, end + 1),
      contentType,
      headers: { "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${body.length}` },
    });
  });
  await page.goto(`/?${query}`);
  await expect(page.getByRole("heading", { name: "Auto Video Editor" })).toBeVisible();
}

/** Layout problems: horizontal scrolling, overlapping columns, cut-off buttons, off-screen controls. */
async function layoutProblems(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const problems: string[] = [];
    if (document.documentElement.scrollWidth > window.innerWidth) problems.push("page scrolls sideways");
    const cols = ['aside[aria-label="Videos"]', 'main[aria-label="Preview"]', 'aside[aria-label="AI edit"]']
      .map((s) => document.querySelector(s)!.getBoundingClientRect());
    for (let i = 0; i < cols.length - 1; i++) if (cols[i].right > cols[i + 1].left) problems.push(`columns ${i} and ${i + 1} overlap`);
    for (const c of cols) if (c.bottom > window.innerHeight + 1 || c.right > window.innerWidth + 1) problems.push("a column goes off screen");
    // Every control stays inside its own column.
    ['aside[aria-label="Videos"]', 'main[aria-label="Preview"]', 'aside[aria-label="AI edit"]'].forEach((sel) => {
      const col = document.querySelector(sel)!;
      const c = col.getBoundingClientRect();
      col.querySelectorAll("button, input, select, textarea").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width && (r.left < c.left - 1 || r.right > c.right + 1)) problems.push(`${el.textContent || el.getAttribute("aria-label")} sticks out of ${sel}`);
      });
    });
    // The preview uses most of the window height once there is something to show.
    const stage = document.querySelector('[data-testid="stage"]');
    if (stage && stage.getBoundingClientRect().height < window.innerHeight * 0.55) problems.push("the preview is too small");
    document.querySelectorAll("button").forEach((b) => {
      const r = b.getBoundingClientRect();
      if (r.width && b.scrollWidth > b.clientWidth + 1) problems.push(`button text cut off: ${b.textContent}`);
      if (r.width && (r.right > window.innerWidth || r.bottom > window.innerHeight + 1) && !b.closest(".panel-body")) problems.push(`button off screen: ${b.textContent}`);
    });
    return problems;
  });
}

for (const size of [{ width: 1280, height: 800 }, { width: 1920, height: 1080 }]) {
  test(`layout at ${size.width}x${size.height}`, async ({ page }) => {
    await page.setViewportSize(size);
    await open(page);
    expect(await layoutProblems(page)).toEqual([]);
    await page.screenshot({ path: path.join(SHOTS, `empty-${size.width}.png`) });
    await page.getByRole("button", { name: "Add videos" }).click();
    await page.getByRole("button", { name: "Add photos" }).click();
    await page.getByLabel("Instructions for the AI").fill("Mabilis na edit, malaking captions, ipakita ang github_logo.png");
    await page.getByTestId("run").click();
    await expect(page.getByTestId("summary")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("video-item").locator(".status.done")).toHaveCount(2, { timeout: 30_000 });
    expect(await layoutProblems(page)).toEqual([]);
    await page.screenshot({ path: path.join(SHOTS, `done-${size.width}.png`) });
  });
}

test("first run asks about consent", async ({ page }) => {
  await open(page, "mock=1");
  const dialog = page.getByRole("dialog", { name: "Before you start" });
  await expect(dialog).toContainText("agreed to appear");
  await expect(dialog).toContainText("no face swap, deepfake");
  const go = dialog.getByRole("button", { name: "Continue" });
  await expect(go).toBeDisabled();
  await dialog.getByLabel("I understand").check();
  await go.click();
  await expect(dialog).toBeHidden();
});

test("auto mode: a batch is edited, rendered and summarised with no extra clicks; undo and redo", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "mock=1&consent=1&speed=1");
  await expect(page.getByRole("switch", { name: "Auto mode" })).toBeChecked(); // on by default
  await page.getByRole("button", { name: "Add videos" }).click();
  await expect(page.getByTestId("video-item")).toHaveCount(2);
  await expect(page.getByTestId("estimate")).toContainText("$0 on the free tier");
  await page.getByLabel("AI provider").selectOption("anthropic");
  await expect(page.getByTestId("estimate")).toContainText("Estimated API cost: about $0.04 per video");
  await page.getByLabel("Instructions for the AI").fill("Fast, big captions");
  const run = page.getByTestId("run");
  await expect(run).toHaveText("Edit 2 videos with AI");
  await run.click();

  // The steps light up live, and the preview fills in as stages arrive.
  await expect(page.locator('[data-step="transcript"][data-state="done"]')).toBeVisible();
  await expect(page.locator('[data-step="captions"][data-state="done"]')).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: path.join(SHOTS, "live-stages.png") });
  await expect(page.locator('[data-step="render"][data-state="active"]')).toBeVisible({ timeout: 20_000 });

  // Both videos finish one after the other.
  await expect(page.getByTestId("video-item").locator(".status.done")).toHaveCount(2, { timeout: 40_000 });
  const summary = page.getByTestId("summary");
  await expect(summary).toContainText("Mabilis na edit with big captions");
  await expect(summary).toContainText("Photo github_logo.png");
  await expect(summary).toContainText("Not done: No music file");
  await expect(page.getByTestId("cost")).toContainText("API cost: about");
  await expect(page.locator("video")).toHaveAttribute("src", /demo_talk_ai\.webm/);

  await summary.getByRole("button", { name: "Undo AI edit" }).click();
  await expect(page.getByText("The AI edit was undone")).toBeVisible();
  await expect(page.locator("video")).toHaveAttribute("src", /demo_talk\.webm/);
  await page.getByRole("button", { name: "Redo AI edit" }).click();
  await expect(page.locator("video")).toHaveAttribute("src", /demo_talk_ai\.webm/);

  await summary.getByRole("button", { name: "Redo with new instructions" }).click();
  await expect(page.getByLabel("Instructions for the AI")).toHaveValue("Fast, big captions");
  await expect(page.getByLabel("Instructions for the AI")).toBeFocused();
  await expect(run).toHaveText("Redo with these instructions");
});

test("auto mode off: the AI's changes are reviewed and only accepted ones are applied", async ({ page }) => {
  await open(page, "mock=1&consent=1&speed=4");
  await page.getByRole("switch", { name: "Auto mode" }).uncheck();
  await page.getByRole("button", { name: "Add videos" }).click();
  await page.getByRole("button", { name: "Remove demo_talk_2.mp4 from the list" }).click();
  await page.getByTestId("run").click();
  const review = page.getByTestId("review");
  await expect(review).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('[data-step="render"]')).toHaveCount(0); // nothing rendered yet
  await expect(review).toContainText("Caption style: bold_caps");
  await expect(review).toContainText("github_logo.png at 0:06");
  // The live preview already shows the planned project.
  await expect(page.getByTestId("stage")).toBeVisible();
  await review.getByLabel(/github_logo\.png/).uncheck();
  await review.getByRole("button", { name: /Apply & render/ }).click();
  await expect(page.getByTestId("video-item").locator(".status.done")).toHaveCount(1, { timeout: 20_000 });
  const applied = await page.evaluate(() => (window as unknown as { lastAppliedPlan: { photos: unknown[]; style: string } }).lastAppliedPlan);
  expect(applied.photos).toEqual([]);
  expect(applied.style).toBe("bold_caps");
});

test("a plan that fails the checks falls back to the preset and says so", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Add videos" }).click();
  await page.getByLabel("Instructions for the AI").fill("FAIL please");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("summary").getByRole("alert").first()).toContainText("preset edit", { timeout: 30_000 });
  await expect(page.getByTestId("video-item").first().locator(".status")).toHaveText("Done (preset edit)");
});

test("settings: keys are saved without ever being shown", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByLabel(/Groq API key/)).toHaveAttribute("placeholder", "Saved (••••a1b2)");
  await dialog.getByLabel(/Anthropic API key/).fill("sk-ant-secret-9876");
  await dialog.getByRole("button", { name: "Save" }).nth(1).click();
  await expect(dialog.getByLabel(/Anthropic API key/)).toHaveValue("");
  await expect(dialog.getByLabel(/Anthropic API key/)).toHaveAttribute("placeholder", "Saved (••••9876)");
  expect(await page.content()).not.toContain("sk-ant-secret");
  await expect(dialog.getByLabel(/Anthropic API key/)).toHaveAttribute("type", "password");
  await dialog.getByRole("button", { name: "Check the editor engine" }).click();
  await expect(dialog).toContainText("ready");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("live preview puts captions and photos where the engine renders them", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await open(page, "mock=1&consent=1&scenario=parity");
  await page.getByRole("button", { name: "Add videos" }).click();
  await expect(page.getByTestId("stage")).toBeVisible();
  const cases = JSON.parse(fs.readFileSync(path.join(FIXTURES, "parity.json"), "utf-8")).cases as { name: string; time: number; box: number[] }[];
  for (const c of cases) {
    await page.getByLabel("Position").fill(String(c.time));
    const target = c.name === "photo" ? page.getByTestId("overlay") : page.getByTestId("caption");
    await expect(target).toBeVisible();
    const box = await page.evaluate((selector) => {
      const stage = document.querySelector('[data-testid="stage"]')!.getBoundingClientRect();
      const el = document.querySelector(selector)!.getBoundingClientRect();
      const s = 1920 / stage.height;
      return [(el.left - stage.left) * s, (el.top - stage.top) * s, (el.right - stage.left) * s, (el.bottom - stage.top) * s];
    }, c.name === "photo" ? '[data-testid="overlay"]' : '[data-testid="caption"]');
    const [ex0, ey0, ex1, ey1] = c.box; // where the engine drew ink
    const [px0, py0, px1, py1] = box; // the preview's box
    const message = `${c.name}: engine ${c.box.map(Math.round)} preview ${box.map(Math.round)}`;
    // Same horizontal centre (within 1% of the width) and vertical centre (within 3%).
    expect(Math.abs((ex0 + ex1) / 2 - (px0 + px1) / 2), message).toBeLessThan(11);
    expect(Math.abs((ey0 + ey1) / 2 - (py0 + py1) / 2), message).toBeLessThan(58);
    // Similar size: the ink fits inside the preview box, which is at most a little larger.
    expect(Math.abs((ex1 - ex0) - (px1 - px0)), message).toBeLessThan(c.name === "photo" ? 12 : 60);
    // Both stay inside the safe area (clear of the app's buttons on the right and bottom 20%).
    for (const right of [ex1, px1]) expect(right, message).toBeLessThanOrEqual(1080 - 170 + 1);
    for (const bottom of [ey1, py1]) expect(bottom, message).toBeLessThanOrEqual(1920 * 0.8);
    await page.screenshot({ path: path.join(SHOTS, `parity-${c.name}.png`), clip: await page.getByTestId("stage").boundingBox() ?? undefined });
  }
});

test("live preview plays the planned edit: right source frame, photo, caption, and it jumps over cuts", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, "mock=1&consent=1&speed=4");
  await page.getByRole("switch", { name: "Auto mode" }).uncheck();
  await page.getByRole("button", { name: "Add videos" }).click();
  await page.getByRole("button", { name: "Remove demo_talk_2.mp4 from the list" }).click();
  await page.getByTestId("run").click();
  await expect(page.getByTestId("review")).toBeVisible({ timeout: 20_000 });
  const video = page.locator("video");

  // 4.0s on the timeline is in the third piece (starts at 3.2s, source 5.2s): source 6.0s.
  await page.getByLabel("Position").fill("4");
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(2);
  expect(await video.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeCloseTo(6.0, 1);
  await expect(page.getByTestId("overlay")).toBeVisible();
  await expect(page.getByTestId("caption")).toBeVisible();
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, "live-preview.png") });

  // Play from 1.5s (source 1.6s) across the cut at 1.7s: the source must jump from 2.1s to 2.8s.
  await page.getByLabel("Position").fill("1.5");
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(async () => Number(await page.getByLabel("Position").inputValue()), { timeout: 10_000 }).toBeGreaterThan(2.0);
  // Read the timeline position and the source time at the same instant.
  const { timeline, source } = await page.evaluate(() => ({
    timeline: Number((document.querySelector('input[aria-label="Position"]') as HTMLInputElement).value),
    source: document.querySelector("video")!.currentTime,
  }));
  expect(timeline).toBeGreaterThan(1.7);
  expect(timeline).toBeLessThan(3.2);                      // still in the second piece
  expect(source).toBeCloseTo(2.8 + (timeline - 1.7), 1);   // 2.1s-2.8s of the source was skipped
  await page.getByRole("button", { name: "Pause" }).click();
});
