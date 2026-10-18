"""Rate limits kept in the database (so they hold across several API processes): a counter per key
and per minute. Keys: "client:<id>" (each client's own limit), "ip:<address>" (requests without a
valid key), "authfail:<address>" (wrong keys: slows down key guessing), "upload:<client>"."""

import time

WINDOW = 60


def hit(t, key, limit, window=WINDOW, cost=1):
    """Count one request. Returns (allowed, seconds until the window resets)."""
    start = int(time.time() // window * window)
    t.run("INSERT INTO rate_counters (key, window_start, count) VALUES (?, ?, ?) ON CONFLICT (key, window_start) "
          "DO UPDATE SET count = rate_counters.count + excluded.count", (key, start, int(cost)))
    count = int(t.value("SELECT count FROM rate_counters WHERE key = ? AND window_start = ?", (key, start), 0))
    return count <= limit, max(1, int(start + window - time.time()))


def peek(t, key, window=WINDOW):
    start = int(time.time() // window * window)
    return int(t.value("SELECT count FROM rate_counters WHERE key = ? AND window_start = ?", (key, start), 0) or 0)


def cleanup(t, older_than=2 * 3600):
    return t.run("DELETE FROM rate_counters WHERE window_start < ?", (int(time.time() - older_than),))
