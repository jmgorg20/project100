import * as path from "node:path";
import { expect, test } from "@playwright/test";
import { MEDIA, PASSWORD, checkPhoneLayout, signUp } from "./helpers";

test.describe.configure({ mode: "serial" });

test("phone: sign up, upload, pick a style, watch, fix a caption, export, history", async ({ page }) => {
  const email = await signUp(page);
  await expect(page.getByTestId("minutes-left")).toContainText("60 minutes");

  // a new video: the file goes up in pieces, then the job starts
  await page.getByTestId("pick-video").setInputFiles(path.join(MEDIA, "talk.mp4"));
  await page.getByLabel("Add photos (optional)").setInputFiles(path.join(MEDIA, "photo.png"));
  await page.getByTestId("preset-podcast_clips").click();
  await page.getByTestId("instruction").fill("Mabilis, big captions, tanggalin ang pauses");
  const previews: { status: number; type: string; disposition: string }[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/files/out/") && !r.url().includes("download=1") && r.headers()["content-type"] === "video/mp4") {
      previews.push({ status: r.status(), type: r.headers()["content-type"], disposition: r.headers()["content-disposition"] ?? "" });
    }
  });
  const chunks: string[] = [];
  page.on("request", (r) => r.url().includes("/chunk?offset=") && chunks.push(r.url()));
  await page.getByTestId("start").click();
  await expect(page.getByTestId("job")).toBeVisible();
  expect(chunks.length).toBeGreaterThan(2);                  // 1 MB pieces

  // live progress, then the result
  await expect(page.getByTestId("job")).toHaveAttribute("data-status", "succeeded", { timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Done!" })).toBeVisible();
  const video = page.getByTestId("preview");
  const h264 = await video.evaluate((v: HTMLVideoElement) => v.canPlayType('video/mp4; codecs="avc1.42E01E"'));
  if (h264) {
    await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(1);
  } else {
    // Playwright's open-source Chromium cannot decode H.264 (phones and Chrome can): check the player
    // asked for the video and got it as an inline MP4 instead.
    await expect.poll(() => previews.length).toBeGreaterThan(0);
    expect([200, 206]).toContain(previews[0].status);
    expect(previews[0].disposition).toMatch(/^inline/);
  }
  expect(await page.getByTestId("download").getAttribute("href")).toContain("download=1");
  await expect(page.getByTestId("qc")).toContainText("All checks passed");
  await expect(page.getByTestId("expires")).toContainText("days");
  await checkPhoneLayout(page);

  // the storyboard and a caption fix, then a smaller export
  await expect(page.getByTestId("storyboard")).toContainText("Alam niyo ba ito?");
  await page.getByText("Fix captions").click();
  const line = page.getByTestId("caption-t2").getByRole("textbox");
  await line.fill("Simple lang talaga.");
  await line.blur();
  const exportBox = page.getByTestId("export");
  await exportBox.getByLabel("Size").selectOption("1280");
  await exportBox.getByLabel("Quality").selectOption("small");
  const renderRequest = page.waitForRequest((r) => r.url().endsWith("/v1/jobs") && r.method() === "POST");
  await page.getByTestId("render").click();
  const sent = (await renderRequest).postDataJSON();
  expect(sent.kind).toBe("render");
  expect(sent.export).toEqual({ height: 1280, quality: "small", fps: 30 });
  const fixed = sent.project.tracks.find((t: { kind: string }) => t.kind === "caption").clips.find((c: { id: string }) => c.id === "t2");
  expect(fixed.words.map((w: { text: string }) => w.text).join(" ")).toBe("Simple lang talaga.");
  expect(sent.project.media.every((m: { path: string }) => /^(upload|output):/.test(m.path))).toBe(true);
  // the new render job's own page (the old page also says "succeeded": wait for the switch first)
  const renderJob = await (await (await renderRequest).response())!.json();
  await expect(page).toHaveURL(new RegExp(`#/jobs/${renderJob.id}$`));
  await expect(page.getByTestId("job")).toHaveAttribute("data-status", "succeeded", { timeout: 60_000 });

  // history: both jobs; Taglish; delete one
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "My videos" }).click();
  await expect(page.getByTestId("history").getByRole("listitem")).toHaveCount(2);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" }).click();
  await page.getByTestId("language").selectOption("tl");
  await expect(page.getByRole("navigation", { name: "Main" })).toContainText("Mga video ko");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Mga video ko" }).click();
  await page.getByTestId("history").getByRole("link").first().click();
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Burahin na" }).click();
  await expect(page.getByTestId("history").getByRole("listitem")).toHaveCount(1);

  // the language choice follows the account to another device
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" }).click();
  await page.getByRole("button", { name: "Mag-sign out" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Mag-sign in" }).click();
  await expect(page.getByRole("heading", { name: "Bagong video" })).toBeVisible();
});

test("a broken connection does not lose the upload: it continues where it stopped", async ({ page }) => {
  await signUp(page);
  let failed = 0;
  await page.route("**/chunk?offset=*", async (route) => {
    const offset = Number(new URL(route.request().url()).searchParams.get("offset"));
    if (offset > 0 && failed < 1) {
      failed++;
      await route.abort("connectionreset");                     // the network drops once
    } else await route.continue();
  });
  await page.getByTestId("pick-video").setInputFiles(path.join(MEDIA, "talk.mp4"));
  await page.getByTestId("start").click();
  await expect(page.getByTestId("job")).toBeVisible({ timeout: 30_000 });
  expect(failed).toBe(1);
});

test("pause, close the app, pick the same file again: the upload resumes", async ({ page }) => {
  await signUp(page);
  const offsets: number[] = [];
  await page.route("**/chunk?offset=*", async (route) => {
    offsets.push(Number(new URL(route.request().url()).searchParams.get("offset")));
    await new Promise((r) => setTimeout(r, 400));               // a slow phone connection
    await route.continue();
  });
  await page.getByTestId("pick-video").setInputFiles(path.join(MEDIA, "talk.mp4"));
  await page.getByTestId("start").click();
  await expect.poll(() => offsets.length).toBeGreaterThanOrEqual(2);
  await page.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByText("Paused.")).toBeVisible();
  const before = Math.max(...offsets);
  await page.reload();
  offsets.length = 0;
  await page.getByTestId("pick-video").setInputFiles(path.join(MEDIA, "talk.mp4"));
  await page.getByTestId("start").click();
  await expect(page.getByTestId("job")).toBeVisible({ timeout: 30_000 });
  expect(offsets[0]).toBeGreaterThan(0);                         // it did not start again from zero
  expect(offsets[0]).toBeLessThanOrEqual(before + 1048576);
});

test("a rejected file says why", async ({ page }) => {
  await signUp(page);
  await page.getByTestId("pick-video").setInputFiles({ name: "notreally.mp4", mimeType: "video/mp4", buffer: Buffer.from("this is text, not a video".repeat(40)) });
  await page.getByTestId("start").click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByTestId("start")).toBeEnabled();
});
