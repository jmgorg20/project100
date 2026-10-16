// "What the AI did", in plain words, with the cost and the undo / redo buttons.
import { formatCost } from "../../shared/planItems";
import type { Summary } from "../../shared/types";

interface Props {
  summary: Summary;
  title?: string;
  children?: React.ReactNode;
}

export function SummaryCard({ summary, title = "What the AI did", children }: Props) {
  const cost = summary.cost;
  return (
    <section className="card" data-testid="summary" aria-label={title}>
      <h3>{title}</h3>
      {summary.fallback ? (
        <p className="warn" role="alert">{summary.headline}</p>
      ) : (
        <p style={{ marginTop: 0 }}>{summary.headline}</p>
      )}
      <ul>
        {summary.details.map((line, i) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
      {cost && (
        <p className="muted small" data-testid="cost">
          API cost: about {formatCost(cost.total)}
          {cost.paid_provider ? ` (Anthropic, ${cost.model})` : ` (Groq ${cost.model}; $0 on the free tier)`}
          {cost.transcript_cached ? " · transcript was saved" : ""}
          {cost.plan_cached ? " · plan was saved" : ""}
        </p>
      )}
      {children}
    </section>
  );
}
