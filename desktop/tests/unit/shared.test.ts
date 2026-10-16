import { describe, expect, it } from "vitest";
import { fileUrl } from "../../src/shared/fileUrl";
import { addVersion, canRedo, canUndo, currentVersion, emptyHistory, redo, undo } from "../../src/shared/history";
import { applyEvent, finishJob, newJob, versionFromJob } from "../../src/shared/jobs";
import { acceptedPlan, formatCost, mmss, planItems } from "../../src/shared/planItems";
import type { EngineEvent, Job, JobRequest, Plan, Version } from "../../src/shared/types";

const request: JobRequest = { video: "C:/v/talk.mp4", photos: [], instruction: "fast", provider: "groq", auto: true, mode: "new" };

function basePlan(): Plan {
  return {
    summary: "", style: "yellow_pop", grade: "natural_clean",
    pacing: { silence_threshold: 0.25, remove_fillers: true }, zoom: { enabled: true, amount: 1.15 },
    captions: { enabled: true, size_scale: 1, position: null, highlight_words: [] },
    cuts: [], zooms: [], grades: [], effects: [], photos: [], notes: [], ai_clips: [], voiceovers: [],
  };
}

function run(job: Job, events: EngineEvent[]): Job {
  return events.reduce(applyEvent, job);
}

describe("job events", () => {
  it("follows the stages and keeps the results", () => {
    const plan = { ...basePlan(), style: "bold_caps" };
    const job = run(newJob("j1", request, 5), [
      { type: "stage", stage: "transcript", label: "Listening" },
      { type: "transcript", words: 120, cached: true, text: "..." },
      { type: "stage", stage: "plan", label: "Planning" },
      { type: "plan", plan, baseline: basePlan(), fallback: false, reason: "", cached: false, given: false, model: "m", cost: 0.001, attempts: [] },
      { type: "stage", stage: "render", label: "Rendering" },
      { type: "progress", stage: "render", percent: 40 },
      { type: "log", message: "hello" },
      { type: "result", output: "/o/a.mp4", project: "/o/a.project.json", plan: "/o/a.plan.json" },
    ]);
    expect(job.stagesDone).toEqual(["transcript", "plan"]);
    expect(job.stage).toBe("render");
    expect(job.percent).toBe(40);
    expect(job.transcriptCached).toBe(true);
    expect(job.plan?.style).toBe("bold_caps");
    expect(job.planBaseline?.style).toBe("yellow_pop");
    expect(job.log).toEqual(["hello"]);
    expect(job.output).toBe("/o/a.mp4");

    const done = finishJob(job, 0, false);
    expect(done.status).toBe("done");
    expect(done.stagesDone).toEqual(["transcript", "plan", "render"]);
    const version = versionFromJob(done, 9) as Version;
    expect(version).toMatchObject({ jobId: "j1", output: "/o/a.mp4", planFile: "/o/a.plan.json", createdAt: 9 });
  });

  it("ends in review, cancelled or failed as appropriate", () => {
    const base = newJob("j", { ...request, auto: false });
    expect(finishJob(base, 0, false).status).toBe("review");
    expect(finishJob({ ...base, mode: "apply" }, 0, false).status).toBe("done");
    expect(finishJob(base, 130, true).status).toBe("cancelled");
    const failed = finishJob(applyEvent(base, { type: "error", message: "No Groq API key." }), 1, false);
    expect(failed).toMatchObject({ status: "failed", error: "No Groq API key." });
    expect(finishJob(base, 3, false).error).toContain("exit code 3");
    expect(finishJob(base, null, false, "Python was not found").error).toBe("Python was not found");
    expect(versionFromJob(finishJob(base, 0, false))).toBeNull();
  });
});

describe("version history", () => {
  const v = (id: string): Version => ({ id, jobId: id, instruction: id, mode: "new", output: `${id}.mp4`, projectFile: "", planFile: "", createdAt: 0 });

  it("undoes back to the original video and redoes forward", () => {
    let h = addVersion(addVersion(emptyHistory("a.mp4"), v("1")), v("2"));
    expect(currentVersion(h)?.id).toBe("2");
    expect(canRedo(h)).toBe(false);
    h = undo(h);
    expect(currentVersion(h)?.id).toBe("1");
    h = undo(h);
    expect(currentVersion(h)).toBeNull(); // the original video
    expect(canUndo(h)).toBe(false);
    expect(undo(h)).toBe(h);
    h = redo(redo(h));
    expect(currentVersion(h)?.id).toBe("2");
    expect(redo(h)).toBe(h);
  });

  it("keeps later versions when a new edit is made after undo", () => {
    let h = addVersion(addVersion(emptyHistory("a"), v("1")), v("2"));
    h = addVersion(undo(h), v("3"));
    expect(h.versions.map((x) => x.id)).toEqual(["1", "2", "3"]);
    expect(currentVersion(h)?.id).toBe("3");
  });
});

