"""Backups and the restore test (deploy/backup.sh, deploy/restore.sh) against a real Postgres: a dump
made as the admin has every tenant's rows, a restore gives the tables back to the service's user with
row-level security still on, and the service works on the restored database."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from service import clients
from service.db import Database
from service.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("pg_dump") or not shutil.which("sh"),
                                reason="needs sh and the Postgres client programs (pg_dump, pg_restore, psql)")


def admin_url(pg, app_url):
    """The same database, as the test cluster's admin (superuser)."""
    return urlunsplit(urlsplit(pg.url)._replace(path=urlsplit(app_url).path))


def run(script, *args, **env):
    r = subprocess.run(["sh", str(ROOT / "deploy" / script), *args], capture_output=True, text=True, timeout=300,
                       env={**os.environ, **env})
    return r.returncode, r.stdout + r.stderr


@pytest.fixture
def pg(postgres):
    if postgres is None:
        pytest.skip("no Postgres for the tests")
    return postgres


def test_backup_and_restore(pg, tmp_path):
    app_url = pg.fresh_database()
    if urlsplit(app_url).username != pg.APP_ROLE:
        pytest.skip("the test Postgres cannot make an ordinary user")
    s = Settings(env="test", database_url=app_url, data_dir=str(tmp_path / "d"), secret_key="k" * 40,
                 admin_token="a" * 40, password_cost=10)
    db = Database(app_url)
    db.migrate()
    with db.tx() as t:
        a = clients.create_client(t, s, "Tenant A", kind="organization")
        clients.create_client(t, s, "Tenant B")
        clients.audit(t, "test", "backup.test", a["id"])
    db.close()

    # as the service's own user the dump would be empty (row-level security): refused
    code, out = run("backup.sh", str(tmp_path / "bad"), BACKUP_DATABASE_URL=app_url)
    assert code != 0, out

    code, out = run("backup.sh", str(tmp_path / "backups"), BACKUP_DATABASE_URL=admin_url(pg, app_url))
    assert code == 0, out
    [dump] = list((tmp_path / "backups").glob("autoedit-*.dump"))
    assert oct(dump.stat().st_mode & 0o777) == "0o600"                  # only the owner can read it

    code, out = run("restore.sh", "--check", str(dump), RESTORE_DATABASE_URL=pg.url, APP_DB_USER=pg.APP_ROLE)
    assert code == 0, out
    assert "restore: clients 2" in out and "restore: OK" in out

    # a real restore into a new, empty database; then the service uses it as its own user
    target = pg.fresh_database()
    code, out = run("restore.sh", str(dump), RESTORE_DATABASE_URL=admin_url(pg, target), APP_DB_USER=pg.APP_ROLE)
    assert code == 0, out
    restored = Database(target)
    assert restored.rls_status() == "enforced" and restored.migrate() == []
    with restored.tx() as t:
        assert {c["name"] for c in t.all("SELECT name FROM clients")} == {"Tenant A", "Tenant B"}
        assert t.value("SELECT COUNT(*) FROM audit_log WHERE action = 'backup.test'") == 1
        clients.create_client(t, s, "After restore")                    # writable as the service
    restored.close()
    code, out = run("restore.sh", str(dump), RESTORE_DATABASE_URL=admin_url(pg, target), APP_DB_USER=pg.APP_ROLE)
    assert code != 0 and "not empty" in out                            # never over an existing database
