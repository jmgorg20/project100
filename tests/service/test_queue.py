"""The durable job queue, on SQLite and on real Postgres."""

import threading

import pytest

from service import clients, jobqueue
from service.db import now


def client(db, settings, **limits):
    with db.tx() as t:
        return clients.create_client(t, settings, "Test client", **limits)


def worker(db, settings, queues=("cpu",), channel="stable"):
    with db.tx() as t:
        w = jobqueue.create_worker(t, settings, "pc", list(queues), channel)
        return jobqueue.authenticate_worker(t, settings, w["token"])


def job(db, settings, c, queue="cpu", **kw):
    with db.tx() as t:
        j, _ = jobqueue.enqueue(t, settings, c, "polish", {"preset": "meme"}, {"main": ["up_x"]}, queue=queue, **kw)
        return j


def test_migrations_are_applied_once(db):
    assert db.migrate() == []                       # already applied by the fixture
    assert db.ping()


def test_a_job_goes_to_exactly_one_worker_even_under_concurrency(db, settings):
    c = client(db, settings, concurrent_jobs=100)
    ids = {job(db, settings, c)["id"] for _ in range(12)}
    workers = [worker(db, settings) for _ in range(6)]
    got, lock = [], threading.Lock()

    def run(w):
        while True:
            j = jobqueue.claim(db, settings, w)
            if j is None:
                return
            with lock:
                got.append(j["id"])

    threads = [threading.Thread(target=run, args=(w,)) for w in workers]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    assert sorted(got) == sorted(ids)               # every job once, none twice


def test_order_queues_and_client_concurrency(db, settings):
    c = client(db, settings, concurrent_jobs=1)
    first = job(db, settings, c)
    job(db, settings, c)
    gpu_job = job(db, settings, client(db, settings), queue="gpu")
    w = worker(db, settings, ("cpu",))
    j = jobqueue.claim(db, settings, w)
    assert j["id"] == first["id"] and j["status"] == "running" and j["attempts"] == 1
    assert jobqueue.claim(db, settings, w) is None          # the client already has 1 running
    g = jobqueue.claim(db, settings, worker(db, settings, ("gpu",)))
    assert g["id"] == gpu_job["id"]


def test_channels_and_the_promoted_version(db, settings):
    beta_client = client(db, settings)
    with db.tx() as t:
        clients.update_client(t, beta_client["id"], {"channel": "beta"})
        beta_client = clients.get_client(t, beta_client["id"])
    b = job(db, settings, beta_client)
    s = job(db, settings, client(db, settings))
    stable_w, beta_w = worker(db, settings), worker(db, settings, channel="beta")
    with db.tx() as t:
        jobqueue.register_release(t, "1.1.0", tests_passed=True)
        jobqueue.register_release(t, "1.2.0", tests_passed=False)
        with pytest.raises(jobqueue.QueueError, match="did not pass"):
            jobqueue.promote(t, "1.2.0")
        jobqueue.promote(t, "1.1.0")
    assert jobqueue.claim(db, settings, stable_w, engine_version="1.2.0") is None   # not promoted
    assert jobqueue.claim(db, settings, stable_w, engine_version="1.1.0")["id"] == s["id"]
    assert jobqueue.claim(db, settings, beta_w, engine_version="1.2.0")["id"] == b["id"]   # beta: any version


def test_promote_and_one_command_rollback(db):
    with db.tx() as t:
        for v in ("1.0.0", "1.1.0"):
            jobqueue.register_release(t, v, tests_passed=True)
        jobqueue.promote(t, "1.0.0")
        jobqueue.promote(t, "1.1.0")
        assert jobqueue.get_setting(t, "stable_version") == "1.1.0"
        assert jobqueue.rollback(t) == "1.0.0"
        assert jobqueue.get_setting(t, "stable_version") == "1.0.0"
        with pytest.raises(jobqueue.QueueError, match="no earlier"):
            jobqueue.rollback(t)


def test_heartbeat_progress_and_cancel(db, settings):
    c = client(db, settings)
    j = job(db, settings, c)
    w = worker(db, settings)
    jobqueue.claim(db, settings, w)
    assert jobqueue.heartbeat(db, settings, w, j["id"], 0.4, "render", "Rendering") == {"cancel": False}
    with db.tx() as t:
        jobqueue.cancel(t, t.one("SELECT * FROM jobs WHERE id = ?", (j["id"],)))
    assert jobqueue.heartbeat(db, settings, w, j["id"], 0.5) == {"cancel": True}
    out = jobqueue.fail(db, w, j["id"], "Cancelled by the client.", retryable=True)
    assert out["status"] == "cancelled"                      # a cancelled job is never retried
    other = worker(db, settings)
    with pytest.raises(jobqueue.QueueError):
        jobqueue.heartbeat(db, settings, other, j["id"])     # not its job


