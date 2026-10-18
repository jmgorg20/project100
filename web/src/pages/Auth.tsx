import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, get, post, type AuthConfig, type MfaNeeded, type Session } from "../api";
import { go, query } from "../App";
import { deviceId } from "../device";
import { getLang, t } from "../i18n";

const OAUTH_ERRORS: Record<string, [string, string]> = {
  invite_required: ["An invite code is needed: enter it, then use Google again.", "Kailangan ng invite code: ilagay ito, tapos Google ulit."],
  signups_paused: ["New sign-ups are paused for now.", "Naka-pause muna ang bagong sign-up."],
  email_not_verified: ["Your Google email is not verified.", "Hindi verified ang Google email mo."],
  account_disabled: ["This account is disabled.", "Naka-disable ang account na ito."],
};

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : t("tryAgain");
}

function useConfig() {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  useEffect(() => {
    get<AuthConfig>("/v1/auth/config").then(setConfig).catch(() => setConfig(null));
  }, []);
  return config;
}

function ErrorLine({ text }: { text: string }) {
  return text ? <p className="error" role="alert">{text}</p> : null;
}

/** Cloudflare Turnstile or hCaptcha, when the service asks for one. */
function Captcha({ config, onToken }: { config: AuthConfig | null; onToken: (token: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const provider = config?.captcha.provider;
  const siteKey = config?.captcha.site_key;
  useEffect(() => {
    if (!provider || !siteKey || !box.current) return;
    const src = provider === "turnstile" ? "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
      : "https://js.hcaptcha.com/1/api.js?render=explicit";
    const render = () => {
      const w = window as unknown as Record<string, { render: (el: HTMLElement, o: object) => void } | undefined>;
      const api = w[provider === "turnstile" ? "turnstile" : "hcaptcha"];
      if (api && box.current && !box.current.childElementCount) api.render(box.current, { sitekey: siteKey, callback: onToken });
    };
    let script = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`);
    if (!script) {
      script = document.createElement("script");
      script.src = src;
      script.async = true;
      document.head.appendChild(script);
    }
    script.addEventListener("load", render);
    render();
    return () => script?.removeEventListener("load", render);
  }, [provider, siteKey, onToken]);
  return provider ? <div ref={box} className="captcha" /> : null;
}

function GoogleButton({ config, invite }: { config: AuthConfig | null; invite?: string }) {
  if (!config?.providers.includes("google")) return null;
  const q = new URLSearchParams({ device_id: deviceId() });
  if (invite) q.set("invite_code", invite);
  const href = `/v1/auth/oauth/google/start?${q}`;
  return <a className="button ghost wide" href={href}>{t("withGoogle")}</a>;
}

export function Login({ onDone }: { onDone: (s: Session) => void }) {
  const config = useConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [captcha, setCaptcha] = useState("");
  const [error, setError] = useState(() => {
    const code = query("error");
    return code ? (OAUTH_ERRORS[code]?.[getLang() === "tl" ? 1 : 0] ?? t("tryAgain")) : "";
  });
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await post<Session | MfaNeeded>("/v1/auth/login", { email, password, captcha: captcha || undefined });
      if ("mfa_required" in r) go(`/mfa/${r.ticket}`);
      else onDone(r);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card narrow">
      <h1>{t("signIn")}</h1>
      <p className="muted">{t("tagline")}</p>
      <form onSubmit={submit}>
        <label>{t("email")}<input type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>{t("password")}<input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <Captcha config={config} onToken={setCaptcha} />
        <ErrorLine text={error} />
        <button className="wide" disabled={busy}>{t("signIn")}</button>
      </form>
      <GoogleButton config={config} />
      <p className="links"><a href="#/forgot">{t("forgot")}</a><a href="#/signup">{t("noAccount")}</a></p>
    </section>
  );
}

export function Signup() {
  const config = useConfig();
  const [form, setForm] = useState({ email: "", password: "", name: "", invite_code: query("code") ?? "", website: "" });
  const [agree, setAgree] = useState(false);
  const [captcha, setCaptcha] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/v1/auth/signup", { ...form, captcha: captcha || undefined, locale: getLang(), device_id: deviceId() || undefined });
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  if (sent) return <CheckEmail email={form.email} />;
  if (config?.signup_mode === "closed") {
    return <section className="card narrow"><h1>{t("signUp")}</h1><p>{t("signupsPaused")}</p><p className="links"><a href="#/login">{t("haveAccount")}</a></p></section>;
  }
  return (
    <section className="card narrow">
      <h1>{t("signUp")}</h1>
      {config?.signup_mode === "invite" && <p className="muted">{t("inviteOnly")}</p>}
      <form onSubmit={submit}>
        {config?.signup_mode !== "open" && (
          <label>{t("inviteCode")}<input required autoCapitalize="characters" autoComplete="off" value={form.invite_code} onChange={set("invite_code")} placeholder="ABCD-EFGH-JKLM-NPQR" /></label>
        )}
        <label>{t("email")}<input type="email" autoComplete="email" inputMode="email" required value={form.email} onChange={set("email")} /></label>
        <label>{t("password")}<input type="password" autoComplete="new-password" minLength={config?.password_min_length ?? 10} required value={form.password} onChange={set("password")} />
          <small className="muted">{t("passwordHint")}</small></label>
        <label>{t("name")}<input autoComplete="name" value={form.name} onChange={set("name")} maxLength={80} /></label>
        {/* People never see or fill this; bots do. */}
        <input className="hp" tabIndex={-1} autoComplete="off" aria-hidden value={form.website} onChange={set("website")} name="website" />
        <label className="check"><input type="checkbox" required checked={agree} onChange={(e) => setAgree(e.target.checked)} />
          <span>{t("agree")} <a href="/app/terms.html" target="_blank" rel="noreferrer">{t("terms")}</a> · <a href="/app/privacy.html" target="_blank" rel="noreferrer">{t("privacy")}</a></span></label>
        <Captcha config={config} onToken={setCaptcha} />
        <ErrorLine text={error} />
        <button className="wide" disabled={busy || !agree}>{t("signUp")}</button>
      </form>
      <GoogleButton config={config} invite={form.invite_code} />
      <p className="links"><a href="#/login">{t("haveAccount")}</a></p>
    </section>
  );
}

function CheckEmail({ email }: { email: string }) {
  const [again, setAgain] = useState(false);
  return (
    <section className="card narrow" data-testid="check-email">
      <h1>{t("checkEmail")}</h1>
      <p className="muted">{t("checkEmailSpam")}</p>
      <button className="ghost" disabled={again} onClick={() => void post("/v1/auth/resend", { email }).finally(() => setAgain(true))}>{t("resend")}</button>
    </section>
  );
}

export function Verify({ token, onDone }: { token: string; onDone: (s: Session) => void }) {
  const [error, setError] = useState("");
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;                   // the link works once: never send it twice
    started.current = true;
    post<Session | MfaNeeded>("/v1/auth/verify", { token, device_id: deviceId() || undefined })
      .then((r) => ("mfa_required" in r ? go(`/mfa/${r.ticket}`) : onDone(r)))
      .catch((err) => setError(errorText(err)));
  }, [token, onDone]);
  return (
    <section className="card narrow">
      <h1>{t("confirming")}</h1>
      <ErrorLine text={error} />
      {error && <p className="links"><a href="#/login">{t("signIn")}</a></p>}
    </section>
  );
}

export function Forgot() {
  const config = useConfig();
  const [email, setEmail] = useState("");
  const [captcha, setCaptcha] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await post("/v1/auth/password/forgot", { email, captcha: captcha || undefined });
      setSent(true);
    } catch (err) {
      setError(errorText(err));
    }
  };
  if (sent) return <section className="card narrow"><h1>{t("checkEmail")}</h1><p className="muted">{t("checkEmailSpam")}</p></section>;
  return (
    <section className="card narrow">
      <h1>{t("forgot")}</h1>
      <form onSubmit={submit}>
        <label>{t("email")}<input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <Captcha config={config} onToken={setCaptcha} />
        <ErrorLine text={error} />
        <button className="wide">{t("sendResetLink")}</button>
      </form>
      <p className="links"><a href="#/login">{t("back")}</a></p>
    </section>
  );
}

export function Reset({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await post("/v1/auth/password/reset", { token, password });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    }
  };
  if (done) return <section className="card narrow"><p>{t("passwordSaved")}</p><a className="button wide" href="#/login">{t("signIn")}</a></section>;
  return (
    <section className="card narrow">
      <h1>{t("newPassword")}</h1>
      <form onSubmit={submit}>
        <label>{t("newPassword")}<input type="password" autoComplete="new-password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} />
          <small className="muted">{t("passwordHint")}</small></label>
        <ErrorLine text={error} />
        <button className="wide">{t("setPassword")}</button>
      </form>
    </section>
  );
}

export function MfaStep({ ticket, onDone }: { ticket: string; onDone: (s: Session) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      onDone(await post<Session>("/v1/auth/mfa", { ticket, code }));
    } catch (err) {
      setError(errorText(err));
      if ((err as ApiError).code === "invalid_token") setTimeout(() => go("/login"), 1500);
    }
  };
  return (
    <section className="card narrow">
      <h1>{t("twoStep")}</h1>
      <p className="muted">{t("enterCode")}</p>
      <form onSubmit={submit}>
        <label>{t("code")}<input inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} /></label>
        <ErrorLine text={error} />
        <button className="wide">{t("verify")}</button>
      </form>
    </section>
  );
}
