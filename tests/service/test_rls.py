"""Row-level security on Postgres: under the `client_id = ?` filters of every query, the database
itself keeps tenants apart. These tests run queries WITHOUT the filter (as a buggy query would) and
check that a tenant still sees and changes only its own rows. The test database user is an
ordinary user (tests/service/pgtest.py), as in production."""

import dataclasses

import psycopg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from service import clients, jobqueue
from service.api import create_app
from service.db import SYSTEM, Database, tenant
from service.deps import require_client
from tests.service.helpers import admin, new_client


@pytest.fixture
def pg(db):
    if db.kind != "postgres":
        pytest.skip("row-level security is a Postgres feature (SQLite: one tenant filter per query, tested elsewhere)")
    return db


def two_tenants(db, settings):
    with db.tx() as t:
        a = clients.create_client(t, settings, "A")
        b = clients.create_client(t, settings, "B")
        for c in (a, b):
            jobqueue.enqueue(t, settings, c, "polish", {}, {"main": []})
            clients.record_usage(t, c["id"], kind="job", input_minutes=1)
    return a, b


def test_rls_is_enforced_for_the_service_user(pg):
    assert pg.rls_status() == "enforced"


def test_sqlite_has_no_rls(db):
    if db.kind == "sqlite":
        assert db.rls_status() == "none"


def test_a_tenant_sees_only_its_rows_even_without_a_filter(pg, settings):
    a, b = two_tenants(pg, settings)
    with tenant(a["id"]), pg.tx() as t:
        assert {r["client_id"] for r in t.all("SELECT client_id FROM jobs")} == {a["id"]}
        assert [r["id"] for r in t.all("SELECT id FROM clients")] == [a["id"]]
        assert t.value("SELECT COUNT(*) FROM usage") == 1
        assert t.value("SELECT COUNT(*) FROM job_events") == 1                  # through its job
        # it cannot change or delete another tenant's rows either
        assert t.run("UPDATE jobs SET priority = 1") == 1
        assert t.run("DELETE FROM usage WHERE client_id = ?", (b["id"],)) == 0
    with tenant(a["id"]), pytest.raises(psycopg.Error, match="row-level security"):
        with pg.tx() as t:                                                      # nor write rows for another tenant
            clients.record_usage(t, b["id"], kind="job", input_minutes=5)
    with pg.tx() as t:                                                          # the system (workers, janitor) sees all
        assert t.value("SELECT COUNT(*) FROM jobs") == 2
        assert t.value("SELECT COUNT(*) FROM usage") == 2


def test_a_connection_that_does_not_say_who_it_is_sees_nothing(pg, settings):
    two_tenants(pg, settings)
    with psycopg.connect(pg.url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0
        conn.execute("SELECT set_config('app.tenant', %s, false)", (SYSTEM,))
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2


def test_requests_run_as_their_tenant(settings, db):
    """Through the API: an endpoint with an unfiltered query (a bug) still sees only the caller's
    rows, for an API key and for a signed-in user."""
    if db.kind != "postgres":
        pytest.skip("Postgres only")
    app = create_app(dataclasses.replace(settings, password_cost=10, signup_mode="open"))

    @app.get("/test/unfiltered")
    def unfiltered(client=Depends(require_client)):
        with app.state.db.tx() as t:
            return {"clients": [r["id"] for r in t.all("SELECT id FROM clients")],
                    "jobs": t.value("SELECT COUNT(*) FROM jobs")}

    with TestClient(app) as http:
        a, ha = new_client(http, "A")
        b, _ = new_client(http, "B")
        with app.state.db.tx() as t:
            for c in (a, b):
                jobqueue.enqueue(t, settings, clients.get_client(t, c["id"]), "polish", {}, {"main": []})
        assert http.get("/test/unfiltered", headers=ha).json() == {"clients": [a["id"]], "jobs": 1}
        # a signed-in user, acting in their own organisation
        http.post("/v1/auth/signup", json={"email": "u@example.com", "password": "correct horse battery", "accept_terms": True})
        with app.state.db.tx() as t:
            body = t.value("SELECT body FROM email_outbox WHERE template = 'verify_email'")
        token = body.split("#/verify/")[1].split()[0]
        org = http.post("/v1/auth/verify", json={"token": token}).json()["organisation"]["id"]
        assert http.get("/test/unfiltered").json() == {"clients": [org], "jobs": 0}
        # the admin still sees every client (system)
        assert len(http.get("/v1/admin/clients", headers=admin(http)).json()["clients"]) == 3


def test_production_refuses_a_user_that_bypasses_rls(settings, db, postgres):
    if db.kind != "postgres":
        pytest.skip("Postgres only")
    superuser_url = postgres.url.rsplit("/", 1)[0] + "/" + db.url.rsplit("/", 1)[1]
    if Database(superuser_url).rls_status() != "bypassed":
        pytest.skip("the test server has no superuser to try with")
    with pytest.raises(RuntimeError, match="Row-level security"):
        create_app(dataclasses.replace(settings, database_url=superuser_url, require_rls=True))
