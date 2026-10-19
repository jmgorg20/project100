import * as path from "node:path";
import { expect, test } from "@playwright/test";
import { MEDIA, checkPhoneLayout, signUp } from "./helpers";

const ADMIN = { Authorization: `Bearer ${"a".repeat(40)}` };

test("results are labelled as AI-edited; anyone with the link can report one, and it is held", async ({ page, browser }) => {
  await signUp(page);
  await page.getByTestId("pick-video").setInputFiles(path.join(MEDIA, "talk.mp4"));
  await page.getByTestId("start").click();
  await expect(page.getByTestId("job")).toHaveAttribute("data-status", "succeeded", { timeout: 60_000 });
  await expect(page.getByTestId("ai-label")).toContainText("Edited automatically with AI");
  await expect(page.getByTestId("ai-label")).toContainText("AI label");
  const link = new URL((await page.getByTestId("download").getAttribute("href"))!, page.url()).href;
  const jobId = page.url().split("/jobs/")[1];

  // someone else, not signed in, reports it
  const stranger = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await stranger.goto(`${new URL(page.url()).origin}/app/#/login`);
  await stranger.getByRole("link", { name: "Report a video" }).click();
  await expect(stranger.getByRole("heading", { name: "Report a video" })).toBeVisible();
  await checkPhoneLayout(stranger);
  await stranger.getByLabel("Link to the video").fill("https://example.com/not-ours");
  await stranger.getByLabel("Harm to a child").check();
  await stranger.getByRole("button", { name: "Send report" }).click();
  await expect(stranger.getByRole("alert")).toContainText("whole link");
  await stranger.getByLabel("Link to the video").fill(link);
  await stranger.getByLabel("Details (optional)").fill("test report");
  await stranger.getByRole("button", { name: "Send report" }).click();
  await expect(stranger.getByTestId("report-sent")).toContainText("Thank you");
  expect((await stranger.request.get(link)).status()).toBe(451);
  await stranger.close();

  // the owner sees it is on hold; the staff see the report
  await page.reload();
  await expect(page.getByTestId("held")).toBeVisible();
  await expect(page.getByTestId("download")).toHaveCount(0);
  const reports = (await (await page.request.get("/v1/admin/reports", { headers: ADMIN })).json()).reports;
  const mine = reports.find((r: { job_id: string }) => r.job_id === jobId);
  expect(mine.reason).toBe("child_safety");
  expect(mine.details).toBe("test report");
  // released by the staff: downloadable again
  await page.request.post(`/v1/admin/reports/${mine.id}/resolve`, { data: { action: "dismiss" }, headers: ADMIN });
  await page.reload();
  await expect(page.getByTestId("download")).toBeVisible();
});

test("sign-up needs the terms ticked, Google too", async ({ page }) => {
  await page.goto("/app/#/signup");
  await expect(page.getByRole("button", { name: "Create account" })).toBeDisabled();
  const google = page.getByRole("button", { name: "Continue with Google" });
  if (await google.count()) await expect(google).toBeDisabled();
  await page.getByRole("checkbox").check();
  await expect(page.getByRole("button", { name: "Create account" })).toBeEnabled();
  for (const name of ["terms", "privacy", "ai", "refund", "acceptable-use"]) {
    const r = await page.request.get(`/app/${name}.html`);
    expect(r.status(), name).toBe(200);
    expect(await r.text(), name).toContain("DRAFT");
  }
});
