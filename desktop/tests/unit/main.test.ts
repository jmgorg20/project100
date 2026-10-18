import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { HistoryStore } from "../../src/main/historyStore";
import { freeOutputPath, jobArgs } from "../../src/main/jobArgs";
import { KeyStore, type Encryptor } from "../../src/main/keys";
import { JobQueue } from "../../src/main/queue";
import { cleanSettings, defaultSettings, loadSettings, saveSettings } from "../../src/main/settings";
import type { RunHandle, RunResult } from "../../src/main/engine";
import { newJob } from "../../src/shared/jobs";
import type { EngineEvent, Job, JobRequest } from "../../src/shared/types";

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "autoedit-"));

const fakeCrypto = (available = true): Encryptor => ({
  isEncryptionAvailable: () => available,
  encryptString: (s) => Buffer.from(`enc:${[...s].reverse().join("")}`),
  decryptString: (b) => [...b.toString().slice(4)].reverse().join(""),
});

describe("API keys", () => {
  it("stores keys encrypted and only hands them out as engine environment", () => {
    const file = path.join(tmp(), "keys.json");
    const store = new KeyStore(file, fakeCrypto());
    store.set("groq", "  gsk_secret1234  ");
    expect(fs.readFileSync(file, "utf-8")).not.toContain("gsk_secret1234");
    expect(store.status()).toEqual({
      encryptionAvailable: true,
      groq: { set: true, hint: "••••1234" },
      anthropic: { set: false, hint: "" },
      pexels: { set: false, hint: "" },
      pixabay: { set: false, hint: "" },
    });
    expect(store.env()).toEqual({ GROQ_API_KEY: "gsk_secret1234" });
    // Free stock keys (B-roll) are kept the same way.
    store.set("pexels", "pexels-key-9876");
    store.set("pixabay", "pixabay-key-5555");
    expect(fs.readFileSync(file, "utf-8")).not.toMatch(/9876|5555/);
    expect(store.status().pexels).toEqual({ set: true, hint: "••••9876" });
    expect(store.env()).toEqual({ GROQ_API_KEY: "gsk_secret1234", PEXELS_API_KEY: "pexels-key-9876", PIXABAY_API_KEY: "pixabay-key-5555" });
    store.clear("pexels");
    store.clear("pixabay");
    expect(() => store.set("openai" as never, "x")).toThrow(/Unknown/);
    store.clear("groq");
    expect(store.env()).toEqual({});
  });

  it("refuses to save without encryption, and rejects bad keys", () => {
    const store = new KeyStore(path.join(tmp(), "k.json"), fakeCrypto(false));
    expect(() => store.set("anthropic", "sk-ant-1")).toThrow(/cannot encrypt/);
    const ok = new KeyStore(path.join(tmp(), "k.json"), fakeCrypto());
    expect(() => ok.set("groq", "   ")).toThrow(/empty/);
    expect(() => ok.set("groq", "gsk a")).toThrow(/spaces/);
  });
});

describe("settings", () => {
  it("defaults to Auto mode on, Groq, and safe values for anything odd", () => {
    const d = defaultSettings("win32", "C:/app");
    expect(d).toMatchObject({ autoMode: true, provider: "groq", pythonPath: "python", consentAccepted: false });
    const cleaned = cleanSettings({ autoMode: "yes", provider: "openai", groqModel: "x", extra: 1 }, d);
    expect(cleaned.autoMode).toBe(true);
    expect(cleaned.provider).toBe("groq");
    expect(cleaned.groqModel).toBe("x");
    expect("extra" in cleaned).toBe(false);
    const file = path.join(tmp(), "s.json");
    saveSettings(file, { ...d, autoMode: false });
    expect(loadSettings(file, d).autoMode).toBe(false);
    fs.writeFileSync(file, "{broken");
    expect(loadSettings(file, d)).toEqual(d);
  });
});

