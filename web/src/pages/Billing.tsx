import { useEffect, useState } from "react";
import { ApiError, get, post, type Billing as BillingView, type PlanInfo } from "../api";
import { query } from "../App";
import { getLang, t, useLang } from "../i18n";

function money(cents: number, currency: string) {
  try {
    return new Intl.NumberFormat(getLang() === "tl" ? "en-PH" : undefined, { style: "currency", currency }).format(cents / 100);
  } catch {
    return `${(cents / 100).toFixed(2)} ${currency}`;
  }
}

const date = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleDateString() : "");

export function useBilling() {
  const [billing, setBilling] = useState<BillingView | null>(null);
  useEffect(() => {
    get<BillingView>("/v1/billing").then(setBilling).catch(() => setBilling(null));
  }, []);
  return billing;
}

/** A short line on the New video page: trial days left, or why videos are paused. */
export function BillingBanner() {
  useLang();
  const b = useBilling();
  if (!b || !b.enabled) return null;
  if (b.mode === "trial" && b.trial_days_left !== null) {
    return <p className="banner-inline" data-testid="billing-banner">{t("trialLeft", { days: Math.ceil(b.trial_days_left) })} · <a href="#/account">{t("seePlans")}</a></p>;
  }
  if (b.mode === "locked") {
    return (
      <div className="card warn-card" data-testid="billing-banner" role="status">
        <strong>{b.reason === "trial_ended" ? t("trialEndedTitle") : t("needPlan")}</strong>
        {b.reason === "trial_ended" && <p>{t("needPlan")}</p>}
        <a className="button" href="#/account">{t("seePlans")}</a>
      </div>
    );
  }
  if (b.reason === "payment_failed") return <p className="banner-inline warn" data-testid="billing-banner">{t("paymentProblem")} <a href="#/account">{t("manageBilling")}</a></p>;
  return null;
}

function PlanCard({ plan, current, canBuy, onChoose, busy }: { plan: PlanInfo; current: boolean; canBuy: boolean; onChoose: () => void; busy: boolean }) {
  const tl = getLang() === "tl";
  return (
    <li className={current ? "plan on" : "plan"} data-testid={`plan-${plan.id}`}>
      <strong>{tl && plan.name_tl ? plan.name_tl : plan.name}</strong>
      <span className="price">{t("perInterval", { price: money(plan.price_cents, plan.currency), interval: t(plan.billing_interval) })}</span>
      <small className="muted">{tl && plan.description_tl ? plan.description_tl : plan.description}</small>
      {current ? <span className="tag">{t("currentPlan")}</span>
        : canBuy && <button className="small" disabled={busy} onClick={onChoose}>{t("choosePlan")}</button>}
    </li>
  );
}

/** The billing card on the Account page. */
export function BillingCard() {
  useLang();
  const [b, setB] = useState<BillingView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const returned = query("billing");
  useEffect(() => {
    get<BillingView>("/v1/billing").then(setB).catch((err) => setError((err as ApiError).status === 404 ? "" : (err as ApiError).message));
  }, []);
  if (!b || !b.enabled) return null;
  const go = async (path: string, body?: unknown) => {
    setBusy(true);
    setError("");
    try {
      const r = await post<{ url: string }>(path, body);
      window.location.assign(r.url);                  // the provider's page (or the test checkout)
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  };
  const used = b.usage.minutes;
  const limit = b.usage.minutes_limit;
  return (
    <div className="card" data-testid="billing">
      <h2>{t("plan")}</h2>
      {returned === "success" && <p className="ok" role="status">{t("billingThanks")}</p>}
      {returned === "cancelled" && <p className="muted" role="status">{t("billingCancelled")}</p>}
      {b.mode === "trial" && b.trial_days_left !== null && <p data-testid="billing-state">{t("trialLeft", { days: Math.ceil(b.trial_days_left) })}</p>}
      {b.mode === "locked" && <p className="warn" data-testid="billing-state">{b.reason === "trial_ended" ? t("trialEndedTitle") : ""} {t("needPlan")}</p>}
      {b.reason === "payment_failed" && <p className="warn">{t("paymentProblem")}</p>}
      {b.cancel_at_period_end && b.current_period_end && <p className="muted">{t("canceling", { date: date(b.current_period_end) })}</p>}
      {limit > 0 && (
        <div className="meter" data-testid="usage-meter">
          <div className="bar"><div style={{ width: `${Math.min(100, (used / limit) * 100)}%` }} /></div>
          <small className="muted">{t("minutesUsed", { used: used.toFixed(1), limit: limit.toFixed(0) })}</small>
        </div>
      )}
      <ul className="plans">
        {b.plans.map((p) => (
          <PlanCard key={p.id} plan={p} current={b.plan?.id === p.id && b.mode === "plan"} busy={busy}
            canBuy={b.can_manage && b.online_payment} onChoose={() => void go("/v1/billing/checkout", { plan_id: p.id })} />
        ))}
      </ul>
      {!b.can_manage && <p className="muted">{t("onlyManagers")}</p>}
      {b.can_manage && !b.online_payment && <p className="muted">{t("contactForPlan")}</p>}
      {b.can_manage && b.has_portal && <button className="ghost" disabled={busy} onClick={() => void go("/v1/billing/portal")}>{t("manageBilling")}</button>}
      {b.payments.length > 0 && (
        <details>
          <summary>{t("payments")}</summary>
          <ul className="plain">{b.payments.map((p, i) => <li key={i}>{date(p.occurred_at)} · {money(p.amount_cents, p.currency)} · {p.status}</li>)}</ul>
        </details>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
