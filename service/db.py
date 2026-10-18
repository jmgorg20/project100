"""The database: Postgres in production (Supabase or any Postgres), SQLite for development and tests.

All SQL is written once, in a portable subset (`?` placeholders, TEXT ids, DOUBLE PRECISION epoch
seconds, INTEGER 0/1 for true/false, JSON as TEXT). Schema changes are numbered files in
service/migrations/, applied in order and recorded in schema_migrations.
"""

import json
import queue
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DatabaseError(Exception):
    pass


def now():
    return time.time()


def dumps(value):
    return None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(text, default=None):
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


class Tx:
    """One transaction. Rows come back as dicts."""

    def __init__(self, db, conn):
        self.db, self.conn = db, conn
        self.kind = db.kind

    def _sql(self, sql):
        if self.kind == "postgres":
            return sql.replace("?", "%s")
        return sql

    def _cursor(self, sql, params):
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), tuple(params or ()))
        return cur

    def all(self, sql, params=()):
        cur = self._cursor(sql, params)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def value(self, sql, params=(), default=None):
        row = self.one(sql, params)
        return default if row is None else next(iter(row.values()))

    def run(self, sql, params=()):
        return self._cursor(sql, params).rowcount

    def insert(self, table, values):
        cols = list(values)
        self.run(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                 [values[c] for c in cols])

    def update(self, table, key, values, where_extra="", extra_params=()):
        """UPDATE table SET ... WHERE id = key [AND where_extra]. Returns the row count."""
        cols = list(values)
        sets = ", ".join(f"{c} = ?" for c in cols)
        sql = f"UPDATE {table} SET {sets} WHERE id = ?" + (f" AND {where_extra}" if where_extra else "")
        return self.run(sql, [values[c] for c in cols] + [key] + list(extra_params))

    @property
    def for_update(self):
        """Row locking for a SELECT that is followed by an UPDATE (Postgres only; SQLite locks the
        whole database for an immediate transaction)."""
        return " FOR UPDATE SKIP LOCKED" if self.kind == "postgres" else ""


class Database:
    def __init__(self, url="", sqlite_path=None):
        self.url = url or ""
        if self.url.startswith(("postgres://", "postgresql://")):
            self.kind = "postgres"
            self._pool = queue.LifoQueue(maxsize=20)
        else:
            self.kind = "sqlite"
            path = self.url[len("sqlite:///"):] if self.url.startswith("sqlite:///") else sqlite_path
            if not path:
                raise DatabaseError("No database: set SERVICE_DATABASE_URL or a data folder.")
            self.path = str(path)
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._lock = threading.RLock()
            self._memory = None
            if self.path == ":memory:":
                self._memory = self._sqlite_connect()

    # ---------------------------------------------------------- connections
    def _sqlite_connect(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _pg_connect(self):
        import psycopg
        return psycopg.connect(self.url, autocommit=False, connect_timeout=10)

    @contextmanager
    def tx(self, immediate=False):
        """A transaction: committed when the block ends, rolled back on an exception.
        `immediate`: SQLite takes the write lock at once (needed for claim-style read-then-write)."""
        if self.kind == "sqlite":
            conn = self._memory or self._sqlite_connect()
            lock = self._lock if self._memory else None
            if lock:
                lock.acquire()
            try:
                conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                try:
                    yield Tx(self, conn)
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                if lock:
                    lock.release()
                if not self._memory:
                    conn.close()
            return
        try:
            conn = self._pool.get_nowait()
        except queue.Empty:
            conn = self._pg_connect()
        healthy = True
        try:
            yield Tx(self, conn)
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except Exception:
                healthy = False
            raise
        finally:
            if healthy and not conn.closed:
                try:
                    self._pool.put_nowait(conn)
                except queue.Full:
                    conn.close()
            else:
                conn.close()

    def close(self):
        if self.kind == "sqlite":
            if self._memory:
                self._memory.close()
            return
        while True:
            try:
                self._pool.get_nowait().close()
            except queue.Empty:
                break

    # ---------------------------------------------------------- migrations
    def migrate(self):
        """Apply the migrations not applied yet. Returns their names."""
        applied = []
        with self.tx(immediate=True) as t:
            t.run("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at DOUBLE PRECISION)")
            done = {r["name"] for r in t.all("SELECT name FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                for statement in split_sql(path.read_text(encoding="utf-8")):
                    t.run(statement)
                t.insert("schema_migrations", {"name": path.stem, "applied_at": now()})
                applied.append(path.stem)
        return applied

    def ping(self):
        with self.tx() as t:
            return t.value("SELECT 1") == 1


def split_sql(text):
    """The statements of a migration file (no semicolons inside strings in our migrations)."""
    text = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]


def open_database(settings):
    db = Database(settings.database_url, settings.data_path / "service.sqlite3")
    db.migrate()
    return db
