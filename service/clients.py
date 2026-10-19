"""Clients (the partner project, the SaaS website, future projects): each has its own API keys,
presets, quotas, rate limit, webhooks, channel (stable / beta) and usage report."""

import time

from . import security
from .db import dumps, loads, now


class ClientError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


CHANNELS = ("stable", "beta")
EDITABLE = {"name", "status", "channel", "rate_per_minute", "concurrent_jobs", "monthly_minutes", "storage_mb",
            "gpu_allowed", "retention_days", "delete_after_download_hours", "presets", "default_preset", "notes"}


def month_of(ts=None):
    return time.strftime("%Y-%m", time.gmtime(ts if ts is not None else now()))


def audit(t, actor, action, target=None, details=None, ip=None):
    t.insert("audit_log", {"id": security.new_id("au_"), "at": now(), "actor": actor, "action": action,
                           "target": target, "details": dumps(details), "ip": ip})


def public(client):
    """A client as the API shows it."""
    out = dict(client)
    out["presets"] = loads(client.get("presets"))
    out["gpu_allowed"] = bool(client.get("gpu_allowed"))
    return out


def create_client(t, settings, name, **limits):
    name = str(name or "").strip()
    if not name or len(name) > 100:
        raise ClientError("A client needs a name (up to 100 characters).")
    cid = security.new_id("cl_")
    row = {"id": cid, "name": name, "status": "active", "channel": "stable",
           "rate_per_minute": settings.rate_per_minute, "concurrent_jobs": settings.concurrent_jobs,
           "monthly_minutes": settings.monthly_minutes, "storage_mb": settings.storage_mb, "gpu_allowed": 0,
           "retention_days": settings.retention_days,
           "delete_after_download_hours": settings.delete_after_download_hours,
           "presets": None, "default_preset": None, "notes": None, "created_at": now(), "updated_at": now()}
    t.insert("clients", row)
    if limits:
        update_client(t, cid, limits)
    return get_client(t, cid)


def get_client(t, client_id):
    return t.one("SELECT * FROM clients WHERE id = ?", (client_id,))


def update_client(t, client_id, changes):
    bad = set(changes) - EDITABLE
    if bad:
        raise ClientError(f"Unknown setting(s): {', '.join(sorted(bad))}")
    values = {}
    for k, v in changes.items():
        if k == "status" and v not in ("active", "suspended"):
            raise ClientError("status must be active or suspended")
        if k == "channel" and v not in CHANNELS:
            raise ClientError("channel must be stable or beta")
        if k in ("rate_per_minute", "concurrent_jobs", "storage_mb"):
            v = int(v)
            if v < 0 or v > 1_000_000:
                raise ClientError(f"{k} is out of range")
        if k in ("monthly_minutes", "retention_days", "delete_after_download_hours"):
            v = float(v)
            if v < 0 or v > 100_000:
                raise ClientError(f"{k} is out of range")
        if k == "retention_days" and v > 30:
            raise ClientError("retention_days can be at most 30 (cloud storage is temporary)")
        if k == "gpu_allowed":
            v = 1 if v else 0
        if k == "presets":
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) for x in v)):
                raise ClientError("presets must be a list of preset ids, or null for all")
            v = dumps(v)
        values[k] = v
    values["updated_at"] = now()
    if not t.update("clients", client_id, values):
        raise ClientError("No such client.", 404)
    return get_client(t, client_id)


# ---------------------------------------------------------------- API keys

def create_key(t, settings, client_id, name=None, expires_days=None):
    if not get_client(t, client_id):
        raise ClientError("No such client.", 404)
    full, prefix, digest = security.make_key("ak", settings.secret_key)
    kid = security.new_id("key_")
    t.insert("api_keys", {"id": kid, "client_id": client_id, "prefix": prefix, "key_hash": digest,
                          "name": (name or "")[:100] or None, "created_at": now(), "last_used_at": None,
                          "expires_at": now() + float(expires_days) * 86400 if expires_days else None,
                          "revoked_at": None})
    return {"id": kid, "key": full, "prefix": prefix, "client_id": client_id}


def list_keys(t, client_id):
    return t.all("SELECT id, prefix, name, created_at, last_used_at, expires_at, revoked_at FROM api_keys "
                 "WHERE client_id = ? ORDER BY created_at", (client_id,))


def revoke_key(t, key_id, client_id=None):
    sql = "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL"
    params = [now(), key_id]
    if client_id:
        sql += " AND client_id = ?"
        params.append(client_id)
    if not t.run(sql, params):
        raise ClientError("No such active key.", 404)


def rotate_key(t, settings, key_id, grace_hours=24.0):
    """A new key for the same client; the old one keeps working for `grace_hours` (time to switch)."""
    old = t.one("SELECT * FROM api_keys WHERE id = ? AND revoked_at IS NULL", (key_id,))
    if not old:
        raise ClientError("No such active key.", 404)
    new = create_key(t, settings, old["client_id"], old["name"])
    until = now() + max(0.0, float(grace_hours)) * 3600
    t.run("UPDATE api_keys SET expires_at = ? WHERE id = ? AND (expires_at IS NULL OR expires_at > ?)",
          (until, key_id, until))
    return {**new, "old_key_expires_at": until}


