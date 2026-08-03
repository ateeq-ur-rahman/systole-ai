from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_container
from app.config import Settings
from app.container import build_container
from app.database.db import _SCHEMA_PATH, _connect
from app.database.migrations import run_migrations


@pytest.fixture
def file_db_path(tmp_path):
    """A real file-backed SQLite database (not :memory:) -- this is the
    only way to reproduce the bug this test guards against. An in-memory
    database is inherently single-connection: two separate sqlite3.connect
    calls to ':memory:' are two entirely different databases, so a
    missing commit() can never be detected that way. A file-backed DB, by
    contrast, is genuinely shared across independent connections -- the
    same setup api/routes/*.py + run.py's per-thread connections use in
    production, and the exact scenario that surfaced 'database is
    locked' + silently-lost writes."""
    db_path = tmp_path / "systole.db"
    conn = _connect(str(db_path))
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()
    run_migrations(conn)
    conn.close()
    return str(db_path)


def test_set_folder_is_durably_committed_to_a_separate_connection(file_db_path, tmp_path):
    """Regression test for a real production bug: the Folder Monitor API
    routes were missing conn.commit() after mutating operations. In a
    single-shared-connection test setup this bug is invisible (uncommitted
    writes are still readable from the SAME connection that made them) --
    it only shows up when a genuinely different connection tries to read
    or write the same file, exactly as happens in production where each
    request thread gets its own connection. This test uses two
    independent connections to the same file to catch exactly that."""
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "file.txt").write_text("hello")

    conn_a = _connect(file_db_path)
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(conn_a, settings)

    from app.main import app
    app.dependency_overrides[get_container] = lambda: container

    with TestClient(app) as client:
        resp = client.post("/folder-monitor", json={"path": str(watch_dir)})
        assert resp.status_code == 200

    app.dependency_overrides.clear()

    # A completely separate connection to the same file must see the
    # write. If it doesn't, the transaction was never committed -- the
    # exact bug this test guards against.
    conn_b = sqlite3.connect(file_db_path)
    conn_b.row_factory = sqlite3.Row
    row = conn_b.execute("SELECT * FROM monitored_folder").fetchone()
    conn_b.close()

    assert row is not None, "monitored_folder row was never committed -- visible only to the writing connection"
    assert row["path"] == str(watch_dir)


def test_second_connection_can_write_immediately_after_first_finishes(file_db_path, tmp_path):
    """The concrete symptom from the field: after POST /folder-monitor,
    a second connection attempting its own write must not hit 'database
    is locked' -- which happens when the first connection's transaction
    was left open (no commit/rollback) and is still holding the write
    lock."""
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "file.txt").write_text("hello")

    conn_a = _connect(file_db_path)
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(conn_a, settings)

    from app.main import app
    app.dependency_overrides[get_container] = lambda: container

    with TestClient(app) as client:
        client.post("/folder-monitor", json={"path": str(watch_dir)})

    app.dependency_overrides.clear()

    # Simulate a second, independent writer (e.g. a different request
    # thread, or the scheduler tick) -- must not raise "database is locked".
    conn_b = _connect(file_db_path)
    conn_b.execute(
        "INSERT INTO notifications (message, level) VALUES (?, ?)", ("test write", "info")
    )
    conn_b.commit()
    conn_b.close()
