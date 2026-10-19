// M1 in the app: caption punctuation and "fix the words first" in Settings; fixing the words
// before the AI edit; the project-wide punctuation switch in the caption editor.
import { expect, test } from "@playwright/test";
import { SHOTS, open } from "./helpers";

test("fix the words before the edit: the fixed transcript goes to the engine", async ({ page }) => {
  await open(page, "mock=1&consent=1&speed=4");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByLabel(/Caption punctuation/)).toHaveValue("remove");
  await dialog.getByTestId("fix-captions-first").check();
  await dialog.getByRole("button", { name: "Save", exact: true }).last().click();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Add videos" }).click();
  await page.getByTestId("run").click();
  const fix = page.getByTestId("transcript-fix");
  await expect(fix).toBeVisible();
  const line = fix.getByRole("textbox", { name: "Line 2" });
  await expect(line).toHaveValue("Tatyo sikreto ng viral na video.");
  await line.fill("Tatlong sikreto ng viral na video.");
  await page.screenshot({ path: `${SHOTS}/m1-fix-words.png` });
  await fix.getByTestId("transcript-done").click();
  const saved = await page.evaluate(() => (window as unknown as { savedTranscript: { words: { text: string }[] } }).savedTranscript);
  expect(saved.words.map((w) => w.text).join(" ")).toContain("Tatlong sikreto ng viral na video.");
  let requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
  expect(requests[0]).toMatchObject({ video: "C:/Videos/demo_talk.mp4", transcriptFile: "C:/AppData/transcripts/demo.transcript.json" });
  // then the second video's words, one video after another
  await expect(fix.getByRole("textbox", { name: "Line 1" })).toHaveValue("Teka lang!");
  await fix.getByTestId("transcript-done").click();
  await expect(fix).toBeHidden();
  requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
  expect(requests[0]).toMatchObject({ video: "C:/Videos/demo_talk_2.mp4" });
});

test("without the setting, Edit with AI starts right away", async ({ page }) => {
  await open(page, "mock=1&consent=1&speed=4");
  await page.getByRole("button", { name: "Add videos" }).click();
  await page.getByTestId("run").click();
  await expect(page.getByTestId("transcript-fix")).toHaveCount(0);
  const requests = await page.evaluate(() => (window as unknown as { lastJobRequests: Record<string, unknown>[] }).lastJobRequests);
  expect(requests[0].transcriptFile).toBeUndefined();
});
