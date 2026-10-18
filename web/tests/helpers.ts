import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const MEDIA = path.join(HERE, ".media");
const OUTBOX = path.join(HERE, ".data", "outbox");
export const PASSWORD = "correct horse battery";

/** The newest email to `to` (the test server writes sent emails as files). */
export async function emailTo(to: string, template: string): Promise<{ subject: string; body: string }> {
  let found: { subject: string; body: string } | null = null;
  await expect.poll(() => {
    if (!fs.existsSync(OUTBOX)) return false;
    const mails = fs.readdirSync(OUTBOX).map((f) => ({ f, at: fs.statSync(path.join(OUTBOX, f)).mtimeMs }))
      .sort((a, b) => b.at - a.at)
      .map(({ f }) => JSON.parse(fs.readFileSync(path.join(OUTBOX, f), "utf8")) as { to: string; template: string; subject: string; body: string })
      .filter((m) => m.to === to && m.template === template);
    found = mails[0] ?? null;
    return Boolean(found);
  }, { timeout: 20_000 }).toBe(true);
  return found!;
}

export function linkIn(body: string, route: string): string {
  const m = body.match(new RegExp(`https?://\\S+#/${route}/\\S+`));
  if (!m) throw new Error(`no ${route} link in: ${body}`);
  return new URL(m[0]).hash;
}

let counter = 0;
export function uniqueEmail(tag: string) {
  return `${tag}.${Date.now()}.${counter++}@example.com`;
}

/** A new account, confirmed and signed in on `page`. */
export async function signUp(page: Page, email = uniqueEmail("user")) {
  await page.goto("/app/#/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: false }).first().fill(PASSWORD);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByTestId("check-email")).toBeVisible();
  const mail = await emailTo(email, "verify_email");
  await page.goto(`/app/${linkIn(mail.body, "verify")}`);
  await expect(page.getByRole("heading", { name: "New video" })).toBeVisible();
  return email;
}

/** No sideways scrolling and every control big enough to tap. */
export async function checkPhoneLayout(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "page scrolls sideways").toBeLessThanOrEqual(0);
  const small = await page.evaluate(() => Array.from(document.querySelectorAll("button, a.button, input:not([type=checkbox]):not(.hp), select, nav a"))
    .filter((el) => (el as HTMLElement).offsetParent !== null)
    .map((el) => ({ el: (el as HTMLElement).outerHTML.slice(0, 80), h: el.getBoundingClientRect().height }))
    .filter((x) => x.h < 43.5));
  expect(small, "controls smaller than 44px").toEqual([]);
}
