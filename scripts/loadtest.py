"""A small load test for the service: many parallel users for a while, then the latency (p50 / p95 /
p99), requests per second and errors per kind of request.

    python scripts/loadtest.py --url http://127.0.0.1:8000 --scenario read --key ak_... --users 20 --seconds 60
    python scripts/loadtest.py --url https://staging.example.com --scenario upload --key ak_... --i-own-this

Scenarios:
    health   /healthz and /readyz (no key)
    read     /v1/me, /v1/jobs, /v1/usage with an API key (a test client's)
    upload   each user uploads a small file in pieces and deletes it (needs a key; tests storage and
             the database under writes, not the video workers)

Run it against your own staging server, never production at busy hours and never anyone else's
server: it refuses an address that is not this computer unless you add --i-own-this. Limits per
address (SERVICE_*_PER_MINUTE) will answer 429 when they work: a test client with high limits, or
running from several addresses, measures the service instead of the limits.
"""

import argparse
import json
import os
import statistics
import sys
import threading
import time
from urllib.parse import urlsplit


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}

    def add(self, name, seconds, status):
        with self.lock:
            r = self.rows.setdefault(name, {"times": [], "codes": {}})
            r["times"].append(seconds)
            r["codes"][status] = r["codes"].get(status, 0) + 1

    def summary(self, elapsed):
        out = {}
        for name, r in sorted(self.rows.items()):
            n = len(r["times"])
            errors = sum(c for code, c in r["codes"].items() if not (isinstance(code, int) and code < 400))
            out[name] = {"requests": n, "per_second": round(n / elapsed, 2) if elapsed else None,
                         "p50_ms": round(percentile(r["times"], 50) * 1000, 1),
                         "p95_ms": round(percentile(r["times"], 95) * 1000, 1),
                         "p99_ms": round(percentile(r["times"], 99) * 1000, 1),
                         "mean_ms": round(statistics.fmean(r["times"]) * 1000, 1),
                         "errors": errors, "error_rate": round(errors / n, 4) if n else 0,
                         "codes": {str(k): v for k, v in sorted(r["codes"].items(), key=lambda kv: str(kv[0]))}}
        return out


def timed(stats, name, fn, *args, **kw):
    start = time.perf_counter()
    try:
        r = fn(*args, **kw)
        status = r.status_code
    except Exception as exc:                      # a refused connection or a timeout counts as an error
        r, status = None, type(exc).__name__
    stats.add(name, time.perf_counter() - start, status)
    return r


def user_loop(scenario, http, base, key, stats, stop, file_bytes):
    h = {"Authorization": f"Bearer {key}"} if key else {}
    while not stop.is_set():
        if scenario == "health":
            timed(stats, "GET /healthz", http.get, base + "/healthz", timeout=30)
            timed(stats, "GET /readyz", http.get, base + "/readyz", timeout=30)
        elif scenario == "read":
            timed(stats, "GET /v1/me", http.get, base + "/v1/me", headers=h, timeout=30)
            timed(stats, "GET /v1/jobs", http.get, base + "/v1/jobs", headers=h, timeout=30)
            timed(stats, "GET /v1/usage", http.get, base + "/v1/usage", headers=h, timeout=30)
        elif scenario == "upload":
            r = timed(stats, "POST /v1/uploads", http.post, base + "/v1/uploads", headers=h, timeout=30,
                      json={"filename": "load.json", "size": len(file_bytes)})
            if r is None or r.status_code != 201:
                time.sleep(0.5)
                continue
            up = r.json()
            step = up.get("chunk_size") or len(file_bytes)
            for offset in range(0, len(file_bytes), step):
                timed(stats, "PUT chunk", http.put, f"{base}/v1/uploads/{up['id']}/chunk", params={"offset": offset},
                      data=file_bytes[offset:offset + step], headers=h, timeout=60)
            timed(stats, "DELETE upload", http.delete, f"{base}/v1/uploads/{up['id']}", headers=h, timeout=30)


def run(base, scenario, users, seconds, key=None, session_factory=None, file_kb=256):
    if session_factory is None:
        import requests
        session_factory = requests.Session
    stats, stop = Stats(), threading.Event()
    file_bytes = os.urandom(file_kb * 1024)
    threads = [threading.Thread(target=user_loop, args=(scenario, session_factory(), base.rstrip("/"), key, stats,
                                                        stop, file_bytes), daemon=True) for _ in range(users)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join(timeout=60)
    elapsed = time.perf_counter() - start
    return {"url": base, "scenario": scenario, "users": users, "seconds": round(elapsed, 1),
            "results": stats.summary(elapsed)}


def is_local(url):
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", required=True)
    p.add_argument("--scenario", choices=("health", "read", "upload"), default="health")
    p.add_argument("--key", default=os.environ.get("AUTOEDIT_LOADTEST_KEY"), help="an API key (read, upload)")
    p.add_argument("--users", type=int, default=10)
    p.add_argument("--seconds", type=float, default=30)
    p.add_argument("--file-kb", type=int, default=256)
    p.add_argument("--max-p95-ms", type=float, help="exit 1 if any request kind is slower than this at p95")
    p.add_argument("--max-error-rate", type=float, default=0.01)
    p.add_argument("--i-own-this", action="store_true", help="allow a server that is not this computer")
    a = p.parse_args(argv)
    if not is_local(a.url) and not a.i_own_this:
        p.error("only your own servers: add --i-own-this for an address that is not this computer")
    if a.scenario != "health" and not a.key:
        p.error("this scenario needs --key (an API key of a test client)")
    if not 1 <= a.users <= 500 or not 1 <= a.seconds <= 3600:
        p.error("--users 1..500 and --seconds 1..3600")
    report = run(a.url, a.scenario, a.users, a.seconds, a.key, file_kb=a.file_kb)
    print(json.dumps(report, indent=2))
    bad = [n for n, r in report["results"].items() if r["error_rate"] > a.max_error_rate or
           (a.max_p95_ms is not None and r["p95_ms"] > a.max_p95_ms)]
    if bad:
        print("over the limits: " + ", ".join(bad), file=sys.stderr)
    return 1 if bad or not report["results"] else 0


if __name__ == "__main__":
    sys.exit(main())
