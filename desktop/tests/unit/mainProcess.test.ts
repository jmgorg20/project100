// The Electron main process (src/main/main.ts) with a stand-in `electron` module: the IPC
// handlers, job queue, engine runs and history are real; only the window/dialog/encryption
// pieces are faked. The engine runs a real AI edit from an accepted plan (no AI call) on a
// synthetic video, with its transcript seeded in the engine's cache (no Whisper call).
import { execFileSync } from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { Job, VideoHistory } from "../../src/shared/types";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "autoedit-main-"));
const handlers = new Map<string, (...args: unknown[]) => unknown>();
const sent: [string, unknown][] = [];

vi.mock("electron", () => {
  class BrowserWindow {
    webContents = {
      send: (channel: string, payload: unknown) => sent.push([channel, payload]),
      setWindowOpenHandler: () => {},
      on: () => {},
    };
    static getAllWindows = () => [];
    loadURL() {}
    loadFile() {}
    on() {}
    isDestroyed() {
      return false;
    }
  }
  return {
    app: {
      getPath: () => path.join(tmp, "userData"),
      getAppPath: () => path.join(repo, "desktop"),
      whenReady: () => Promise.resolve(),
      on: () => {},
      quit: () => {},
    },
    BrowserWindow,
    dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) },
    ipcMain: { handle: (channel: string, fn: (...args: unknown[]) => unknown) => handlers.set(channel, fn) },
    safeStorage: {
      isEncryptionAvailable: () => true,
      encryptString: (s: string) => Buffer.from(s).reverse(),
      decryptString: (b: Buffer) => Buffer.from(b).reverse().toString(),
    },
    shell: { openExternal: () => {} },
  };
});

const call = (channel: string, ...args: unknown[]) => handlers.get(channel)!({}, ...args) as Promise<unknown>;
let seeded = "";

beforeAll(async () => {
  // A synthetic talking video, a photo, and its transcript in the engine's cache.
  execFileSync(python, ["-c", `
import sys; sys.path.insert(0, ".")
from pathlib import Path
from tests import synthetic
d = Path(sys.argv[1])
synthetic.make_video(d / "talk.mp4"); synthetic.make_transcript(d / "talk.json"); synthetic.make_image(d / "logo.png")
`, tmp], { cwd: repo });
  const digest = crypto.createHash("sha256").update(fs.readFileSync(path.join(tmp, "talk.mp4"))).digest("hex");
  seeded = path.join(repo, "work", "cache", "transcripts", `${digest}-groq-whisper-large-v3-tl.json`);
  fs.mkdirSync(path.dirname(seeded), { recursive: true });
  fs.copyFileSync(path.join(tmp, "talk.json"), seeded);
  await import("../../src/main/main");
  await new Promise((r) => setTimeout(r, 0));
}, 60_000);

afterAll(() => {
  if (seeded) fs.rmSync(seeded, { force: true });
});

const lastJob = (): Job => [...sent].reverse().find(([c]) => c === "job:changed")![1] as Job;

describe("main process with the real engine", () => {
  it("registers every channel the window uses", () => {
    for (const channel of ["settings:get", "settings:set", "keys:status", "keys:set", "keys:clear", "dialog:videos", "dialog:photos",
      "jobs:add", "jobs:list", "jobs:cancel", "jobs:dismiss", "plan:apply", "history:get", "history:undo", "history:redo",
      "engine:estimate", "engine:frame", "engine:check"]) {
      expect(handlers.has(channel), channel).toBe(true);
    }
  });

  it("starts with Auto mode on and the repository as the engine", async () => {
    const settings = (await call("settings:get")) as { autoMode: boolean; engineDir: string };
    expect(settings.autoMode).toBe(true);
    expect(settings.engineDir).toBe(repo);
    await call("settings:set", { pythonPath: python, outputDir: path.join(tmp, "out") });
    expect(await call("engine:check")).toEqual({ ok: true, message: "The editor engine is ready." });
  });

  it("keeps keys encrypted and only reports a hint", async () => {
    const status = (await call("keys:set", "anthropic", "sk-ant-abcd1234")) as { anthropic: { set: boolean; hint: string } };
    expect(status.anthropic).toEqual({ set: true, hint: "••••1234" });
    expect(fs.readFileSync(path.join(tmp, "userData", "keys.json"), "utf-8")).not.toContain("sk-ant-abcd1234");
    await call("keys:clear", "anthropic");
  });

  it("estimates the cost with the real engine", async () => {
    const estimate = (await call("engine:estimate", path.join(tmp, "talk.mp4"), "anthropic", "fast")) as { total: number; transcript_cached: boolean; model: string };
    expect(estimate.model).toBe("claude-opus-5-5");
    expect(estimate.transcript_cached).toBe(true);
    expect(estimate.total).toBeGreaterThan(0);
  }, 60_000);

  it("runs an accepted plan to a finished video, records the version, and undoes it", async () => {
    const plan = JSON.parse(execFileSync(python, ["-c", `
import json
from autoedit.config import load_config
from autoedit.ai_plan import preset_plan
p = preset_plan(load_config()); p["style"] = "one_word"
p["photos"] = [{"file": "logo.png", "at": 5.5, "duration": 1.5, "position": "top", "reason": "GitHub"}]
print(json.dumps(p))`], { cwd: repo, encoding: "utf-8" }));
    const planFile = path.join(tmp, "accepted.plan.json");
    fs.writeFileSync(planFile, JSON.stringify({ plan }));
    const video = path.join(tmp, "talk.mp4");
    await call("jobs:add", [{ video, photos: [path.join(tmp, "logo.png")], instruction: "one word captions", provider: "groq", auto: true, mode: "apply", planFile }]);
    await vi.waitFor(() => expect(["done", "failed"]).toContain(lastJob().status), { timeout: 120_000, interval: 200 });
    const job = lastJob();
    expect(job.error).toBeUndefined();
    expect(job.status).toBe("done");
    expect(job.stagesDone).toEqual(["transcript", "plan", "cuts", "zooms", "captions", "photos", "render"]);
    expect(job.transcriptCached).toBe(true);
    expect(job.summary?.details.join(" ")).toContain("one_word");
    expect(path.basename(job.output!)).toBe("talk_ai.mp4");
    expect(fs.existsSync(job.output!)).toBe(true);
    // A version was added to the history and sent to the window.
    const history = [...sent].reverse().find(([c]) => c === "history:changed")![1] as VideoHistory;
    expect(history.current).toBe(0);
    expect(history.versions[0].output).toBe(job.output);
    expect(((await call("history:undo", video)) as VideoHistory).current).toBe(-1);
    expect(((await call("history:redo", video)) as VideoHistory).current).toBe(0);
    // "Exact frame" renders the true frame from the saved project.
    const frame = (await call("engine:frame", job.projectFile, 1.0)) as { path: string };
    expect(fs.existsSync(frame.path)).toBe(true);
  }, 180_000);
});
