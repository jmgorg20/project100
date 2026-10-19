import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError, get, setCsrf, type Session } from "./api";
import { setLang, t, useLang } from "./i18n";
import { Account, AcceptInvite } from "./pages/Account";
import { Admin } from "./pages/Admin";
import { Forgot, Login, MfaStep, Reset, Signup, Verify } from "./pages/Auth";
import { History } from "./pages/History";
import { JobPage } from "./pages/Job";
import { NewVideo } from "./pages/NewVideo";

// Routes live after "#" (the links in emails are …/app/#/verify/<token> and so on).
export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("?")[0].split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(path: string) {
  window.location.hash = path.startsWith("#") ? path : `#/${path.replace(/^\//, "")}`;
}

export function query(name: string): string | null {
  const q = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(q).get(name);
}

export interface SessionProps {
  session: Session;
  refresh: () => Promise<Session | null>;
  setSession: (s: Session | null) => void;
}

const PUBLIC = new Set(["login", "signup", "verify", "forgot", "reset", "mfa"]);

export function App() {
  const route = useRoute();
  useLang();
  const [session, setSessionState] = useState<Session | null | undefined>(undefined);
  const [online, setOnline] = useState(navigator.onLine);

  const setSession = useCallback((s: Session | null) => {
    setCsrf(s?.csrf_token ?? "");
    if (s?.user.locale) setLang(s.user.locale);
    setSessionState(s);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const s = await get<Session>("/v1/auth/session");
      setSession(s);
      return s;
    } catch (err) {
      if ((err as ApiError).status === 401) setSession(null);
      else setSessionState((old) => (old === undefined ? null : old));   // offline: keep what we had
      return null;
    }
  }, [setSession]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  const page = route[0] ?? "";
  // someone just made staff: the admin pages re-read the session once
  const staleAdmin = page === "admin" && session && !session.user.is_admin;
  useEffect(() => {
    if (staleAdmin) void refresh();
  }, [staleAdmin, refresh]);
  let body: ReactNode;
  if (session === undefined) {
    body = <p className="muted center">{t("loading")}</p>;
  } else if (PUBLIC.has(page) || !session) {
    const done = (s: Session) => {
      setSession(s);
      go("/");
    };
    if (page === "signup") body = <Signup />;
    else if (page === "verify") body = <Verify token={route[1] ?? ""} onDone={done} />;
    else if (page === "forgot") body = <Forgot />;
    else if (page === "reset") body = <Reset token={route[1] ?? ""} />;
    else if (page === "mfa") body = <MfaStep ticket={route[1] ?? ""} onDone={done} />;
    else body = <Login onDone={done} />;
  } else {
    const props = { session, refresh, setSession };
    if (page === "jobs" && route[1]) body = <JobPage id={route[1]} {...props} />;
    else if (page === "jobs") body = <History {...props} />;
    else if (page === "account") body = <Account {...props} />;
    else if (page === "admin" && session.user.is_admin) body = <Admin />;
    else if (page === "invite") body = <AcceptInvite token={route[1] ?? ""} {...props} />;
    else body = <NewVideo {...props} />;
  }

  const signedIn = Boolean(session) && !PUBLIC.has(page);
  return (
    <div className={signedIn ? "app with-nav" : "app"}>
      <header className="top">
        <a className="brand" href="#/">{t("appName")}</a>
        {signedIn && session?.organisation && <span className="org" data-testid="org-name">{session.organisation.name}</span>}
        <InstallButton />
      </header>
      {!online && <div className="banner warn" role="status" data-testid="offline">{t("offline")}</div>}
      <UpdateBanner />
      <main>{body}</main>
      {signedIn && (
        <nav className="bottom" aria-label="Main">
          <a href="#/" className={page === "" ? "active" : ""}><span aria-hidden>＋</span>{t("navNew")}</a>
          <a href="#/jobs" className={page === "jobs" ? "active" : ""}><span aria-hidden>▤</span>{t("navHistory")}</a>
          <a href="#/account" className={page === "account" ? "active" : ""}><span aria-hidden>☺</span>{t("navAccount")}</a>
        </nav>
      )}
    </div>
  );
}

interface InstallPrompt extends Event {
  prompt: () => Promise<void>;
}

function InstallButton() {
  const [prompt, setPrompt] = useState<InstallPrompt | null>(null);
  useEffect(() => {
    const on = (e: Event) => {
      e.preventDefault();
      setPrompt(e as InstallPrompt);
    };
    window.addEventListener("beforeinstallprompt", on);
    return () => window.removeEventListener("beforeinstallprompt", on);
  }, []);
  if (!prompt) return null;
  return (
    <button className="small ghost" onClick={() => void prompt.prompt().then(() => setPrompt(null))}>{t("install")}</button>
  );
}

function UpdateBanner() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const on = () => setReady(true);
    window.addEventListener("autoedit-update", on);
    return () => window.removeEventListener("autoedit-update", on);
  }, []);
  if (!ready) return null;
  return (
    <div className="banner" role="status">
      {t("updateReady")} <button className="small" onClick={() => window.location.reload()}>{t("reload")}</button>
    </div>
  );
}
