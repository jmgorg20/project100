// The owner's admin pages (staff signed in with two-step sign-in): money and costs, users, sign-ups
// and invite codes, plans, and the system (queue, workers, audit log). In English: they are for the
// service's staff. Every change is written to the audit log by the service.
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, call, get, post } from "../api";
import { useRoute } from "../App";

interface Day { day: string; revenue_usd: number; cost_usd: number; jobs: number; minutes: number; signups: number }
interface Dashboard {
  days: number;
  users: { total: number; signups: number; verified: number };
  workspaces: { total: number; trialing: number; paying: number; by_status: Record<string, number> };
  money: { mrr_usd: number; revenue_usd: number; cost_usd: number; web_app_cost_usd: number; api_clients_cost_usd: number;
    margin_usd: number; margin_pct: number | null; failed_payments: number; not_converted: Record<string, number> };
  jobs: { total: number; succeeded: number; failed: number; minutes: number; cost_per_job_usd: number | null;
    cost_per_minute_usd: number | null; avg_seconds: number | null };
  system: { queued: number; running: number; workers_alive: number };
  series: Day[];
}

const usd = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "—" : `$${v.toFixed(digits)}`);
const TABS = ["overview", "costs", "users", "signups", "plans", "reports", "system"] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = { overview: "Overview", costs: "Costs", users: "Users", signups: "Sign-ups",
  plans: "Plans", reports: "Reports", system: "System" };

function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    if (!path) return;
    get<T>(path).then((d) => {
      setData(d);
      setError("");
    }).catch((err) => setError((err as ApiError).message));
  }, [path]);
  useEffect(load, [load]);
  return { data, error, reload: load };
}

export function Admin() {
  const route = useRoute();
  const tab = (TABS as readonly string[]).includes(route[1]) ? (route[1] as Tab) : "overview";
  const probe = useLoad<Dashboard>("/v1/admin/dashboard?days=30");
  if (probe.error) {
    return (
      <section className="card">
        <h1>Admin</h1>
        <p className="error" role="alert">{probe.error}</p>
        <p className="muted">Staff need two-step sign-in: turn it on in Account, then sign out and in again.</p>
      </section>
    );
  }
  return (
    <section className="stack admin">
      <h1>Admin</h1>
      <nav className="tabs" aria-label="Admin">
        {TABS.map((t) => <a key={t} href={`#/admin/${t}`} className={t === tab ? "active" : ""} aria-current={t === tab ? "page" : undefined}>{LABEL[t]}</a>)}
      </nav>
      {tab === "overview" && <Overview d={probe.data} />}
      {tab === "costs" && <Costs />}
      {tab === "users" && <Users />}
      {tab === "signups" && <Signups />}
      {tab === "plans" && <Plans />}
      {tab === "reports" && <Reports />}
      {tab === "system" && <System d={probe.data} />}
    </section>
  );
}

function Tile({ label, value, sub, testid }: { label: string; value: string; sub?: string; testid?: string }) {
  return (
    <div className="tile" data-testid={testid}>
      <span className="tile-label">{label}</span>
      <strong className="tile-value">{value}</strong>
      {sub && <small className="muted">{sub}</small>}
    </div>
  );
}

