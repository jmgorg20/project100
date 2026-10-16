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

export function Stages({ job }: { job: Job }) {
  const steps = job.auto || job.mode === "apply" ? STEPS : STEPS.slice(0, -1);
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
