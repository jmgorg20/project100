import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, call, get, post, type Me, type Session } from "../api";
import { go, type SessionProps } from "../App";
import { getLang, setLang, t, useLang, type Lang } from "../i18n";
import { BillingCard, useBilling } from "./Billing";

interface Device {
  id: string;
  user_agent: string | null;
  last_seen_at: number;
  current: boolean;
}
interface Member {
  user_id: string;
  email: string;
  name: string | null;
  role: string;
}

function msg(err: unknown) {
  return err instanceof ApiError ? err.message : t("tryAgain");
}

export function Account({ session, refresh, setSession }: SessionProps) {
  useLang();
  const [me, setMe] = useState<Me | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const billing = useBilling();

  const loadDevices = () => get<{ sessions: Device[] }>("/v1/auth/sessions").then((r) => setDevices(r.sessions)).catch(() => undefined);
  useEffect(() => {
    get<Me>("/v1/me").then(setMe).catch(() => undefined);
    void loadDevices();
  }, []);

  const changeLang = async (lang: Lang) => {
    setLang(lang);
    await call("PATCH", "/v1/account", { locale: lang }).catch(() => undefined);
  };

  const signOut = async () => {
    await post("/v1/auth/logout").catch(() => undefined);
    setSession(null);
    go("/login");
  };

  return (
    <section className="stack">
      <h1>{t("account")}</h1>
      <div className="card">
        <p><strong>{session.user.name ?? session.user.email}</strong><br /><span className="muted">{session.user.email}</span></p>
        <label>{t("language")}
          <select value={getLang()} onChange={(e) => void changeLang(e.target.value as Lang)} data-testid="language">
            <option value="en">English</option>
            <option value="tl">Taglish</option>
          </select>
        </label>
        {me && (
          <p className="muted" data-testid="usage">{t("usage")}: {me.usage.input_minutes.toFixed(1)} / {me.client.monthly_minutes.toFixed(0)} min · {me.usage.jobs}</p>
        )}
        <div className="row wrap">
          <button className="ghost" onClick={() => void signOut()}>{t("signOut")}</button>
          {session.user.is_admin && <a className="button ghost" href="#/admin" data-testid="admin-link">Admin</a>}
        </div>
      </div>

      {billing?.enabled ? <BillingCard /> : (
        <div className="card">
          <h2>{t("plan")}</h2>
          <p className="muted">{t("planSoon", { min: me ? me.client.monthly_minutes.toFixed(0) : "…" })}</p>
        </div>
      )}

      <Workspace session={session} refresh={refresh} setSession={setSession} />

      <div className="card">
        <h2>{t("devices")}</h2>
        <ul className="plain">
          {devices.map((d) => (
            <li key={d.id}>{(d.user_agent ?? "?").slice(0, 60)} · {new Date(d.last_seen_at * 1000).toLocaleDateString()}
              {d.current && <strong> ({t("thisDevice")})</strong>}</li>
          ))}
        </ul>
        {devices.length > 1 && <button className="ghost" onClick={() => void post("/v1/auth/sessions/end-others").then(loadDevices)}>{t("endOthers")}</button>}
      </div>

      {session.user.has_password && <ChangePassword onDone={() => setNote(t("saved"))} />}
      <TwoStep session={session} refresh={refresh} />
      {note && <p className="ok" role="status">{note}</p>}

      <div className="card">
        <a className="button ghost" href="/v1/account/export" download>{t("exportData")}</a>
        <DeleteAccount session={session} onError={setError} onDone={() => {
          setSession(null);
          go("/login");
        }} />
        {error && <p className="error" role="alert">{error}</p>}
      </div>
      <p className="links"><a href="/app/terms.html" target="_blank" rel="noreferrer">{t("terms")}</a><a href="/app/privacy.html" target="_blank" rel="noreferrer">{t("privacy")}</a></p>
    </section>
  );
}