describe("plan review", () => {
  const plan: Plan = {
    ...basePlan(), style: "bold_caps", grade: "warm",
    captions: { enabled: true, size_scale: 1.3, position: "top", highlight_words: ["GCash"] },
    cuts: [{ start: 41, end: 47.5, reason: "retake" }],
    photos: [{ file: "receipt.png", at: 20, duration: 3, position: "top", reason: "when you say resibo" }],
  };

  it("lists only what the AI changed", () => {
    const items = planItems(plan, basePlan());
    expect(items.map((i) => i.id)).toEqual([
      "style", "captions.size_scale", "captions.position", "captions.highlight_words", "grade", "cuts.0", "photos.0",
    ]);
    expect(items.find((i) => i.id === "captions.size_scale")?.label).toBe("Captions 30% bigger");
    expect(items.find((i) => i.id === "cuts.0")?.label).toBe("Remove 0:41–0:48");
    expect(planItems(basePlan(), basePlan())).toEqual([]);
  });

  it("puts rejected changes back to the preset", () => {
    const kept = acceptedPlan(plan, basePlan(), new Set(["style", "photos.0"]));
    expect(kept.style).toBe("bold_caps");
    expect(kept.grade).toBe("natural_clean");
    expect(kept.captions).toEqual(basePlan().captions);
    expect(kept.cuts).toEqual([]);
    expect(kept.photos).toHaveLength(1);
    const all = acceptedPlan(plan, basePlan(), new Set(planItems(plan, basePlan()).map((i) => i.id)));
    expect(all).toEqual(plan);
  });

  it("lists planned effects (transitions on a cut) and drops the rejected ones", () => {
    const withFx: Plan = {
      ...basePlan(),
      effects: [
        { effect: "flash", at: 12, duration: 0.3, intensity: 1, on_cut: true, reason: "new topic" },
        { effect: "shake", at: 31, duration: 0.4, intensity: 0.7, on_cut: false, reason: "punchline" },
      ],
    };
    const items = planItems(withFx, basePlan());
    expect(items.map((i) => [i.id, i.group, i.label])).toEqual([
      ["effects.0", "Effects", "Flash transition at 0:12"],
      ["effects.1", "Effects", "Shake at 0:31"],
    ]);
    expect(acceptedPlan(withFx, basePlan(), new Set(["effects.1"])).effects?.map((e) => e.effect)).toEqual(["shake"]);
    expect(planItems({ ...basePlan(), effects: undefined }, basePlan())).toEqual([]);
  });

  it("lists AI clips and voice-overs, and drops the rejected ones", () => {
    const withAi: Plan = {
      ...basePlan(),
      ai_clips: [
        { kind: "video", prompt: "steam over coffee", search: "coffee steam", style: "realistic", source: "auto", at: 12, duration: 3, position: "full", reason: "b-roll" },
        { kind: "image", prompt: "a sari-sari store", search: "store", style: "cartoon", source: "ai", at: 30, duration: 2, position: "top", reason: "when you say tindahan" },
      ],
      voiceovers: [{ text: "Salamat sa panonood!", at: 50, reason: "outro" }],
    };
    const items = planItems(withAi, basePlan());
    expect(items.map((i) => i.id)).toEqual(["ai_clips.0", "ai_clips.1", "voiceovers.0"]);
    expect(items[0].label).toBe("B-roll video clip at 0:12: “steam over coffee”");
    expect(items[1].label).toBe("AI picture at 0:30: “a sari-sari store” (cartoon)");
    expect(items.every((i) => i.group === "B-roll & AI clips")).toBe(true);
    const kept = acceptedPlan(withAi, basePlan(), new Set(["ai_clips.1"]));
    expect(kept.ai_clips?.map((c) => c.prompt)).toEqual(["a sari-sari store"]);
    expect(kept.voiceovers).toEqual([]);
  });

  it("formats times and costs", () => {
    expect(mmss(0)).toBe("0:00");
    expect(mmss(61.4)).toBe("1:01");
    expect(formatCost(null)).toBe("unknown");
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(0.00166)).toBe("$0.0017"); // same rounding as the engine
    expect(formatCost(0.123)).toBe("$0.12");
  });
});

describe("file URLs", () => {
  it("handles Windows, POSIX, UNC and odd characters", () => {
    expect(fileUrl("C:\\Users\\Juan\\Videos\\my video #1.mp4")).toBe("file:///C:/Users/Juan/Videos/my%20video%20%231.mp4");
    expect(fileUrl("/home/a/b%c?.mp4")).toBe("file:///home/a/b%25c%3F.mp4");
    expect(fileUrl("\\\\server\\share\\x.mp4")).toBe("file://server/share/x.mp4");
    expect(fileUrl("C:/Parañaque/ñ.png")).toBe("file:///C:/Para%C3%B1aque/%C3%B1.png");
  });
});
