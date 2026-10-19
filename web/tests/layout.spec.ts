import { expect, test } from "@playwright/test";
import { WORDS } from "../src/i18n";
import { checkPhoneLayout, signUp } from "./helpers";

test("the sign-in page fits the screen, with big enough buttons", async ({ page }) => {
  const errors: string[] = [];
  // (a 401 from the "am I signed in?" check is expected here: nobody is)
  page.on("console", (m) => m.type() === "error" && !m.text().includes("401") && errors.push(m.text()));
  const r = await page.goto("/app/");
  expect(r?.headers()["content-security-policy"]).toContain("default-src 'self'");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await checkPhoneLayout(page);
  await page.goto("/app/#/signup");
  await expect(page.getByRole("heading", { name: "Create account" })).toBeVisible();
  await checkPhoneLayout(page);
  expect(errors, "console errors (e.g. blocked by the security policy)").toEqual([]);
});

test("signed in: every screen fits the phone, with the bottom navigation", async ({ page }) => {
  await signUp(page);
  await checkPhoneLayout(page);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  for (const [link, heading] of [["My videos", "My videos"], ["Account", "Account"], ["New", "New video"]]) {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: link }).click();
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await checkPhoneLayout(page);
  }
});

test("installable: manifest, icons and the offline shell", async ({ page, context }) => {
  const manifest = await (await page.request.get("/app/manifest.webmanifest")).json();
  expect(manifest.display).toBe("standalone");
  expect(manifest.start_url).toBe("/app/");
  for (const icon of manifest.icons) expect((await page.request.get(icon.src)).ok()).toBe(true);
  await page.goto("/app/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();                                         // now controlled by the service worker
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  await context.setOffline(true);
  await page.reload();
  await expect(page.getByText("AutoEdit").first()).toBeVisible();      // the app opens without internet
  await expect(page.getByTestId("offline")).toBeVisible();
  await context.setOffline(false);
});

test("every word has a Taglish version", () => {
  for (const [key, [en, tl]] of Object.entries(WORDS)) {
    expect(en, key).toBeTruthy();
    expect(tl, key).toBeTruthy();
  }
});
