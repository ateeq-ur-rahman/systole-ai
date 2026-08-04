"""
SQLite connection management for Systole AI - Storage Manager.

A single module-level helper (`get_connection`) hands out connections
configured with WAL mode + foreign keys, and `init_db` applies schema.sql
idempotently. Repositories (app/repositories/*) are the only layer that
should import this module directly -- services and agents should go
through repositories.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings
from app.database.migrations import run_migrations

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"
_local = threading.local()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # If a concurrent connection (a different request thread, or the
    # background scheduler thread) is mid-write, wait up to 5s and retry
    # internally rather than raising "database is locked" immediately.
    # This is defense-in-depth: the real fix for that class of bug is
    # never leaving a transaction uncommitted (see api/routes/*.py, which
    # must commit/rollback after every mutating repository call) -- this
    # PRAGMA just makes brief, legitimate contention between threads
    # (e.g. the Folder Monitor's periodic tick landing at the same moment
    # as an API request) resolve gracefully instead of failing outright.
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_connection() -> sqlite3.Connection:
    """Thread-local SQLite connection (SQLite connections aren't safe to
    share across threads without care; this keeps one per worker thread)."""
    if not hasattr(_local, "conn"):
        settings = get_settings()
        _local.conn = _connect(settings.database_path)
    return _local.conn


class _ThreadSafeCursor:
    """Wraps a real sqlite3.Cursor. Holds the connection-wide lock,
    acquired by _ThreadSafeConnection.execute() below, until the caller
    actually consumes the results (or the cursor is garbage collected,
    as a safety net for callers that never fetch -- e.g. plain
    INSERT/UPDATE/DELETE statements, extremely common in this codebase).
    This is what actually closes the race: releasing the lock right
    after execute() returns would still let a second thread's execute()
    corrupt this cursor's still-pending state before this thread gets to
    fetchone()/fetchall()."""

    def __init__(self, cursor: sqlite3.Cursor, lock: threading.RLock):
        self._cursor = cursor
        self._lock = lock
        self._released = False

    def _release(self) -> None:
        if not self._released:
            self._released = True
            self._lock.release()

    def fetchone(self):
        try:
            return self._cursor.fetchone()
        finally:
            self._release()

    def fetchall(self):
        try:
            return self._cursor.fetchall()
        finally:
            self._release()

    def fetchmany(self, size: int = 1):
        try:
            return self._cursor.fetchmany(size)
        finally:
            self._release()

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        try:
            yield from self._cursor
        finally:
            self._release()

    def __del__(self):
        # Safety net: statements whose caller never fetches (INSERT,
        # UPDATE, DELETE) would otherwise hold the lock until the next
        # GC cycle happens to run. CPython's refcounting collects this
        # object immediately once it goes out of scope in the common
        # case (`conn.execute(...)` with no assignment, or the local
        # variable falling out of scope), so this fires promptly in
        # practice even though __del__ timing isn't guaranteed by the
        # language itself.
        self._release()


class ThreadSafeConnection:
    """Serializes all access to a single sqlite3.Connection shared across
    multiple threads. Needed specifically because run.py builds one
    Container (and its one connection) at startup and shares it with
    background threads it doesn't control directly -- the watchdog
    real-time file-watcher's callback thread, and APScheduler's job
    thread pool. Those threads never go through get_connection() above
    (which would otherwise give each of them their own, safely-isolated
    connection); they just call methods on the one shared connection
    object captured in their closures. check_same_thread=False permits
    that cross-thread usage but does not make it safe under genuine
    concurrent access -- two threads calling execute() on the same
    connection at the same instant can corrupt each other's in-flight
    cursor state, which is exactly the
    'sqlite3.InterfaceError: bad parameter or other API misuse' /
    'sqlite3.DatabaseError: another row available' failures this fixes.

    Deliberately NOT used for the FastAPI per-request connections in
    api/deps.py -- those already correctly call get_connection() fresh
    per request, giving each request-handling thread its own genuinely
    separate connection with no sharing at all, so no lock is needed
    there."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()

    def execute(self, *args, **kwargs) -> _ThreadSafeCursor:
        self._lock.acquire()
        try:
            cur = self._conn.execute(*args, **kwargs)
        except Exception:
            self._lock.release()
            raise
        return _ThreadSafeCursor(cur, self._lock)

    def executemany(self, *args, **kwargs) -> _ThreadSafeCursor:
        self._lock.acquire()
        try:
            cur = self._conn.executemany(*args, **kwargs)
        except Exception:
            self._lock.release()
            raise
        return _ThreadSafeCursor(cur, self._lock)

    def executescript(self, script: str):
        with self._lock:
            return self._conn.executescript(script)

    def commit(self):
        with self._lock:
            return self._conn.commit()

    def rollback(self):
        with self._lock:
            return self._conn.rollback()

    def close(self):
        with self._lock:
            return self._conn.close()

    def cursor(self):
        with self._lock:
            return self._conn.cursor()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    def __getattr__(self, name):
        return getattr(self._conn, name)


def init_db() -> None:
    settings = get_settings()
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()
    run_migrations(conn)


@contextmanager
def transaction():
    """Usage: with transaction() as conn: conn.execute(...)"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
