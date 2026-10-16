// Auto mode off: the AI's changes as a checklist. Nothing is applied until "Apply & render".
import { useMemo, useState } from "react";
import { acceptedPlan, planItems } from "../../shared/planItems";
import type { Job } from "../../shared/types";

interface Props {
  job: Job;
  onApply: (plan: NonNullable<Job["plan"]>) => void;
  onReject: () => void;
}

export function PlanReview({ job, onApply, onReject }: Props) {
  const plan = job.plan!;
  const base = job.planBaseline ?? plan;
  const items = useMemo(() => planItems(plan, base), [plan, base]);
  const [accepted, setAccepted] = useState<Set<string>>(() => new Set(items.map((i) => i.id)));
  const toggle = (id: string) =>
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  let lastGroup = "";
  return (
    <section className="card" data-testid="review" aria-label="Review the AI changes">
      <h3>Review the AI's changes</h3>
      <p className="muted small" style={{ marginTop: 0 }}>
        Auto mode is off, so nothing is applied yet. Pauses, captions and zooms from the preset are always included.
      </p>
      {job.planFallback && <p className="warn" role="alert">{job.planReason}</p>}
      {items.length === 0 ? (
        <p className="muted">The AI kept the preset edit; there is nothing extra to review.</p>
      ) : (
        <div>
          {items.map((item) => {
            const header = item.group !== lastGroup ? <div className="plan-group">{item.group}</div> : null;
            lastGroup = item.group;
            return (
              <div key={item.id}>
                {header}
                <label className="plan-item">
                  <input type="checkbox" checked={accepted.has(item.id)} onChange={() => toggle(item.id)} />
                  <span>
                    {item.label}
                    {item.detail && <span className="muted small"> — {item.detail}</span>}
                  </span>
                </label>
              </div>
            );
          })}
        </div>
      )}
      {plan.notes.length > 0 && (
        <p className="muted small">Not possible: {plan.notes.join(" ")}</p>
      )}
      <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
        <button className="btn small" onClick={() => setAccepted(new Set(items.map((i) => i.id)))}>Accept all</button>
        <button className="btn small" onClick={() => setAccepted(new Set())}>Uncheck all</button>
        <span style={{ flex: 1 }} />
        <button className="btn small danger" onClick={onReject}>Reject</button>
        <button className="btn small primary" onClick={() => onApply(acceptedPlan(plan, base, accepted))}>
          Apply & render ({accepted.size}/{items.length})
        </button>
      </div>
    </section>
  );
}
