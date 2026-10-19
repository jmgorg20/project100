import { expect, test } from "@playwright/test";
import { checkPhoneLayout, signUp } from "./helpers";

test("inside the Android app plans are not sold; the website in the same browser still sells them", async ({ page, context }) => {
  await signUp(page);
  await page.goto("/app/?source=android#/account");
  const card = page.getByTestId("billing");
  await expect(card.getByTestId("plan-creator")).toContainText("$9.00 a month");
  await expect(card.getByTestId("no-buying-in-app")).toBeVisible();
  await expect(card.getByRole("button", { name: "Choose" })).toHaveCount(0);
  // moving around the app keeps it in app mode
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "New" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Account" }).click();
  await expect(card.getByTestId("no-buying-in-app")).toBeVisible();
  await checkPhoneLayout(page);

  const web = await context.newPage();                         // Chrome on the same phone: the website
  await web.goto("/app/#/account");
  await expect(web.getByTestId("billing").getByRole("button", { name: "Choose" })).toBeVisible();
  await expect(web.getByTestId("no-buying-in-app")).toHaveCount(0);
});
