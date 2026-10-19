import { expect, test } from "@playwright/test";
import { checkPhoneLayout, signUp, totp } from "./helpers";

const ADMIN = { Authorization: `Bearer ${"a".repeat(40)}` };

test("the owner's admin pages: two-step sign-in, money, costs, users, sign-ups, plans, system", async ({ page }) => {
  const email = await signUp(page);
  // a payment (test provider), so there is revenue to show
  const session = await (await page.request.get("/v1/auth/session")).json();
  const csrf = { "X-CSRF-Token": session.csrf_token };
  const checkout = await (await page.request.post("/v1/billing/checkout", { data: { plan_id: "creator" }, headers: csrf })).json();
  const sessionToken = new URL(checkout.url).searchParams.get("session")!;
  await page.request.post("/v1/billing/fake/pay", { form: { session: sessionToken, outcome: "paid" }, maxRedirects: 0 });

  // made staff: the admin pages need two-step sign-in first
  const users = await (await page.request.get(`/v1/admin/users?q=${encodeURIComponent(email)}`, { headers: ADMIN })).json();
  await page.request.patch(`/v1/admin/users/${users.users[0].id}`, { data: { is_admin: true }, headers: ADMIN });
  await page.goto("/app/#/admin");
  await expect(page.getByRole("alert")).toContainText("two-step");
  await page.goto("/app/#/account");
  await page.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  const secret = (await page.getByTestId("mfa-secret").textContent())!;
  await page.getByLabel("Code").fill(totp(secret));
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("recovery-codes")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();

  // overview: the numbers, the chart (hover shows the values) and its table
  await page.getByTestId("admin-link").click();
  await expect(page.getByTestId("kpi-mrr")).toContainText("$9.00");
  await expect(page.getByTestId("kpi-revenue")).toContainText("$9.00");
  await expect(page.getByTestId("kpi-margin")).toContainText("%");
  const chart = page.getByTestId("money-chart");
  await expect(chart).toContainText("Revenue");
  await expect(chart).toContainText("Running cost");
  const bars = chart.locator("rect.hit");
  await bars.last().hover();
  await expect(page.getByTestId("chart-tip")).toContainText("Revenue $9.00");
  await chart.screenshot({ path: "test-results/admin-chart.png" });
  const bar = await chart.locator("rect.col").first().boundingBox();
  expect(bar!.height).toBeGreaterThan(40);                         // a real bar, not a dot
  await chart.getByRole("button", { name: "Show table" }).click();
  await expect(page.getByTestId("money-table")).toContainText("$9.00");
  await checkPhoneLayout(page);

  // costs: per client, with the CSV
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "Costs" }).click();
  await expect(page.getByTestId("cost-table")).toContainText("$9.00");
  const csv = await page.request.get(await page.getByRole("link", { name: "Download CSV" }).getAttribute("href") as string);
  expect(await csv.text()).toContain("month,client_id,name");
  await checkPhoneLayout(page);

  // sign-ups: the switch and a new invite code (shown once)
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "Sign-ups" }).click();
  await page.getByRole("radio", { name: "Paused" }).click();
  await expect(page.getByRole("radio", { name: "Paused" })).toHaveAttribute("aria-checked", "true");
  expect((await (await page.request.get("/v1/auth/config")).json()).signup_mode).toBe("closed");
  await page.getByRole("radio", { name: "Open to all" }).click();
  await page.getByLabel("Note").fill("batch 1");
  await page.getByRole("button", { name: "Make a code" }).click();
  await expect(page.getByTestId("new-code")).toContainText(/[A-Z2-9]{4}-[A-Z2-9]{4}/);

  // plans: change the minutes; users; the audit log records it all
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "Plans" }).click();
  const plan = page.getByTestId("edit-plan-creator");
  await plan.getByLabel("Minutes / month").fill("350");
  await plan.getByRole("button", { name: "Save" }).click();
  await expect(plan.getByRole("status")).toHaveText("Saved.");
  const saved = (await (await page.request.get("/v1/admin/plans", { headers: ADMIN })).json()).plans;
  expect(saved.find((p: { id: string }) => p.id === "creator").monthly_minutes).toBe(350);
  await page.request.put("/v1/admin/plans/creator", { data: { monthly_minutes: 300 }, headers: ADMIN });   // as it was
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "Users" }).click();
  await expect(page.getByTestId("admin-users")).toContainText(email);
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "Reports" }).click();
  await expect(page.getByRole("radiogroup", { name: "Report status" })).toBeVisible();
  await page.getByRole("radio", { name: "all" }).click();
  await expect(page.getByRole("radio", { name: "all" })).toHaveAttribute("aria-checked", "true");
  await checkPhoneLayout(page);
  await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: "System" }).click();
  await expect(page.getByTestId("audit")).toContainText("plan.saved");
  await expect(page.getByTestId("audit")).toContainText("signups.mode");
  await expect(page.getByTestId("audit")).toContainText(/admin:us_/);
  await checkPhoneLayout(page);
});

test("people who are not staff do not get the admin pages", async ({ page }) => {
  await signUp(page);
  await page.goto("/app/#/account");
  await expect(page.getByTestId("admin-link")).toHaveCount(0);
  await page.goto("/app/#/admin");
  await expect(page.getByRole("heading", { name: "New video" })).toBeVisible();
  expect((await page.request.get("/v1/admin/dashboard")).status()).toBe(403);
});
