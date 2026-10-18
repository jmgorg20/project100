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

/** No sideways scrolling and every control big enough to tap; again with a wide font (phones and
 * Linux use wider fonts than this machine may have). */
export async function checkPhoneLayout(page: Page) {
  await checkLayoutOnce(page);
  // (set through the DOM: the page's security policy rightly refuses injected <style>)
  const set = (font: string) => page.evaluate((f) => document.body.style.setProperty("font-family", f, f ? "important" : ""), font);
  for (const font of ["DejaVu Sans", "Liberation Sans", "monospace"]) {
    await set(font);
    await checkLayoutOnce(page);
  }
  await set("");
}

async function checkLayoutOnce(page: Page) {
  const wide = await page.evaluate(() => {
    const limit = document.documentElement.clientWidth;
    const over = document.documentElement.scrollWidth - limit;
    const culprits = over <= 0 ? [] : Array.from(document.querySelectorAll("body *"))
      .filter((el) => el.getBoundingClientRect().right > limit + 0.5)
      .map((el) => `${el.tagName.toLowerCase()}.${(el as HTMLElement).className} → ${Math.round(el.getBoundingClientRect().right)}px`)
      .slice(0, 8);
    return { over, culprits, font: getComputedStyle(document.body).fontFamily };
  });
  expect(wide, "page scrolls sideways").toEqual({ over: Math.min(wide.over, 0), culprits: [], font: wide.font });
  const small = await page.evaluate(() => Array.from(document.querySelectorAll("button, a.button, input:not([type=checkbox]):not(.hp), select, nav a"))
    .filter((el) => (el as HTMLElement).offsetParent !== null)
    .map((el) => ({ el: (el as HTMLElement).outerHTML.slice(0, 80), h: el.getBoundingClientRect().height }))
    .filter((x) => x.h < 43.5));
  expect(small, "controls smaller than 44px").toEqual([]);
}