def authenticate(t, settings, full_key):
    """The client for an API key, or None (unknown, revoked or expired key, or a suspended client)."""
    parsed = security.parse_key(full_key)
    if parsed is None or parsed[0] != "ak":
        return None
    row = t.one("SELECT k.id AS key_id, k.key_hash, k.expires_at, k.revoked_at, k.last_used_at, c.* "
                "FROM api_keys k JOIN clients c ON c.id = k.client_id WHERE k.prefix = ?", (parsed[1],))
    if not row or not security.key_matches(full_key, row["key_hash"], settings.secret_key):
        return None
    if row["revoked_at"] or (row["expires_at"] and row["expires_at"] < now()):
        return None
    if row["status"] != "active":
        return None
    if not row["last_used_at"] or now() - row["last_used_at"] > 60:
        t.run("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now(), row["key_id"]))
    for k in ("key_hash", "expires_at", "revoked_at", "last_used_at"):
        row.pop(k, None)
    return row


# ---------------------------------------------------------------- quotas and usage

def usage_this_month(t, client_id, month=None):
    month = month or month_of()
    row = t.one("SELECT COALESCE(SUM(input_minutes), 0) AS input_minutes, COALESCE(SUM(output_minutes), 0) AS "
                "output_minutes, COALESCE(SUM(cpu_seconds), 0) AS cpu_seconds, COALESCE(SUM(gpu_seconds), 0) AS "
                "gpu_seconds, COALESCE(SUM(egress_bytes), 0) AS egress_bytes, COALESCE(SUM(transcription_usd), 0) "
                "AS transcription_usd, COALESCE(SUM(ai_usd), 0) AS ai_usd, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
                "COALESCE(SUM(CASE WHEN kind = 'job' THEN 1 ELSE 0 END), 0) AS jobs "
                "FROM usage WHERE client_id = ? AND month = ?", (client_id, month))
    return {k: (float(v) if k not in ("jobs", "egress_bytes") else int(v)) for k, v in row.items()}


def reserved_minutes(t, client_id):
    """Minutes of jobs that are queued or running (counted before they finish)."""
    return float(t.value("SELECT COALESCE(SUM(input_minutes), 0) FROM jobs WHERE client_id = ? AND "
                         "status IN ('queued', 'running')", (client_id,), 0) or 0)


def stored_bytes(t, client_id):
    up = t.value("SELECT COALESCE(SUM(size_received), 0) FROM uploads WHERE client_id = ? AND status IN "
                 "('uploading', 'ready')", (client_id,), 0)
    out = t.value("SELECT COALESCE(SUM(size), 0) FROM outputs WHERE client_id = ? AND deleted_at IS NULL",
                  (client_id,), 0)
    return int(up or 0) + int(out or 0)


def check_job_quota(t, client, input_minutes, gpu):
    if gpu and not client["gpu_allowed"]:
        raise ClientError("AI generation (GPU) is not included for this client.", 403)
    used = usage_this_month(t, client["id"])["input_minutes"] + reserved_minutes(t, client["id"])
    if used + input_minutes > float(client["monthly_minutes"]) + 1e-9:
        left = max(0.0, float(client["monthly_minutes"]) - used)
        raise ClientError(f"Monthly minutes used up: {left:.1f} of {client['monthly_minutes']:.0f} min left this "
                          f"month, this job needs {input_minutes:.1f}.", 402)


def check_storage_quota(t, client, extra_bytes):
    if stored_bytes(t, client["id"]) + extra_bytes > int(client["storage_mb"]) * 1024 * 1024:
        raise ClientError("Storage limit reached: delete old files or wait for them to expire.", 413)


def record_usage(t, client_id, job_id=None, kind="job", **amounts):
    row = {"id": security.new_id("us_"), "client_id": client_id, "job_id": job_id, "month": month_of(),
           "kind": kind, "created_at": now()}
    for k in ("input_minutes", "output_minutes", "cpu_seconds", "gpu_seconds", "wall_seconds",
              "transcription_usd", "ai_usd", "cost_usd"):
        row[k] = float(amounts.get(k) or 0)
    for k in ("storage_bytes", "egress_bytes"):
        row[k] = int(amounts.get(k) or 0)
    t.insert("usage", row)
    return row


def estimate_cost(settings, cpu_seconds=0, gpu_seconds=0, storage_bytes=0, retention_days=0, egress_bytes=0,
                  transcription_usd=0, ai_usd=0):
    gb = 1024 ** 3
    return round(cpu_seconds * settings.cost_cpu_second + gpu_seconds * settings.cost_gpu_second
                 + storage_bytes / gb * settings.cost_gb_month * (retention_days / 30.0)
                 + egress_bytes / gb * settings.cost_gb_egress + transcription_usd + ai_usd, 6)
