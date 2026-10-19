import { expect, test } from "@playwright/test";
import { checkPhoneLayout, signUp } from "./helpers";

const ADMIN = { Authorization: `Bearer ${"a".repeat(40)}` };

test("phone: the free trial, choosing a plan, paying (test provider), and a paused workspace", async ({ page }) => {
  await signUp(page);
  await expect(page.getByTestId("billing-banner")).toContainText("Free trial: 7 day(s) left");

  // the plans, then the (test) checkout and back
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" }).click();
  const card = page.getByTestId("billing");
  await expect(card.getByTestId("billing-state")).toContainText("7 day(s) left");
  await expect(card.getByTestId("plan-creator")).toContainText("$9.00 a month");
  await checkPhoneLayout(page);
  await card.getByTestId("plan-creator").getByRole("button", { name: "Choose" }).click();
  await expect(page.getByRole("heading", { name: "Test checkout (no real payment)" })).toBeVisible();
  await page.getByRole("button", { name: "Pay (test)" }).click();
  await expect(page.getByText("Thank you! Your plan is active.")).toBeVisible();
  await expect(card.getByTestId("plan-creator")).toContainText("Your plan");
  await expect(card.getByTestId("usage-meter")).toContainText("of 300 minutes used this month");
  await expect(card.getByText("Payments")).toBeVisible();

  // the plan is taken away (as when it ends): new videos are paused, with a way to choose a plan
  const session = await (await page.request.get("/v1/auth/session")).json();
  const org = session.organisation.id;
  expect((await page.request.post(`/v1/admin/billing/${org}/grant`, { data: { plan_id: null }, headers: ADMIN })).ok()).toBe(true);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "New" }).click();
  await expect(page.getByTestId("billing-banner")).toContainText("Choose a plan to make more videos");
  await page.getByTestId("pick-video").setInputFiles({ name: "x.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(2000) });
  await page.getByTestId("start").click();
  await expect(page.getByRole("alert")).toContainText("Choose a plan");
});

test("Taglish billing words", async ({ page }) => {
  await signUp(page);
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" }).click();
  await page.getByTestId("language").selectOption("tl");
  await expect(page.getByTestId("billing")).toContainText("Plan at bayad");
  await expect(page.getByTestId("billing")).toContainText("araw na lang");
});
