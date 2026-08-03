from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from app.agents.duplicate_detection import DuplicateDetectionAgent
from app.agents.file_scanner import FileScannerAgent
from app.agents.folder_monitor import FolderMonitorAgent
from app.agents.hash_engine import HashEngine
from app.agents.safe_cleanup import SafeCleanupAgent
from app.agents.version_intelligence import VersionIntelligenceAgent
from app.database.db import _SCHEMA_PATH, _connect
from app.database.migrations import run_migrations
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.monitored_folder_repository import MonitoredFolderRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.vault_repository import VaultRepository
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault


@pytest.fixture
def file_db_path(tmp_path):
    db_path = tmp_path / "systole.db"
    conn = _connect(str(db_path))
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()
    run_migrations(conn)
    conn.close()
    return str(db_path)


def _build_agent(conn, tmp_path):
    file_repo = FileRepository(conn)
    dup_repo = DuplicateRepository(conn)
    vault_repo = VaultRepository(conn)
    folder_repo = MonitoredFolderRepository(conn)
    notify_repo = NotificationRepository(conn)
    guard = PathGuard()
    vault = SafeVault(str(tmp_path / "_vault"))

    hash_engine = HashEngine(file_repo, guard)
    file_scanner = FileScannerAgent(file_repo, hash_engine, guard)
    version_agent = VersionIntelligenceAgent()
    duplicate_detection = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)
    safe_cleanup = SafeCleanupAgent(file_repo, dup_repo, vault_repo, vault, guard)

    return FolderMonitorAgent(
        conn, folder_repo, file_repo, dup_repo, vault_repo, notify_repo, guard,
        file_scanner, duplicate_detection, safe_cleanup,
    )


def test_mid_cycle_failure_does_not_block_other_connections(file_db_path, tmp_path):
    """Regression test for a real production bug: when scan_path() (or any
    step inside run_cycle) raised an exception, the FolderMonitorAgent's
    except-block used to write a 'failed' status update and then
    re-raise -- WITHOUT ever committing or rolling back. That left the
    transaction open indefinitely, holding a write lock that then blocked
    every other connection (a different request thread, or the scheduler
    tick) with 'database is locked', even for operations completely
    unrelated to the original failure. This test forces scan_path() to
    raise mid-cycle, confirms run_cycle() propagates the error (callers
    still need to know it failed), and then proves a totally separate
    connection can immediately write to the database afterward."""
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "file.txt").write_text("hello")

    conn = _connect(file_db_path)
    agent = _build_agent(conn, tmp_path)
    agent.set_folder(str(watch_dir))

    with patch.object(
        agent._file_scanner, "scan_path", side_effect=RuntimeError("simulated disk failure")
    ):
        with pytest.raises(RuntimeError):
            agent.run_cycle(is_initial=False)

    # A completely separate connection must be able to write immediately
    # -- if the previous transaction was left open, this raises
    # 'database is locked' within the busy_timeout window.
    other_conn = _connect(file_db_path)
    other_conn.execute("INSERT INTO notifications (message, level) VALUES (?, ?)", ("probe", "info"))
    other_conn.commit()
    other_conn.close()

    # The failure must also have been durably recorded (not lost along
    # with the rest of the failed transaction).
    verify_conn = sqlite3.connect(file_db_path)
    verify_conn.row_factory = sqlite3.Row
    row = verify_conn.execute("SELECT * FROM monitored_folder").fetchone()
    verify_conn.close()
    assert row["last_scan_status"] == "failed"


def test_agent_owned_transaction_works_when_called_outside_any_http_request(file_db_path, tmp_path):
    """The whole point of moving commit/rollback into the agent: it must
    behave identically whether invoked from an API route or called
    directly, the way run.py's scheduler tick and real-time watcher call
    it. This simulates that direct-call path."""
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    content = "identical content\n" * 300
    (watch_dir / "a.txt").write_text(content)
    (watch_dir / "b.txt").write_text(content)

    conn = _connect(file_db_path)
    agent = _build_agent(conn, tmp_path)

    # No HTTP request involved at all -- exactly like run.py's background callbacks.
    status = agent.set_folder(str(watch_dir))
    assert status["recovered_bytes"] > 0

    result = agent.run_cycle(is_initial=False)
    assert result.errors == 0

    # And a separate connection sees everything durably.
    verify_conn = sqlite3.connect(file_db_path)
    verify_conn.row_factory = sqlite3.Row
    vault_count = verify_conn.execute("SELECT COUNT(*) as c FROM safe_vault").fetchone()["c"]
    verify_conn.close()
    assert vault_count == 1