def test_retry_with_backoff_then_fail(db, settings):
    c = client(db, settings)
    j = job(db, settings, c)
    w = worker(db, settings)
    for attempt in range(1, settings.max_attempts + 1):
        with db.tx() as t:
            t.run("UPDATE jobs SET not_before = 0 WHERE id = ?", (j["id"],))
        claimed = jobqueue.claim(db, settings, w)
        assert claimed["attempts"] == attempt
        out = jobqueue.fail(db, w, j["id"], "ffmpeg crashed")
        if attempt < settings.max_attempts:
            assert out["status"] == "queued" and out["not_before"] > now()
            assert jobqueue.claim(db, settings, w) is None   # waits before the next try
    assert out["status"] == "failed" and "ffmpeg crashed" in out["error"]


def test_a_worker_that_disappears_gives_its_job_back(db, settings):
    c = client(db, settings)
    j = job(db, settings, c)
    w = worker(db, settings)
    jobqueue.claim(db, settings, w)
    with db.tx() as t:
        t.run("UPDATE jobs SET lease_expires_at = ? WHERE id = ?", (now() - 1, j["id"]))
    assert jobqueue.reap(db) == [j["id"]]
    with db.tx() as t:
        back = t.one("SELECT * FROM jobs WHERE id = ?", (j["id"],))
        assert back["status"] == "queued" and back["worker_id"] is None and "stopped answering" in back["error"]
        events = [e["kind"] for e in t.all("SELECT kind FROM job_events WHERE job_id = ? ORDER BY seq", (j["id"],))]
    assert events == ["queued", "started", "retry"]
    with pytest.raises(jobqueue.QueueError):
        jobqueue.complete(db, w, j["id"], {"status": "ok"})  # the old worker can no longer finish it


def test_time_limit(db, settings):
    c = client(db, settings)
    j = job(db, settings, c)
    w = worker(db, settings)
    jobqueue.claim(db, settings, w)
    with db.tx() as t:
        t.run("UPDATE jobs SET started_at = ?, max_attempts = 1 WHERE id = ?", (now() - 10_000, j["id"]))
    jobqueue.reap(db)
    with db.tx() as t:
        back = t.one("SELECT * FROM jobs WHERE id = ?", (j["id"],))
    assert back["status"] == "failed" and "time limit" in back["error"]


def test_revoking_a_worker_returns_its_jobs(db, settings):
    c = client(db, settings)
    j = job(db, settings, c)
    w = worker(db, settings)
    jobqueue.claim(db, settings, w)
    with db.tx() as t:
        jobqueue.revoke_worker(t, w["id"])
        assert t.one("SELECT status FROM jobs WHERE id = ?", (j["id"],))["status"] == "queued"
        assert jobqueue.authenticate_worker(t, settings, "wk_" + w["token_prefix"] + "_x" * 10) is None


def test_complete_and_idempotency(db, settings):
    c = client(db, settings)
    with db.tx() as t:
        a, new_a = jobqueue.enqueue(t, settings, c, "polish", {}, {}, idempotency_key="abc")
        b, new_b = jobqueue.enqueue(t, settings, c, "polish", {}, {}, idempotency_key="abc")
    assert new_a and not new_b and a["id"] == b["id"]
    w = worker(db, settings)
    jobqueue.claim(db, settings, w)
    done = jobqueue.complete(db, w, a["id"], {"status": "warnings", "qc": {"failed": ["black_frames"]}})
    assert done["status"] == "succeeded" and done["progress"] == 1.0
    with db.tx() as t:
        with pytest.raises(jobqueue.QueueError, match="already"):
            jobqueue.cancel(t, t.one("SELECT * FROM jobs WHERE id = ?", (a["id"],)))


def test_flags_per_channel(db):
    with db.tx() as t:
        jobqueue.set_flag(t, "formats", stable=False, beta=True, description="video formats")
        jobqueue.set_flag(t, "graphics", stable=True, beta=True)
        assert jobqueue.flags_for(t, "stable") == ["graphics"]
        assert jobqueue.flags_for(t, "beta") == ["formats", "graphics"]
        jobqueue.set_flag(t, "formats", stable=True)
        assert jobqueue.flags_for(t, "stable") == ["formats", "graphics"]
