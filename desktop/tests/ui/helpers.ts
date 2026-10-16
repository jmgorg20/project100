import { expect, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

export const FIXTURES = path.join(__dirname, "fixtures");
export const SHOTS = path.join(__dirname, "screenshots");
const TYPES: Record<string, string> = {
  ".mp4": "video/mp4", ".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json", ".wav": "audio/wav",
};

export async function open(page: Page, query = "mock=1&consent=1&speed=3") {
  await page.route("**/fixtures/**", async (route) => {
    const name = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop() ?? "");
    const file = path.join(FIXTURES, name);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404 });
    const body = fs.readFileSync(file);
    const contentType = TYPES[path.extname(name)] ?? "application/octet-stream";
    // Videos can only seek when the server answers Range requests (file:// in Electron does).
    const range = /bytes=(\d+)-(\d*)/.exec(route.request().headers()["range"] ?? "");
    if (!range) return route.fulfill({ body, contentType, headers: { "Accept-Ranges": "bytes" } });
    const start = Number(range[1]);
    const end = range[2] ? Math.min(Number(range[2]), body.length - 1) : body.length - 1;
    await route.fulfill({
      status: 206,
      body: body.subarray(start, end + 1),
      contentType,
      headers: { "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${body.length}` },
    });
  });
  await page.goto(`/?${query}`);
  await expect(page.getByRole("heading", { name: "Auto Video Editor" })).toBeVisible();
}

