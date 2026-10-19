"""Command line for the service (through editor.py):

    python editor.py serve [--host 127.0.0.1 --port 8787]
    python editor.py worker --server https://api.example.com --token wk_... --public-key service.pub [--queues cpu,gpu]
    python editor.py service-admin <command> ...      (works on the database directly: SERVICE_* env)

service-admin commands:
    signing-key FILE                 make the Ed25519 key that signs jobs (and FILE.pub for workers)
    migrate                          apply database migrations
    client-create NAME [--minutes N --concurrent N --rate N --storage-mb N --gpu --beta --presets a,b]
    client-update ID key=value ...   e.g. status=suspended channel=beta monthly_minutes=600
    clients                          list clients with this month's usage
    key-create CLIENT_ID [--name N]  key-revoke KEY_ID   key-rotate KEY_ID [--grace-hours 24]
    worker-create NAME [--queues cpu,gpu] [--channel beta]   worker-revoke WORKER_ID   workers
    release-register VERSION --junit report.xml | --passed     promote VERSION     rollback
    flag NAME [--stable on|off] [--beta on|off]                flags
    users [--q TEXT]                 web-app users        user-staff EMAIL [--off]   user-disable EMAIL [--enable]
    invite-create [--uses 1 --days 30 --note TEXT]   invite-codes   invite-revoke ID
    signups invite|open|closed|status    the switch for new sign-ups (closed = paused)
    janitor                          delete expired files, return stuck jobs (for a scheduler)
    status                           queue depth, workers, stable version
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _settings():
    from .settings import Settings
    return Settings.from_env()


def _db(settings):
    from .db import open_database
    return open_database(settings)


def _print(data):
    print(json.dumps(data, indent=1, default=str, ensure_ascii=False))


def junit_passed(path):
    """True when a JUnit XML report (pytest --junitxml) has tests and no failures or errors."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    tests = sum(int(s.get("tests", 0)) for s in suites)
    bad = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    return tests > 0 and bad == 0, {"tests": tests, "failures_and_errors": bad}


