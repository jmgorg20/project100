// Helpers for the timeline editor's browser tests.
import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import type { Project } from "../../src/shared/types";
import { open } from "./helpers";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");

export async function openEditor(page: Page, query = "mock=1&consent=1&speed=4") {
  await open(page, query);
  await page.getByRole("button", { name: "Open project…" }).click();
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/);
}

export const clipsOn = (page: Page, track: string) => page.getByTestId(`track-${track}`).getByTestId("clip");

export const saveCount = (page: Page) => page.evaluate(() => (window as unknown as { savedProjects: unknown[] }).savedProjects.length);

/** Do something in the editor and return the project it saves next (autosave). */
export async function savedAfter(page: Page, action: () => Promise<void>): Promise<Project> {
  const before = await saveCount(page);
  await action();
  await expect.poll(() => saveCount(page), { timeout: 5000 }).toBeGreaterThan(before);
  await expect(page.getByTestId("save-state")).toHaveText(/Saved/);
  return page.evaluate(() => {
    const w = window as unknown as { savedProjects: { project: Project }[] };
    return w.savedProjects[w.savedProjects.length - 1].project;
  });
}

/** The engine's own validator (autoedit/project.py) on a project the editor saved. */
export function engineProblems(project: Project): string[] {
  const out = execFileSync(python, ["-c", "import json,sys; from autoedit.project import validate_project; print(json.dumps(validate_project(json.load(sys.stdin))))"], {
    cwd: repo,
    input: JSON.stringify(project),
    encoding: "utf-8",
  });
  return JSON.parse(out);
}

export const mainOf = (p: Project) => [...p.tracks.find((t) => t.kind === "video")!.clips].sort((a, b) => a.start - b.start);

