"""A throwaway Postgres for the service tests (so they run against real Postgres, not only SQLite).

Uses AUTOEDIT_TEST_PG_URL if set (an empty database you own), else starts a temporary cluster with
initdb/pg_ctl (as the `postgres` user when the tests run as root). Without either, the Postgres
variant of the tests is skipped and says why.
"""

import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _bin(name):
    found = shutil.which(name)
    if found:
        return found
    for base in sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True):
        if (base / name).exists():
            return str(base / name)
    return None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TempPostgres:
    def __init__(self):
        self.dir = None
        self.url = None
        self.reason = ""

    def start(self):
        if os.environ.get("AUTOEDIT_TEST_PG_URL"):
            self.url = os.environ["AUTOEDIT_TEST_PG_URL"]
            return True
        initdb, pg_ctl = _bin("initdb"), _bin("pg_ctl")
        if not initdb or not pg_ctl:
            self.reason = "no Postgres (initdb) on this machine; set AUTOEDIT_TEST_PG_URL to test against Postgres"
            return False
        as_postgres = []
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            if not shutil.which("runuser"):
                self.reason = "running as root without runuser"
                return False
            as_postgres = ["runuser", "-u", "postgres", "--"]
        self.dir = tempfile.mkdtemp(prefix="autoedit-pg-")
        if as_postgres:
            shutil.chown(self.dir, "postgres", "postgres")
        data = os.path.join(self.dir, "data")
        port = _free_port()
        try:
            subprocess.run(as_postgres + [initdb, "-D", data, "-U", "postgres", "-A", "trust", "--no-sync"],
                           check=True, capture_output=True, timeout=120)
            subprocess.run(as_postgres + [pg_ctl, "-D", data, "-l", os.path.join(self.dir, "log"), "-w", "-o",
                                          f"-p {port} -k {self.dir} -c listen_addresses=127.0.0.1 -c fsync=off",
                                          "start"], check=True, capture_output=True, timeout=120)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            self.reason = f"could not start a test Postgres: {getattr(exc, 'stderr', b'')!r}"[:300]
            return False
        self._pg_ctl, self._as, self._data = pg_ctl, as_postgres, data
        self.url = f"postgresql://postgres@127.0.0.1:{port}/postgres"
        for _ in range(50):
            try:
                import psycopg
                psycopg.connect(self.url, connect_timeout=2).close()
                return True
            except Exception:
                time.sleep(0.2)
        self.reason = "the test Postgres did not answer"
        return False

    APP_ROLE = "autoedit_test_app"

    def fresh_database(self):
        """A new empty database owned by an ordinary user (not a superuser, no BYPASSRLS), as in
        production, so the row-level security policies apply in the tests. Returns its URL (as that
        user). Falls back to the given user if it cannot make roles."""
        import psycopg
        name = f"t{time.time_ns()}"
        parts = urlsplit(self.url)
        with psycopg.connect(self.url, autocommit=True) as conn:
            try:
                if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (self.APP_ROLE,)).fetchone():
                    conn.execute(f"CREATE ROLE {self.APP_ROLE} LOGIN PASSWORD '{self.APP_ROLE}' NOSUPERUSER "
                                 "NOBYPASSRLS NOCREATEDB NOCREATEROLE")
                conn.execute(f'CREATE DATABASE "{name}" OWNER {self.APP_ROLE}')
            except psycopg.Error:
                conn.execute(f'CREATE DATABASE "{name}"')
                return urlunsplit(parts._replace(path="/" + name))
        host = parts.netloc.rsplit("@", 1)[-1]
        return urlunsplit(parts._replace(netloc=f"{self.APP_ROLE}:{self.APP_ROLE}@{host}", path="/" + name))

    def stop(self):
        if self.dir and getattr(self, "_pg_ctl", None):
            subprocess.run(self._as + [self._pg_ctl, "-D", self._data, "-m", "immediate", "stop"],
                           capture_output=True, timeout=60)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)
