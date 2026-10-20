// After a restart, a job an earlier session left "running" (a real Windows run kept "Planning the
// editorial scenes..." with Cancel, "Edit with AI" greyed out): it is shown interrupted with Retry,
// Edit with AI works again, and Retry edits the video again.
import { expect, test } from "@playwright/test";
import { SHOTS, open } from "./helpers";

test("a job left running by an earlier session: interrupted, Retry, Edit with AI enabled", async ({ page }) => {
  await open(page, "mock=1&consent=1&speed=4&scenario=stale");
  const item = page.getByTestId("video-item").filter({ hasText: "test 2.mp4" });
  await expect(item).toContainText("Interrupted: press Retry");
  await expect(item.getByRole("button", { name: "Cancel test 2.mp4" })).toHaveCount(0);
  await item.click();
  const card = page.getByTestId("job-interrupted");
  await expect(card).toContainText('closed or restarted while "Planning the editorial scenes"');
  await expect(card).toContainText("jobs.log");
  await expect(page.getByTestId("run")).toBeEnabled();
  await page.screenshot({ path: `${SHOTS}/stale-job-interrupted.png` });
  await card.getByTestId("retry-job").click();
  expect(await page.evaluate(() => (window as unknown as { retried: string[] }).retried)).toEqual(["stale1"]);
  await expect(item).not.toContainText("Interrupted", { timeout: 20_000 });
  await expect(item).toContainText(/Done|Ready to review/, { timeout: 30_000 });
});

test("the ✕ clears a stale job and its video", async ({ page }) => {
  await open(page, "mock=1&consent=1&speed=4&scenario=stale");
  const item = page.getByTestId("video-item").filter({ hasText: "test 2.mp4" });
  await expect(item).toContainText("Interrupted");
  await item.getByRole("button", { name: "Remove test 2.mp4 from the list" }).click();
  await expect(page.getByTestId("video-item")).toHaveCount(0);
});
