"""Fixtures for the service tests: every database test runs on SQLite and on real Postgres."""

import pytest

from service.db import Database
from service.settings import Settings
from tests.service.pgtest import TempPostgres


@pytest.fixture(scope="session")
def postgres():
    pg = TempPostgres()
    ok = pg.start()
    yield pg if ok else None
    pg.stop()


@pytest.fixture(params=["sqlite", "postgres"])
def db_url(request, tmp_path, postgres):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'service.sqlite3'}"
    if postgres is None:
        pytest.skip("no Postgres for the tests (see tests/service/pgtest.py)")
    return postgres.fresh_database()


@pytest.fixture
def settings(tmp_path, db_url):
    return Settings(env="test", database_url=db_url, data_dir=str(tmp_path / "data"), secret_key="k" * 40,
                    admin_token="a" * 40, background=False, allow_private_webhooks=True, log_json=False)


@pytest.fixture
def db(settings):
    d = Database(settings.database_url)
    d.migrate()
    yield d
    d.close()