function Overview({ d }: { d: Dashboard | null }) {
  if (!d) return <p className="muted">Loading…</p>;
  const m = d.money;
  return (
    <>
      <div className="tiles" data-testid="kpis">
        <Tile label="Monthly recurring revenue" value={usd(m.mrr_usd)} sub={`${d.workspaces.paying} paying`} testid="kpi-mrr" />
        <Tile label={`Revenue, ${d.days} days`} value={usd(m.revenue_usd)} sub={m.failed_payments ? `${m.failed_payments} failed payments` : undefined} testid="kpi-revenue" />
        <Tile label={`Running cost, ${d.days} days`} value={usd(m.cost_usd)} sub={`web app ${usd(m.web_app_cost_usd)} · API clients ${usd(m.api_clients_cost_usd)}`} testid="kpi-cost" />
        <Tile label="Margin (web app)" value={usd(m.margin_usd)} sub={m.margin_pct === null ? "no revenue yet" : `${m.margin_pct}%`} testid="kpi-margin" />
        <Tile label="Cost per video" value={usd(d.jobs.cost_per_job_usd, 3)} sub={`${usd(d.jobs.cost_per_minute_usd, 3)} per minute`} testid="kpi-cost-job" />
        <Tile label="Videos" value={String(d.jobs.total)} sub={`${d.jobs.failed} failed · ${d.jobs.minutes.toFixed(0)} min`} />
        <Tile label="Free trials now" value={String(d.workspaces.trialing)} sub={`${d.workspaces.total} workspace${d.workspaces.total === 1 ? "" : "s"}`} />
        <Tile label="Sign-ups" value={String(d.users.signups)} sub={`${d.users.verified} confirmed · ${d.users.total} user${d.users.total === 1 ? "" : "s"}`} />
      </div>
      {Object.keys(m.not_converted).length > 0 && (
        <p className="warn">Not in the totals (no exchange rate, SERVICE_FX_RATES): {Object.entries(m.not_converted).map(([k, v]) => `${k} ${(v / 100).toFixed(2)}`).join(", ")}</p>
      )}
      <MoneyChart series={d.series} />
    </>
  );
}

const SERIES = [
  { key: "revenue_usd", label: "Revenue", cls: "s1" },
  { key: "cost_usd", label: "Running cost", cls: "s2" },
] as const;

/** Revenue and running cost per day: grouped bars on one dollar axis, with a legend, values on
 * hover or tap, and the same numbers as a table. */