describe("job arguments", () => {
  const settings = defaultSettings("linux", "/engine");
  const job = (r: Partial<JobRequest>): Job => newJob("j", { video: "/v/a.mp4", photos: [], instruction: "", provider: "groq", auto: true, mode: "new", ...r });
  const files = { instructionFile: "/d/i.txt", output: "/o/a_ai.mp4" };

  it("builds the engine command for each mode", () => {
    expect(jobArgs(job({}), settings, files)).toEqual([
      "ai-edit", "/v/a.mp4", "--output", "/o/a_ai.mp4", "--provider", "groq", "--model", "openai/gpt-oss-120b",
      "--transcribe-with", "groq", "--instruction-file", "/d/i.txt",
    ]);
    expect(jobArgs(job({ auto: false }), settings, files)).toContain("--no-render");
    const followup = jobArgs(job({ mode: "followup", planFile: "/o/a.plan.json", provider: "anthropic" }), settings, files);
    expect(followup).toEqual(expect.arrayContaining(["--previous-plan", "/o/a.plan.json", "claude-opus-5-5"]));
    const apply = jobArgs(job({ auto: false, mode: "apply", planFile: "/p.json", photos: ["/x.png", "/y.png"] }), settings, files);
    expect(apply).not.toContain("--no-render");
    expect(apply.slice(-5)).toEqual(["--plan-file", "/p.json", "--photos", "/x.png", "/y.png"]);
    // Your B-roll folder and "no stock" go to the engine; nothing is added when unset.
    expect(jobArgs(job({}), settings, files)).not.toContain("--broll-library");
    const broll = jobArgs(job({ photos: ["/x.png"] }), { ...settings, brollFolder: "D:/My B-roll", useStock: false }, files);
    expect(broll.slice(-5)).toEqual(["--broll-library", "D:/My B-roll", "--no-stock", "--photos", "/x.png"]);
    // Per-video AI generation limits, before --photos (which takes the rest of the list).
    const limited = jobArgs(job({ maxGenMinutes: 12, maxAiClips: 0, photos: ["/x.png"] }), settings, files);
    expect(limited.slice(-6)).toEqual(["--max-generation-minutes", "12", "--max-ai-clips", "0", "--photos", "/x.png"]);
    expect(jobArgs(job({}), settings, files)).not.toContain("--max-ai-clips");
    // Video formats: the format, its files by role, list items and the second video's offset.
    const fmt = jobArgs(job({
      format: "reaction", formatInputs: { source: ["C:/v/clip.mp4"], takes: ["/t1.mp4", "/t2.mp4"] },
      items: ["Mag-ipon", " ", "Mag-invest "], offsets: { source: 1.5, second: 0 }, photos: ["/x.png"],
    }), settings, files);
    expect(fmt.slice(-16)).toEqual([
      "--format", "reaction", "--input", "source=C:/v/clip.mp4", "--input", "takes=/t1.mp4", "--input", "takes=/t2.mp4",
      "--item", "Mag-ipon", "--item", "Mag-invest", "--offset", "source=1.5", "--photos", "/x.png",
    ]);
    expect(jobArgs(job({}), settings, files)).not.toContain("--format");
  });

  it("never reuses an output name", () => {
    const dir = tmp();
    const taken = new Set<string>();
    const first = freeOutputPath(dir, "/v/talk.mp4", taken);
    expect(path.basename(first)).toBe("talk_ai.mp4");
    taken.add(first);
    expect(path.basename(freeOutputPath(dir, "/v/talk.mp4", taken))).toBe("talk_ai_2.mp4");
    fs.writeFileSync(path.join(dir, "talk_ai_2.project.json"), "{}");
    expect(path.basename(freeOutputPath(dir, "/v/talk.mp4", taken))).toBe("talk_ai_3.mp4");
  });
});

describe("history store", () => {
  it("persists versions per video", () => {
    const file = path.join(tmp(), "h.json");
    const store = new HistoryStore(file);
    store.add("a.mp4", { id: "v1", jobId: "1", instruction: "", mode: "new", output: "1.mp4", projectFile: "", planFile: "", createdAt: 0 });
    store.undo("a.mp4");
    const again = new HistoryStore(file);
    expect(again.get("a.mp4").current).toBe(-1);
    expect(again.redo("a.mp4").current).toBe(0);
    expect(again.get("b.mp4").versions).toEqual([]);
  });
});

describe("job queue", () => {
  function fakeRunner() {
    const runs: { job: Job; emit: (e: EngineEvent) => void; finish: (r: RunResult) => void; cancelled: boolean }[] = [];
    const run = (job: Job, onEvent: (e: EngineEvent) => void): RunHandle => {
      let finish!: (r: RunResult) => void;
      const done = new Promise<RunResult>((resolve) => (finish = resolve));
      const entry = { job, emit: onEvent, finish, cancelled: false };
      runs.push(entry);
      return { done, cancel: () => { entry.cancelled = true; finish({ code: 130, cancelled: true }); } };
    };
    return { runs, run };
  }
  const req = (video: string): JobRequest => ({ video, photos: [], instruction: "x", provider: "groq", auto: true, mode: "new" });

  it("runs a batch one video at a time and reports every change", async () => {
    const { runs, run } = fakeRunner();
    const finished: Job[] = [];
    let id = 0;
    const queue = new JobQueue({ run, onChange: () => {}, onFinished: (j) => finished.push(j), makeId: () => `j${++id}` });
    queue.add([req("a.mp4"), req("b.mp4"), req("c.mp4")]);
    expect(runs).toHaveLength(1);
    expect(queue.jobs.map((j) => j.status)).toEqual(["running", "queued", "queued"]);
    queue.cancel("j2");                                     // cancel a queued one
    runs[0].emit({ type: "stage", stage: "plan", label: "Planning" });
    expect(queue.get("j1")?.stage).toBe("plan");
    runs[0].emit({ type: "result", output: "a.mp4", project: "a.p.json", plan: "a.plan.json" });
    runs[0].finish({ code: 0, cancelled: false });
    await new Promise((r) => setTimeout(r, 0));
    expect(runs).toHaveLength(2);
    expect(runs[1].job.video).toBe("c.mp4");                // b was skipped
    queue.cancel("j3");
    await queue.whenIdle();
    expect(queue.jobs.map((j) => j.status)).toEqual(["done", "cancelled", "cancelled"]);
    expect(runs[1].cancelled).toBe(true);
    expect(finished.map((j) => j.id)).toEqual(["j1", "j3"]);
  });
});
