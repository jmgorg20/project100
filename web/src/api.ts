// The service API, from the same site (the session cookie is HttpOnly: the app never sees it).
// Every request that changes something sends the session's CSRF token.

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter = 0) {
    super(message);
  }
}

let csrfToken = "";
export function setCsrf(token: string) {
  csrfToken = token;
}

const SAFE = new Set(["GET", "HEAD"]);

export async function call<T = unknown>(method: string, path: string, body?: unknown, init: RequestInit = {}): Promise<T> {
  const { headers: extra, ...rest } = init;
  const headers: Record<string, string> = { Accept: "application/json", ...(extra as Record<string, string> | undefined) };
  if (!SAFE.has(method)) headers["X-CSRF-Token"] = csrfToken;
  if (body !== undefined && !(body instanceof Blob)) headers["Content-Type"] = "application/json";
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : body instanceof Blob ? body : JSON.stringify(body),
      ...rest,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "offline", "No connection. Check your internet and try again.");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const e = (data as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(response.status, e?.code ?? "error", e?.message ?? `Something went wrong (${response.status}).`,
      Number(response.headers.get("Retry-After") ?? 0));
  }
  return data as T;
}

export const get = <T>(path: string) => call<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => call<T>("POST", path, body ?? {});

// ---------------------------------------------------------------- shapes

export interface User {
  id: string;
  email: string;
  name: string | null;
  locale: "en" | "tl" | null;
  email_verified: boolean;
  mfa_enabled: boolean;
  has_password: boolean;
  is_admin: boolean;
}
export interface OrgRef {
  id: string;
  name: string;
  role: "owner" | "admin" | "member";
  status?: string;
}
export interface Session {
  user: User;
  csrf_token: string;
  organisation: OrgRef | null;
  organisations: OrgRef[];
  mfa_verified: boolean;
}
export interface MfaNeeded {
  mfa_required: true;
  ticket: string;
}
export interface AuthConfig {
  signup_mode: "invite" | "open" | "closed";
  providers: string[];
  captcha: { provider: string | null; site_key: string | null };
  password_min_length: number;
}
export interface Preset {
  id: string;
  name: string;
  tl: string;
  about: string;
  about_tl: string;
  format: string | null;
  own?: boolean;
}
export interface FormatInfo {
  id: string;
  name: string;
  tl: string;
  about: string;
  about_tl: string;
  inputs: { role: string; kinds: string[]; required: boolean; label: string; tl: string }[];
}
export interface Catalog {
  presets: Preset[];
  formats: FormatInfo[];
}
export interface UploadView {
  id: string;
  filename: string;
  kind: string;
  size: number;
  received: number;
  status: "uploading" | "ready" | "rejected" | "deleted";
  error: string | null;
  duration: number | null;
  chunk_size: number;
  expires_in_seconds: number;
}
export interface OutputView {
  id: string;
  name: string;
  size: number;
  content_type: string;
  url: string;
  preview_url: string;
  url_expires_at: number;
  expires_in_seconds: number;
}
export interface JobView {
  id: string;
  kind: "polish" | "render";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  progress: number | null;
  stage: string | null;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  input_minutes: number;
  project_id: string | null;
  params: { preset?: string; format?: string; instruction?: string; export?: Record<string, unknown>; project?: unknown };
  inputs: Record<string, string[]>;
  result: {
    status?: "ok" | "warnings" | "failed";
    qc?: { passed?: boolean; failed?: string[]; checks?: { id: string; ok?: boolean; message?: string }[] };
    opinions?: Record<string, unknown>;
  } | null;
  outputs: OutputView[];
}
export interface Me {
  client: { name: string; monthly_minutes: number; storage_mb: number; retention_days: number };
  usage: { input_minutes: number; jobs: number };
  stored_bytes: number;
  role: string | null;
}
export interface Project {
  id: string;
  name: string;
  jobs: number | null;
}

export interface PlanInfo {
  id: string;
  name: string;
  name_tl: string | null;
  description: string | null;
  description_tl: string | null;
  price_cents: number;
  currency: string;
  billing_interval: "month" | "year";
  monthly_minutes: number;
  storage_mb: number;
}
export interface Billing {
  enabled: boolean;
  mode: "off" | "trial" | "plan" | "locked";
  reason: string | null;
  status: string | null;
  plan: PlanInfo | null;
  trial_days_left: number | null;
  current_period_end: number | null;
  grace_until: number | null;
  cancel_at_period_end: boolean;
  usage: { minutes: number; minutes_limit: number; jobs: number; stored_bytes: number; storage_mb: number };
  plans: PlanInfo[];
  payments: { amount_cents: number; currency: string; status: string; occurred_at: number }[];
  can_manage: boolean;
  has_portal: boolean;
  online_payment: boolean;
}
