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
