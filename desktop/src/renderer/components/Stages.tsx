// The AI edit's steps, lit up as the engine finishes each one.
import type { Job } from "../../shared/types";

const STEPS: [string, string][] = [
  ["transcript", "Transcript"],
  ["plan", "AI plan"],
  ["cuts", "Silence cuts"],
  ["zooms", "Jump cuts & zooms"],
  ["captions", "Captions"],
  ["photos", "Photos"],
  ["render", "Render"],
];

// Shown only when the plan asks for B-roll (your folder, free stock, AI) or AI voice-over.
const AI_STEPS: [string, string][] = [
  ["broll", "B-roll"],
  ["ai_draft", "AI clips (draft)"],
  ["ai_final", "AI clips (final)"],
];

export function Stages({ job }: { job: Job }) {
  const render = job.auto || job.mode === "apply";
  const seen = (key: string) => job.stage === key || job.stagesDone.includes(key);
  const wantsAi = Boolean(job.plan?.ai_clips?.length || job.plan?.voiceovers?.length);
  // Auto mode: draft then final. Review first: draft only. Applying a reviewed plan: final only.
  const wantsBroll = Boolean(job.plan?.ai_clips?.length);
  const ai = AI_STEPS.filter(([key]) =>
    seen(key) || (key === "broll" ? wantsBroll : wantsAi && (key === "ai_draft" ? job.mode !== "apply" : render)),
  );
  const steps = [...STEPS.slice(0, 2), ...ai, ...STEPS.slice(2, render ? undefined : -1)];
  return (
    <div className="stages" aria-label="Progress" data-testid="stages">
      {steps.map(([key, label]) => {
        const done = job.stagesDone.includes(key);
        const active = job.stage === key;
        const pct = active && job.percent !== undefined ? ` ${Math.round(job.percent)}%` : "";
        return (
          <span key={key} className={`step${done ? " done" : ""}${active ? " active" : ""}`} data-step={key} data-state={active ? "active" : done ? "done" : "todo"}>
            <span className="dot" />
            {label}
            {pct}
            {done && key === "transcript" && job.transcriptCached ? " (saved)" : ""}
            {done && key === "plan" && job.planCached ? " (saved)" : ""}
          </span>
        );
      })}
    </div>
  );
}
