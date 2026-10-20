// Runs the Python engine (`editor.py --json --stdin-control ...`) and turns its stdout
// JSON lines into events. Cancel = write "cancel" to stdin (the engine stops FFmpeg and
// deletes the unfinished file); if it has not exited after a grace period, the whole
// process tree is killed (on Windows a plain kill would leave FFmpeg running).
import { spawn as nodeSpawn, type ChildProcess, type SpawnOptions } from "node:child_process";
import * as path from "node:path";
import * as readline from "node:readline";
import type { EngineEvent } from "../shared/types";

export interface EngineConfig {
  python: string;
  engineDir: string;
  /** Extra environment (API keys). Never logged. */
  env?: Record<string, string>;
  /** The script to run; defaults to editor.py in engineDir (tests use a stand-in). */
  script?: string;
  graceMs?: number;
  /** After the engine exits, how long to wait for its output to close before finishing anyway. */
  exitGraceMs?: number;
  spawn?: (cmd: string, args: string[], opts: SpawnOptions) => ChildProcess;
}

export interface RunResult {
  code: number | null;
  cancelled: boolean;
  /** Set when the process could not start at all (e.g. Python not found). */
  startError?: string;
}

export interface RunHandle {
  done: Promise<RunResult>;
  cancel(): void;
  /** Is the engine process still there? (false once it exited, or if it never started) */
  alive?(): boolean;
  /** When the engine last wrote anything (ms since 1970). */
  lastActivity?(): number;
}

/** Does a process with this id exist? (signal 0 only asks; works on Windows too) */
export function pidAlive(pid: number | undefined): boolean {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

export function parseLine(line: string): EngineEvent | null {
  const text = line.trim();
  if (!text) return null;
  if (text.startsWith("{")) {
    try {
      const value = JSON.parse(text);
      if (value && typeof value.type === "string") return value as EngineEvent;
    } catch {
      // not JSON: fall through and treat it as a log line
    }
  }
  return { type: "log", message: text };
}

function killTree(child: ChildProcess, spawnFn: EngineConfig["spawn"]): void {
  if (child.exitCode !== null || child.pid === undefined) return;
  if (process.platform === "win32") {
    (spawnFn ?? nodeSpawn)("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
  } else {
    child.kill("SIGKILL");
  }
}

export function runEngine(config: EngineConfig, args: string[], onEvent: (e: EngineEvent) => void): RunHandle {
  const spawnFn = config.spawn ?? nodeSpawn;
  const script = config.script ?? path.join(config.engineDir, "editor.py");
  let cancelled = false;
  let child: ChildProcess;
  try {
    child = spawnFn(config.python, ["-u", script, "--json", "--stdin-control", ...args], {
      cwd: config.engineDir,
      env: { ...process.env, ...config.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
  } catch (error) {
    const message = `Could not start Python ("${config.python}"): ${(error as Error).message}`;
    return { done: Promise.resolve({ code: null, cancelled: false, startError: message }), cancel() {}, alive: () => false, lastActivity: () => Date.now() };
  }
  let lastActivity = Date.now();

  const done = new Promise<RunResult>((resolve) => {
    let startError: string | undefined;
    child.on("error", (error: NodeJS.ErrnoException) => {
      startError =
        error.code === "ENOENT"
          ? `Python was not found ("${config.python}"). Install Python 3.11+ or set its path in Settings.`
          : `Could not start Python: ${error.message}`;
    });
    if (child.stdout) {
      readline.createInterface({ input: child.stdout }).on("line", (line) => {
        lastActivity = Date.now();
        const event = parseLine(line);
        if (event) onEvent(event);
      });
    }
    if (child.stderr) {
      readline.createInterface({ input: child.stderr }).on("line", (line) => {
        lastActivity = Date.now();
        if (line.trim()) onEvent({ type: "log", message: line, stream: "stderr" });
      });
    }
    child.stdin?.on("error", () => {
      // The engine may exit before we write to it; nothing to do.
    });
    let finished = false;
    const finish = (code: number | null) => {
      if (finished) return;
      finished = true;
      resolve({ code, cancelled, startError });
    };
    child.on("close", (code) => finish(code));
    // "close" waits until the engine's output pipes are closed. A process the engine started can
    // keep them open after the engine itself has exited, and the job would then wait for ever: so
    // once the engine has exited, the job ends shortly after even if the pipes stay open.
    child.on("exit", (code) => {
      const timer = setTimeout(() => {
        if (finished) return;
        onEvent({ type: "log", message: "The engine exited but its output stayed open; finishing anyway.", stream: "stderr" });
        child.stdout?.destroy();
        child.stderr?.destroy();
        finish(code);
      }, config.exitGraceMs ?? 3_000);
      child.on("close", () => clearTimeout(timer));
    });
  });

  return {
    done,
    alive: () => child.exitCode === null && child.signalCode === null && pidAlive(child.pid),
    lastActivity: () => lastActivity,
    cancel() {
      if (cancelled || child.exitCode !== null) return;
      cancelled = true;
      try {
        child.stdin?.write("cancel\n");
        child.stdin?.end();
      } catch {
        // stdin already closed
      }
      const timer = setTimeout(() => killTree(child, config.spawn), config.graceMs ?? 10_000);
      child.on("close", () => clearTimeout(timer));
    },
  };
}