export function MoneyChart({ series }: { series: Day[] }) {
  const [active, setActive] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const max = useMemo(() => Math.max(1, ...series.flatMap((d) => [d.revenue_usd, d.cost_usd])), [series]);
  const W = 640, H = 220, left = 44, bottom = 22, top = 10;
  const plotW = W - left - 8, plotH = H - bottom - top;
  const slot = plotW / Math.max(1, series.length);
  const bar = Math.max(1, Math.min(10, (slot - 4) / 2));
  const y = (v: number) => top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];
  const shown = active === null ? null : series[active];
  return (
    <figure className="card chart" data-testid="money-chart">
      <figcaption>
        <strong>Revenue and running cost per day (USD)</strong>
        <span className="legend">
          {SERIES.map((s) => <span key={s.key} className="legend-item"><i className={`swatch ${s.cls}`} aria-hidden />{s.label}</span>)}
        </span>
        <button className="small ghost" onClick={() => setAsTable(!asTable)}>{asTable ? "Show chart" : "Show table"}</button>
      </figcaption>
      {asTable ? (
        <div className="table-wrap">
          <table data-testid="money-table">
            <thead><tr><th>Day</th><th>Revenue</th><th>Running cost</th><th>Videos</th><th>Sign-ups</th></tr></thead>
            <tbody>{series.map((d) => <tr key={d.day}><td>{d.day}</td><td>{usd(d.revenue_usd)}</td><td>{usd(d.cost_usd)}</td><td>{d.jobs}</td><td>{d.signups}</td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="chart-box">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Revenue and running cost per day">
            {ticks.map((v) => (
              <g key={v}>
                <line x1={left} x2={W - 8} y1={y(v)} y2={y(v)} className="grid" />
                <text x={left - 6} y={y(v) + 4} className="axis" textAnchor="end">${v >= 10 ? v.toFixed(0) : v.toFixed(2)}</text>
              </g>
            ))}
            {series.map((d, i) => {
              const x = left + i * slot + (slot - (bar * 2 + 2)) / 2;
              return (
                <g key={d.day} onMouseEnter={() => setActive(i)} onClick={() => setActive(i)}>
                  <rect x={left + i * slot} y={top} width={slot} height={plotH} className="hit" />
                  {[d.revenue_usd, d.cost_usd].map((v, k) => v > 0 && (
                    <rect key={k} x={x + k * (bar + 2)} y={y(v)} width={bar} height={Math.max(0, top + plotH - y(v))}
                      rx={Math.min(4, bar / 2)} className={`col ${SERIES[k].cls}${active === i ? " on" : ""}`} />
                  ))}
                </g>
              );
            })}
            <line x1={left} x2={W - 8} y1={top + plotH} y2={top + plotH} className="baseline" />
            {series.length > 0 && <>
              <text x={left} y={H - 6} className="axis">{series[0].day.slice(5)}</text>
              <text x={W - 8} y={H - 6} className="axis" textAnchor="end">{series[series.length - 1].day.slice(5)}</text>
            </>}
          </svg>
          {!shown && <p className="muted tip-empty">Point at or tap a day to see its numbers.</p>}
          {shown && (
            <div className="tip" role="status" data-testid="chart-tip">
              <strong>{shown.day}</strong>
              <span><i className="swatch s1" aria-hidden />Revenue {usd(shown.revenue_usd)}</span>
              <span><i className="swatch s2" aria-hidden />Running cost {usd(shown.cost_usd)}</span>
              <span className="muted">{shown.jobs} videos</span>
            </div>
          )}
        </div>
      )}
    </figure>
  );
}

interface CostRow { client_id: string; name: string; kind: string; plan: string | null; status: string | null; jobs: number;
  minutes: number; cost_usd: number; revenue_usd: number; margin_usd: number | null }
interface CostReport { month: string; clients: CostRow[]; top_jobs: { job_id: string; name: string; kind: string | null;
  input_minutes: number; cpu_seconds: number; gpu_seconds: number; cost_usd: number }[];
  totals: { jobs: number; minutes: number; cost_usd: number; revenue_usd: number }; prices: Record<string, number> }

function Costs() {
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const { data, error } = useLoad<CostReport>(`/v1/admin/costs?month=${month}`);
  return (
    <div className="stack">
      <div className="row wrap">
        <label>Month<input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} /></label>
        <a className="button ghost" href={`/v1/admin/costs.csv?month=${month}`} download>Download CSV</a>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <>
          <p className="muted">{data.totals.jobs} videos · {data.totals.minutes.toFixed(1)} min · cost {usd(data.totals.cost_usd)} · revenue {usd(data.totals.revenue_usd)}.
            Costs are estimates from your prices (CPU ${data.prices.cost_cpu_second}/s, GPU ${data.prices.cost_gpu_second}/s, storage ${data.prices.cost_gb_month}/GB-month, downloads ${data.prices.cost_gb_egress}/GB).</p>
          <div className="table-wrap">
            <table data-testid="cost-table">
              <thead><tr><th>Client</th><th>Plan</th><th>Videos</th><th>Minutes</th><th>Cost</th><th>Revenue</th><th>Margin</th></tr></thead>
              <tbody>{data.clients.map((c) => (
                <tr key={c.client_id}><td>{c.name}{c.kind === "integration" && <small className="muted"> (API)</small>}</td>
                  <td>{c.plan ?? "—"}{c.status ? ` · ${c.status}` : ""}</td><td>{c.jobs}</td><td>{c.minutes.toFixed(1)}</td>
                  <td>{usd(c.cost_usd, 3)}</td><td>{usd(c.revenue_usd)}</td>
                  <td className={c.margin_usd !== null && c.margin_usd < 0 ? "error" : ""}>{c.margin_usd === null ? "contract" : usd(c.margin_usd)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <h3>Most costly videos</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Video</th><th>Client</th><th>Minutes</th><th>CPU s</th><th>GPU s</th><th>Cost</th></tr></thead>
              <tbody>{data.top_jobs.map((j) => (
                <tr key={j.job_id}><td><code>{j.job_id.slice(0, 12)}</code> {j.kind}</td><td>{j.name}</td><td>{j.input_minutes.toFixed(1)}</td>
                  <td>{j.cpu_seconds.toFixed(0)}</td><td>{j.gpu_seconds.toFixed(0)}</td><td>{usd(j.cost_usd, 3)}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

interface AdminUser { id: string; email: string; name: string | null; status: string; is_admin: number; mfa_enabled_at: number | null;
  created_at: number; organisations: { id: string; name: string; role: string }[] }

function Users() {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const { data, error, reload } = useLoad<{ users: AdminUser[] }>(`/v1/admin/users?limit=100${search ? `&q=${encodeURIComponent(search)}` : ""}`);
  const change = async (id: string, body: object, ask?: string) => {
    if (ask && !window.confirm(ask)) return;
    await call("PATCH", `/v1/admin/users/${id}`, body).catch((err) => window.alert((err as ApiError).message));
    reload();
  };
  return (
    <div className="stack">
      <form className="row" onSubmit={(e) => {
        e.preventDefault();
        setSearch(q);
      }}>
        <input className="grow" placeholder="Search by email" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search by email" />
        <button className="small">Search</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      <ul className="plain" data-testid="admin-users">
        {data?.users.map((u) => (
          <li key={u.id}>
            <strong>{u.email}</strong> {u.is_admin ? <span className="tag">staff</span> : null} {u.status === "disabled" && <span className="tag">disabled</span>}
            <br /><small className="muted">{new Date(u.created_at * 1000).toLocaleDateString()} · {u.organisations.map((o) => `${o.name} (${o.role})`).join(", ") || "no workspace"} · two-step {u.mfa_enabled_at ? "on" : "off"}</small>
            <div className="row wrap">
              {u.status === "active"
                ? <button className="small ghost danger" onClick={() => void change(u.id, { status: "disabled" }, `Disable ${u.email}? They are signed out everywhere.`)}>Disable</button>
                : <button className="small ghost" onClick={() => void change(u.id, { status: "active" })}>Enable</button>}
              <button className="small ghost" onClick={() => void change(u.id, { is_admin: !u.is_admin }, u.is_admin ? undefined : `Make ${u.email} staff?`)}>{u.is_admin ? "Remove staff" : "Make staff"}</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface Code { id: string; hint: string; note: string | null; max_uses: number; uses: number; expires_at: number | null; revoked_at: number | null }

function Signups() {
  const mode = useLoad<{ mode: string }>("/v1/admin/signups");
  const codes = useLoad<{ invite_codes: Code[] }>("/v1/admin/invite-codes");
  const [made, setMade] = useState<string | null>(null);
  const [form, setForm] = useState({ max_uses: 1, days: 30, note: "" });
  const setMode = async (m: string) => {
    await call("PUT", "/v1/admin/signups", { mode: m });
    mode.reload();
  };
  const create = async (e: FormEvent) => {
    e.preventDefault();
    const r = await post<{ code: string }>("/v1/admin/invite-codes", form);
    setMade(r.code);
    codes.reload();
  };
  return (
    <div className="stack">
      <div className="card">
        <h2>New sign-ups</h2>
        <div className="row wrap" role="radiogroup" aria-label="Sign-up mode" data-testid="signup-mode">
          {["invite", "open", "closed"].map((m) => (
            <button key={m} role="radio" aria-checked={mode.data?.mode === m} className={mode.data?.mode === m ? "small" : "small ghost"}
              onClick={() => void setMode(m)}>{m === "invite" ? "Invite code needed" : m === "open" ? "Open to all" : "Paused"}</button>
          ))}
        </div>
      </div>
      <div className="card">
        <h2>Invite codes</h2>
        <form className="row wrap" onSubmit={create}>
          <label>Uses<input type="number" min={1} max={10000} value={form.max_uses} onChange={(e) => setForm({ ...form, max_uses: Number(e.target.value) })} /></label>
          <label>Days<input type="number" min={1} max={365} value={form.days} onChange={(e) => setForm({ ...form, days: Number(e.target.value) })} /></label>
          <label className="grow">Note<input value={form.note} maxLength={200} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="e.g. Facebook group, batch 1" /></label>
          <button className="small">Make a code</button>
        </form>
        {made && <p className="ok" role="status" data-testid="new-code">New code (shown only now): <code className="secret">{made}</code></p>}
        <ul className="plain">
          {codes.data?.invite_codes.map((c) => (
            <li key={c.id}>{c.hint}… · {c.uses}/{c.max_uses} used{c.note ? ` · ${c.note}` : ""}{c.revoked_at ? " · revoked" : ""}
              {!c.revoked_at && <button className="small ghost danger" onClick={() => void call("DELETE", `/v1/admin/invite-codes/${c.id}`).then(codes.reload)}>Revoke</button>}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

interface PlanRow { id: string; name: string; price_cents: number; currency: string; billing_interval: string; monthly_minutes: number;
  storage_mb: number; concurrent_jobs: number; retention_days: number; provider_price_id: string | null; public: number; active: number }

function Plans() {
  const { data, error, reload } = useLoad<{ plans: PlanRow[] }>("/v1/admin/plans");
  return (
    <div className="stack">
      <p className="muted">Changing limits applies at once to every workspace on the plan. The price customers pay is set in Paddle: change it there too.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {data?.plans.map((p) => <PlanEditor key={p.id} plan={p} onSaved={reload} />)}
    </div>
  );
}

function PlanEditor({ plan, onSaved }: { plan: PlanRow; onSaved: () => void }) {
  const [v, setV] = useState({ price_cents: plan.price_cents, monthly_minutes: plan.monthly_minutes, storage_mb: plan.storage_mb,
    concurrent_jobs: plan.concurrent_jobs, retention_days: plan.retention_days, provider_price_id: plan.provider_price_id ?? "",
    public: Boolean(plan.public) });
  const [note, setNote] = useState("");
  const num = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: Number(e.target.value) });
  return (
    <form className="card" data-testid={`edit-plan-${plan.id}`} onSubmit={(e) => {
      e.preventDefault();
      void call("PUT", `/v1/admin/plans/${plan.id}`, { ...v, provider_price_id: v.provider_price_id || null })
        .then(() => {
          setNote("Saved.");
          onSaved();
        }).catch((err) => setNote((err as ApiError).message));
    }}>
      <h3>{plan.name} <small className="muted">({plan.id}, {plan.currency} per {plan.billing_interval})</small></h3>
      <div className="row wrap">
        <label>Price (cents)<input type="number" min={0} value={v.price_cents} onChange={num("price_cents")} /></label>
        <label>Minutes / month<input type="number" min={0} value={v.monthly_minutes} onChange={num("monthly_minutes")} /></label>
        <label>Storage MB<input type="number" min={0} value={v.storage_mb} onChange={num("storage_mb")} /></label>
        <label>At a time<input type="number" min={0} value={v.concurrent_jobs} onChange={num("concurrent_jobs")} /></label>
        <label>Keep files (days)<input type="number" min={0} max={30} value={v.retention_days} onChange={num("retention_days")} /></label>
        <label className="grow">Paddle price id<input value={v.provider_price_id} onChange={(e) => setV({ ...v, provider_price_id: e.target.value })} placeholder="pri_..." /></label>
        <label className="check"><input type="checkbox" checked={v.public} onChange={(e) => setV({ ...v, public: e.target.checked })} /><span>Shown to customers</span></label>
      </div>
      <button className="small">Save</button> {note && <span className="muted" role="status">{note}</span>}
    </form>
  );
}

interface ReportRow { id: string; reason: string; details: string | null; reporter_email: string | null; status: string;
  created_at: number; client_id: string | null; client_name: string | null; client_status: string | null; job_id: string | null;
  output_id: string | null; held_at: number | null; output_deleted_at: number | null; resolution: string | null }

const URGENT = new Set(["child_safety", "violence", "illegal"]);

function Reports() {
  const [status, setStatus] = useState("open");
  const { data, error, reload } = useLoad<{ reports: ReportRow[] }>(`/v1/admin/reports?status=${status}`);
  const [note, setNote] = useState("");
  const act = (r: ReportRow, action: string) => {
    const ask = action === "dismiss" ? "Release this video and close the report?" : action === "remove"
      ? "Delete this video's files now?" : "Delete the files AND suspend the whole workspace?";
    if (!window.confirm(ask)) return;
    void post(`/v1/admin/reports/${r.id}/resolve`, { action, note: note || undefined })
      .then(() => {
        setNote("");
        reload();
      }).catch((err) => window.alert((err as ApiError).message));
  };
  return (
    <div className="stack">
      <p className="muted">Reports come from anyone with a link (the "Report a video" page). A child-safety report, or reports
        from three different addresses, holds the video at once. Child sexual abuse material must not be deleted before it is
        reported to the authorities (Philippines: Republic Act 11930): follow docs/runbook.md, "Child safety report".</p>
      <div className="row wrap" role="radiogroup" aria-label="Report status">
        {["open", "dismissed", "removed", "suspended", "all"].map((s) => (
          <button key={s} role="radio" aria-checked={status === s} className={status === s ? "small" : "small ghost"} onClick={() => setStatus(s)}>{s}</button>
        ))}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {data && data.reports.length === 0 && <p className="muted" data-testid="no-reports">No {status === "all" ? "" : status} reports.</p>}
      {status === "open" && data && data.reports.length > 0 && (
        <label>Note for the record (optional)<input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></label>
      )}
      {data?.reports.map((r) => (
        <article key={r.id} className="card" data-testid={`report-${r.id}`}>
          <h3>{URGENT.has(r.reason) ? "⚠ " : ""}{r.reason.replace("_", " ")} <small className="muted">· {new Date(r.created_at * 1000).toLocaleString()}</small></h3>
          <p>{r.client_name ?? "(deleted)"} <small className="muted">({r.client_id}, {r.client_status ?? "?"})</small> · job <code>{r.job_id}</code></p>
          {r.details && <p className="quote">{r.details}</p>}
          <p className="muted">{r.reporter_email ? `From ${r.reporter_email}` : "No contact given"} ·{" "}
            {r.output_deleted_at ? "files deleted" : r.held_at ? "on hold (downloads stopped)" : "still downloadable"}</p>
          {r.resolution && <p className="muted">Note: {r.resolution}</p>}
          {r.status === "open" ? (
            <div className="row wrap">
              <button className="small ghost" onClick={() => act(r, "dismiss")}>Dismiss (release)</button>
              <button className="small danger" onClick={() => act(r, "remove")}>Remove video</button>
              <button className="small danger" onClick={() => act(r, "suspend")}>Remove + suspend workspace</button>
            </div>
          ) : (
            <div className="row wrap">
              <strong>{r.status}</strong>
              {r.status !== "dismissed" && r.held_at && !r.output_deleted_at && (
                <button className="small danger" onClick={() => {
                  if (window.confirm("Kept as evidence. Delete these files for good? Only after the authorities have what they need.")) {
                    void post(`/v1/admin/reports/${r.id}/purge`).then(reload).catch((err) => window.alert((err as ApiError).message));
                  }
                }}>Purge evidence files</button>
              )}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

interface Worker { id: string; name: string; queues: string[]; channel: string; status: string; engine_version: string | null; alive: boolean; last_seen_at: number | null }
interface Entry { id: string; at: number; actor: string; action: string; target: string | null; ip: string | null }

function System({ d }: { d: Dashboard | null }) {
  const workers = useLoad<{ workers: Worker[] }>("/v1/admin/workers");
  const audit = useLoad<{ entries: Entry[] }>("/v1/admin/audit?limit=50");
  return (
    <div className="stack">
      {d && (
        <div className="tiles">
          <Tile label="Waiting" value={String(d.system.queued)} />
          <Tile label="Editing now" value={String(d.system.running)} />
          <Tile label="Workers online" value={String(d.system.workers_alive)} />
        </div>
      )}
      <div className="card">
        <h2>Workers</h2>
        <ul className="plain">{workers.data?.workers.map((w) => (
          <li key={w.id}>{w.alive ? "● online" : "○ offline"} · <strong>{w.name}</strong> · {w.queues.join(", ")} · {w.channel} · {w.engine_version ?? "?"} · {w.status}</li>
        ))}</ul>
      </div>
      <div className="card">
        <h2>Audit log</h2>
        <div className="table-wrap">
          <table data-testid="audit">
            <thead><tr><th>When</th><th>Who</th><th>What</th><th>On</th></tr></thead>
            <tbody>{audit.data?.entries.map((e) => (
              <tr key={e.id}><td>{new Date(e.at * 1000).toLocaleString()}</td><td>{e.actor}</td><td>{e.action}</td><td><code>{e.target ?? ""}</code></td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
