import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { parseLine, runEngine } from "../../src/main/engine";
import type { EngineEvent } from "../../src/shared/types";

const python = process.platform === "win32" ? "python" : "python3";
const repo = path.resolve(__dirname, "..", "..", "..");

function script(body: string): string {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "eng-")), "fake.py");
  fs.writeFileSync(file, body);
  return file;
}

describe("engine runner", () => {
  it("parses JSON lines and keeps other lines as logs", () => {
    expect(parseLine('{"type": "progress", "stage": "render", "percent": 5}')).toEqual({ type: "progress", stage: "render", percent: 5 });
    expect(parseLine("  plain text ")).toEqual({ type: "log", message: "plain text" });
    expect(parseLine("{not json")).toEqual({ type: "log", message: "{not json" });
    expect(parseLine("   ")).toBeNull();
  });

  it("runs the real engine and passes keys only through the environment", async () => {
    const events: EngineEvent[] = [];
    const handle = runEngine({ python, engineDir: repo }, ["validate", path.join(repo, "examples", "project.json")], (e) => events.push(e));
    const result = await handle.done;
    expect(result).toEqual({ code: 0, cancelled: false, startError: undefined });
    expect(events.find((e) => e.type === "result")).toMatchObject({ valid: true });

    const env = script("import os, json\nprint(json.dumps({'type': 'result', 'has_key': os.environ.get('GROQ_API_KEY') == 'gsk_x', 'argv_has_key': 'gsk_x' in ' '.join(__import__('sys').argv)}))\n");
    const seen: EngineEvent[] = [];
    await runEngine({ python, engineDir: repo, script: env, env: { GROQ_API_KEY: "gsk_x" } }, [], (e) => seen.push(e)).done;
    expect(seen[0]).toEqual({ type: "result", has_key: true, argv_has_key: false });
  });

  it("cancels through stdin, and the stand-in sees the cancel", async () => {
    const fake = script(
      "import sys, json\nprint(json.dumps({'type': 'stage', 'stage': 'render', 'label': 'x'}), flush=True)\n" +
      "line = sys.stdin.readline()\nprint(json.dumps({'type': 'cancelled', 'got': line.strip()}), flush=True)\nsys.exit(130)\n");
    const events: EngineEvent[] = [];
    let handle!: ReturnType<typeof runEngine>;
    handle = runEngine({ python, engineDir: repo, script: fake }, [], (e) => {
      events.push(e);
      if (e.type === "stage") handle.cancel();
    });
    const result = await handle.done;
    expect(result.cancelled).toBe(true);
    expect(result.code).toBe(130);
    expect(events.at(-1)).toEqual({ type: "cancelled", got: "cancel" });
  });

  it("kills the process if it ignores cancel", async () => {
    const stubborn = script("import time, json\nprint(json.dumps({'type': 'stage', 'stage': 's', 'label': 'x'}), flush=True)\ntime.sleep(60)\n");
    let handle!: ReturnType<typeof runEngine>;
    handle = runEngine({ python, engineDir: repo, script: stubborn, graceMs: 300 }, [], (e) => {
      if (e.type === "stage") handle.cancel();
    });
    const started = Date.now();
    const result = await handle.done;
    expect(result.cancelled).toBe(true);
    expect(Date.now() - started).toBeLessThan(10_000);
  });

  it("explains a missing Python", async () => {
    const result = await runEngine({ python: "/no/such/python", engineDir: repo }, [], () => {}).done;
    expect(result.startError).toMatch(/Python was not found/);
  });
});
