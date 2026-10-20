// Settings -> Face finder (auto / off) and "Repair face finder" (after the real Windows hang).
import { expect, test } from "@playwright/test";
import { SHOTS, open } from "./helpers";

test("face finder: auto by default, can be turned off, and repaired from Settings", async ({ page }) => {
  await open(page, "mock=1&consent=1&speed=4");
  await page.getByRole("button", { name: "Settings" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByTestId("face-finder")).toHaveValue("auto");
  await dialog.getByTestId("repair-face-finder").click();
  await expect(dialog.getByTestId("face-finder-repair-result")).toContainText("The face finder works (OpenCV 4.14.0)");
  await expect(dialog.getByTestId("face-finder-repair-result")).toContainText("face-finder.log");
  expect(await page.evaluate(() => (window as unknown as { faceRepairs: number }).faceRepairs)).toBe(1);
  await dialog.getByTestId("face-finder").selectOption("off");
  await dialog.getByTestId("face-finder").scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/face-finder-settings.png` });
  await dialog.getByRole("button", { name: "Save", exact: true }).last().click();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("dialog", { name: "Settings" }).getByTestId("face-finder")).toHaveValue("off");
});