def serve(argv):
    p = argparse.ArgumentParser(prog="editor.py serve", description="Run the service API.")
    p.add_argument("--host", default=os.environ.get("SERVICE_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("SERVICE_PORT", "8787")))
    p.add_argument("--workers", type=int, default=1, help="API processes (each runs the janitor too; safe)")
    a = p.parse_args(argv)
    import logging

    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = _settings()
    uvicorn.run("service.api:create_app", factory=True, host=a.host, port=a.port, workers=a.workers,
                proxy_headers=True, forwarded_allow_ips=",".join(settings.trusted_proxies), server_header=False,
                date_header=False, access_log=False, timeout_keep_alive=30, limit_concurrency=512)


def worker(argv):
    p = argparse.ArgumentParser(prog="editor.py worker", description="Pull and run jobs from the service.")
    p.add_argument("--server", default=os.environ.get("AUTOEDIT_SERVER"), help="https://api.example.com")
    p.add_argument("--token", default=None, help="the worker token (better: AUTOEDIT_WORKER_TOKEN in the environment)")
    p.add_argument("--public-key", default=os.environ.get("AUTOEDIT_SERVICE_PUBLIC_KEY"),
                   help="the service's public key file (from worker-create / signing-key)")
    p.add_argument("--queues", default=os.environ.get("AUTOEDIT_WORKER_QUEUES", "cpu"), help="cpu, gpu or cpu,gpu")
    p.add_argument("--work-dir", default=None, help="folder for job files (deleted after each job)")
    p.add_argument("--config", default=None, help="the engine's config.yaml for this worker")
    p.add_argument("--once", action="store_true", help="run at most one job and stop")
    p.add_argument("--allow-http", action="store_true", help="local tests only: allow http://")
    a = p.parse_args(argv)
    token = a.token or os.environ.get("AUTOEDIT_WORKER_TOKEN")
    if not a.server or not token or not a.public_key:
        p.error("--server, a token (AUTOEDIT_WORKER_TOKEN) and --public-key are required")
    from .worker import Agent, WorkerError
    try:
        agent = Agent(a.server, token, Path(a.public_key).read_text(), [q.strip() for q in a.queues.split(",") if q.strip()],
                      a.work_dir, a.config, allow_http=a.allow_http)
        if a.once:
            agent.run_once()
        else:
            agent.run_forever()
    except WorkerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


def admin(argv):
    p = argparse.ArgumentParser(prog="editor.py service-admin", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sk = sub.add_parser("signing-key")
    sk.add_argument("file")
    sub.add_parser("migrate")
    cc = sub.add_parser("client-create")
    cc.add_argument("name")
    cc.add_argument("--minutes", type=float)
    cc.add_argument("--concurrent", type=int)
    cc.add_argument("--rate", type=int)
    cc.add_argument("--storage-mb", type=int)
    cc.add_argument("--retention-days", type=float)
    cc.add_argument("--gpu", action="store_true")
    cc.add_argument("--beta", action="store_true")
    cc.add_argument("--presets", help="comma-separated preset ids (default: all)")
    cu = sub.add_parser("client-update")
    cu.add_argument("client_id")
    cu.add_argument("changes", nargs="+", help="key=value")
    sub.add_parser("clients")
    kc = sub.add_parser("key-create")
    kc.add_argument("client_id")
    kc.add_argument("--name")
    kr = sub.add_parser("key-revoke")
    kr.add_argument("key_id")
    kro = sub.add_parser("key-rotate")
    kro.add_argument("key_id")
    kro.add_argument("--grace-hours", type=float, default=24.0)
    wc = sub.add_parser("worker-create")
    wc.add_argument("name")
    wc.add_argument("--queues", default="cpu")
    wc.add_argument("--channel", default="stable", choices=["stable", "beta"])
    wr = sub.add_parser("worker-revoke")
    wr.add_argument("worker_id")
    sub.add_parser("workers")
    rr = sub.add_parser("release-register")
    rr.add_argument("version")
    g = rr.add_mutually_exclusive_group(required=True)
    g.add_argument("--junit", help="pytest --junitxml report: the release passes only with tests and no failures")
    g.add_argument("--passed", action="store_true", help="mark as passed without a report (not recommended)")
    pr = sub.add_parser("promote")
    pr.add_argument("version")
    sub.add_parser("rollback")
    fl = sub.add_parser("flag")
    fl.add_argument("name")
    fl.add_argument("--stable", choices=["on", "off"])
    fl.add_argument("--beta", choices=["on", "off"])
    fl.add_argument("--description")
    sub.add_parser("flags")
    us = sub.add_parser("users")
    us.add_argument("--q")
    ust = sub.add_parser("user-staff")
    ust.add_argument("email")
    ust.add_argument("--off", action="store_true")
    ud = sub.add_parser("user-disable")
    ud.add_argument("email")
    ud.add_argument("--enable", action="store_true")
    ic = sub.add_parser("invite-create")
    ic.add_argument("--uses", type=int, default=1)
    ic.add_argument("--days", type=float, default=30)
    ic.add_argument("--note")
    sub.add_parser("invite-codes")
    ir = sub.add_parser("invite-revoke")
    ir.add_argument("code_id")
    su = sub.add_parser("signups")
    su.add_argument("mode", choices=["invite", "open", "closed", "status"])
    sub.add_parser("janitor")
    sub.add_parser("status")
    a = p.parse_args(argv)

    if a.cmd == "signing-key":
        from . import security
        path = Path(a.file)
        if path.exists():
            print(f"ERROR: {path} exists; refusing to overwrite a signing key.", file=sys.stderr)
            return 1
        pem = security.new_signing_key()
        path.write_text(pem)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        Path(str(path) + ".pub").write_text(security.public_key_pem(security.load_signing_key(pem)))
        print(f"Saved {path} (keep it secret: SERVICE_SIGNING_KEY_FILE) and {path}.pub (give it to workers).")
        return 0

    from . import accounts, clients, janitor, jobqueue
    settings = _settings()
    db = _db(settings)
    actor = "admin-cli"
    try:
        if a.cmd == "migrate":
            print("Database is up to date.")
        elif a.cmd == "client-create":
            limits = {k: v for k, v in {"monthly_minutes": a.minutes, "concurrent_jobs": a.concurrent,
                                        "rate_per_minute": a.rate, "storage_mb": a.storage_mb,
                                        "retention_days": a.retention_days}.items() if v is not None}
            if a.gpu:
                limits["gpu_allowed"] = True
            if a.beta:
                limits["channel"] = "beta"
            if a.presets:
                limits["presets"] = [x.strip() for x in a.presets.split(",") if x.strip()]
            with db.tx() as t:
                c = clients.create_client(t, settings, a.name, **limits)
                key = clients.create_key(t, settings, c["id"], "first key")
                clients.audit(t, actor, "client.created", c["id"], {"name": a.name})
            _print({"client": clients.public(c), "api_key": key["key"]})
            print("The API key is shown only now. Give it to the client.", file=sys.stderr)
        elif a.cmd == "client-update":
            changes = {}
            for pair in a.changes:
                k, _, v = pair.partition("=")
                changes[k] = json.loads(v) if v[:1] in "[{" or v in ("true", "false", "null") else v
            with db.tx() as t:
                c = clients.update_client(t, a.client_id, changes)
                clients.audit(t, actor, "client.updated", a.client_id, changes)
            _print(clients.public(c))
        elif a.cmd == "clients":
            with db.tx() as t:
                _print([{**clients.public(c), "usage": clients.usage_this_month(t, c["id"])}
                        for c in t.all("SELECT * FROM clients ORDER BY created_at")])
        elif a.cmd == "key-create":
            with db.tx() as t:
                key = clients.create_key(t, settings, a.client_id, a.name)
                clients.audit(t, actor, "key.created", key["id"])
            _print(key)
        elif a.cmd == "key-revoke":
            with db.tx() as t:
                clients.revoke_key(t, a.key_id)
                clients.audit(t, actor, "key.revoked", a.key_id)
            print("Revoked.")
        elif a.cmd == "key-rotate":
            with db.tx() as t:
                new = clients.rotate_key(t, settings, a.key_id, a.grace_hours)
                clients.audit(t, actor, "key.rotated", a.key_id)
            _print(new)
        elif a.cmd == "worker-create":
            with db.tx() as t:
                w = jobqueue.create_worker(t, settings, a.name, [q.strip() for q in a.queues.split(",")], a.channel)
                clients.audit(t, actor, "worker.created", w["id"])
            _print(w)
            print("The worker token is shown only now. Put it in AUTOEDIT_WORKER_TOKEN on the worker.", file=sys.stderr)
        elif a.cmd == "worker-revoke":
            with db.tx() as t:
                jobqueue.revoke_worker(t, a.worker_id)
                clients.audit(t, actor, "worker.revoked", a.worker_id)
            print("Revoked; its running jobs went back to the queue.")
        elif a.cmd == "workers":
            with db.tx() as t:
                _print(t.all("SELECT id, name, queues, channel, status, engine_version, last_seen_at FROM workers"))
        elif a.cmd == "release-register":
            passed, report = (True, {"manual": True}) if a.passed else junit_passed(a.junit)
            with db.tx() as t:
                jobqueue.register_release(t, a.version, passed, report)
                clients.audit(t, actor, "release.registered", a.version, report)
            print(f"{a.version}: tests {'PASSED' if passed else 'FAILED'} {report}")
            return 0 if passed else 1
        elif a.cmd == "promote":
            with db.tx() as t:
                v = jobqueue.promote(t, a.version)
                clients.audit(t, actor, "release.promoted", v)
            print(f"Stable version is now {v}.")
        elif a.cmd == "rollback":
            with db.tx() as t:
                v = jobqueue.rollback(t)
                clients.audit(t, actor, "release.rollback", v)
            print(f"Rolled back: stable version is now {v}.")
        elif a.cmd == "flag":
            onoff = {"on": True, "off": False, None: None}
            with db.tx() as t:
                row = jobqueue.set_flag(t, a.name, onoff[a.stable], onoff[a.beta], a.description)
                clients.audit(t, actor, "flag.set", a.name, {"stable": a.stable, "beta": a.beta})
            _print(row)
        elif a.cmd == "flags":
            with db.tx() as t:
                _print(t.all("SELECT * FROM flags ORDER BY name"))
        elif a.cmd == "users":
            with db.tx() as t:
                sql = "SELECT id, email, name, status, is_admin, email_verified_at, mfa_enabled_at, created_at FROM users"
                rows = t.all(sql + " WHERE email LIKE ? ORDER BY created_at", (f"%{a.q.lower()}%",)) if a.q else \
                    t.all(sql + " ORDER BY created_at")
            _print(rows)
        elif a.cmd in ("user-staff", "user-disable"):
            _, canon = accounts.normalize_email(a.email, settings)
            with db.tx() as t:
                user = t.one("SELECT * FROM users WHERE email_canonical = ?", (canon,))
                if not user:
                    raise clients.ClientError(f"No user with the email {a.email}.")
                if a.cmd == "user-staff":
                    t.update("users", user["id"], {"is_admin": 0 if a.off else 1})
                    clients.audit(t, actor, "user.updated", user["id"], {"is_admin": not a.off})
                    note = "" if a.off or user["mfa_enabled_at"] else (
                        " They must turn on two-step sign-in (Account page) before the admin pages open.")
                    print(f"{user['email']} is {'no longer' if a.off else 'now'} staff.{note}")
                else:
                    t.update("users", user["id"], {"status": "active" if a.enable else "disabled"})
                    if not a.enable:
                        accounts.revoke_all_sessions(t, user["id"])
                    clients.audit(t, actor, "user.updated", user["id"], {"status": "active" if a.enable else "disabled"})
                    print(f"{user['email']} is {'enabled' if a.enable else 'disabled (signed out everywhere)'}.")
        elif a.cmd == "invite-create":
            with db.tx() as t:
                code = accounts.create_invite_code(t, settings, a.uses, a.days, a.note, actor)
                clients.audit(t, actor, "invite_code.created", code["id"], {"max_uses": a.uses})
            _print(code)
            print("The invite code is shown only now.", file=sys.stderr)
        elif a.cmd == "invite-codes":
            with db.tx() as t:
                _print(accounts.list_invite_codes(t))
        elif a.cmd == "invite-revoke":
            with db.tx() as t:
                accounts.revoke_invite_code(t, a.code_id)
                clients.audit(t, actor, "invite_code.revoked", a.code_id)
            print("Revoked.")
        elif a.cmd == "signups":
            with db.tx() as t:
                if a.mode != "status":
                    accounts.set_signup_mode(t, a.mode)
                    clients.audit(t, actor, "signups.mode", None, {"mode": a.mode})
                print(f"New sign-ups: {accounts.signup_mode(t, settings)}")
        elif a.cmd == "janitor":
            from .storage import LocalStorage
            _print(janitor.run_once(db, LocalStorage(settings.data_path / "files"), settings))
        elif a.cmd == "status":
            with db.tx() as t:
                _print({"queues": jobqueue.queue_stats(t), "stable_version": jobqueue.get_setting(t, "stable_version"),
                        "workers": t.all("SELECT name, status, channel, engine_version, last_seen_at FROM workers")})
    except (clients.ClientError, jobqueue.QueueError, accounts.AccountError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


COMMANDS = {"serve": serve, "worker": worker, "service-admin": admin}


def main(argv):
    return COMMANDS[argv[0]](argv[1:]) or 0