function Workspace({ session }: SessionProps) {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const manager = session.organisation && ["owner", "admin"].includes(session.organisation.role);
  const load = () => get<{ members: Member[] }>("/v1/org/members").then((r) => setMembers(r.members)).catch(() => undefined);
  useEffect(() => {
    void load();
  }, []);
  const invite = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await post("/v1/org/invites", { email, role: "member" });
      setEmail("");
      setNote(t("inviteSent"));
    } catch (err) {
      setNote(msg(err));
    }
  };
  if (!session.organisation) return null;
  return (
    <div className="card">
      <h2>{t("organisation")}: {session.organisation.name}</h2>
      {session.organisations.length > 1 && (
        <select value={session.organisation.id} aria-label={t("organisation")}
          onChange={(e) => void post<Session>(`/v1/orgs/${e.target.value}/switch`).then(() => window.location.reload())}>
          {session.organisations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      )}
      <h3>{t("members")}</h3>
      <ul className="plain">{members.map((m) => <li key={m.user_id}>{m.name ?? m.email} · {m.role}</li>)}</ul>
      {manager && (
        <form onSubmit={invite} className="row">
          <input type="email" required placeholder={t("email")} value={email} onChange={(e) => setEmail(e.target.value)} className="grow" />
          <button className="small">{t("invite")}</button>
        </form>
      )}
      {note && <p className="muted" role="status">{note}</p>}
    </div>
  );
}

function ChangePassword({ onDone }: { onDone: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await post("/v1/auth/password/change", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setError("");
      onDone();
    } catch (err) {
      setError(msg(err));
    }
  };
  return (
    <details className="card">
      <summary>{t("changePassword")}</summary>
      <form onSubmit={submit}>
        <label>{t("currentPassword")}<input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
        <label>{t("newPassword")}<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button>{t("save")}</button>
      </form>
    </details>
  );
}

function TwoStep({ session, refresh }: Pick<SessionProps, "session" | "refresh">) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  if (codes.length) {
    return (
      <div className="card" data-testid="recovery-codes">
        <p>{t("mfaCodes")}</p>
        <pre>{codes.join("\n")}</pre>
        <button onClick={() => setCodes([])}>{t("close")}</button>
      </div>
    );
  }
  if (session.user.mfa_enabled) {
    return (
      <details className="card">
        <summary>{t("mfaOn")}</summary>
        <form onSubmit={(e) => {
          e.preventDefault();
          void post("/v1/auth/mfa/disable", { password, code }).then(refresh).catch((err) => setError(msg(err)));
        }}>
          {session.user.has_password && <label>{t("password")}<input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
          <label>{t("code")}<input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} /></label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="ghost danger">{t("mfaOff")}</button>
        </form>
      </details>
    );
  }
  return (
    <div className="card">
      {!setup ? (
        <button className="ghost" onClick={() => void post<{ secret: string; otpauth_uri: string }>("/v1/auth/mfa/setup").then(setSetup).catch((err) => setError(msg(err)))}>{t("mfaSetup")}</button>
      ) : (
        <form onSubmit={(e) => {
          e.preventDefault();
          void post<{ recovery_codes: string[] }>("/v1/auth/mfa/enable", { code })
            .then((r) => {
              setCodes(r.recovery_codes);
              void refresh();
            }).catch((err) => setError(msg(err)));
        }}>
          <p>{t("mfaScan")}</p>
          <p><code className="secret" data-testid="mfa-secret">{setup.secret.replace(/(.{4})/g, "$1 ").trim()}</code></p>
          <p><a href={setup.otpauth_uri}>otpauth://…</a></p>
          <label>{t("code")}<input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} /></label>
          <button>{t("verify")}</button>
        </form>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}

function DeleteAccount({ session, onDone, onError }: { session: Session; onDone: () => void; onError: (e: string) => void }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  if (!open) return <button className="ghost danger" onClick={() => setOpen(true)}>{t("deleteAccount")}</button>;
  return (
    <form className="danger-zone" onSubmit={(e) => {
      e.preventDefault();
      void post("/v1/account/delete", { password, code: code || undefined }).then(onDone).catch((err) => onError(msg(err)));
    }}>
      <p>{t("deleteAccountWarn")}</p>
      {session.user.has_password && <label>{t("confirmWithPassword")}<input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
      {session.user.mfa_enabled && <label>{t("code")}<input inputMode="numeric" required value={code} onChange={(e) => setCode(e.target.value)} /></label>}
      <button className="danger">{t("deleteAccount")}</button>
    </form>
  );
}

export function AcceptInvite({ token, setSession }: { token: string } & SessionProps) {
  const [error, setError] = useState("");
  const sent = useRef(false);
  const join = async () => {
    if (sent.current) return;
    sent.current = true;
    try {
      setSession(await post<Session>("/v1/invites/accept", { token }));
      go("/");
    } catch (err) {
      sent.current = false;
      setError(msg(err));
    }
  };
  return (
    <section className="card narrow">
      <h1>{t("joinTitle")}</h1>
      <button className="wide" onClick={() => void join()}>{t("join")}</button>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
