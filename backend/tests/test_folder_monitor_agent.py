from __future__ import annotations

import os
import time

import pytest

from app.agents.duplicate_detection import DuplicateDetectionAgent
from app.agents.file_scanner import FileScannerAgent
from app.agents.folder_monitor import FolderMonitorAgent, FolderMonitorError
from app.agents.hash_engine import HashEngine
from app.agents.safe_cleanup import SafeCleanupAgent
from app.agents.version_intelligence import VersionIntelligenceAgent
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.monitored_folder_repository import MonitoredFolderRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.vault_repository import VaultRepository
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault


def _build_agent(db_conn, tmp_path, min_size_bytes: int = 0):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    vault_repo = VaultRepository(db_conn)
    folder_repo = MonitoredFolderRepository(db_conn)
    notify_repo = NotificationRepository(db_conn)
    guard = PathGuard()
    vault = SafeVault(str(tmp_path / "_vault"))

    hash_engine = HashEngine(file_repo, guard)
    file_scanner = FileScannerAgent(file_repo, hash_engine, guard)
    version_agent = VersionIntelligenceAgent()
    duplicate_detection = DuplicateDetectionAgent(file_repo, dup_repo, version_agent, min_size_bytes)
    safe_cleanup = SafeCleanupAgent(file_repo, dup_repo, vault_repo, vault, guard)

    agent = FolderMonitorAgent(
        db_conn, folder_repo, file_repo, dup_repo, vault_repo, notify_repo, guard,
        file_scanner, duplicate_detection, safe_cleanup,
    )
    return agent, notify_repo, folder_repo


def test_set_folder_runs_initial_scan_and_reports_no_duplicates(db_conn, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "unique.txt").write_text("nothing else looks like this" * 50)

    agent, notify_repo, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(watch_dir))

    assert status["active"] is True
    assert status["total_files"] == 1
    assert status["duplicate_groups"] == 0

    messages = [n["message"] for n in notify_repo.list_recent()]
    assert any("Monitoring" in m for m in messages)
    assert any("No duplicates found" in m for m in messages)


def test_cycle_detects_and_auto_cleans_duplicates(db_conn, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    content = "duplicate report content\n" * 300

    older = watch_dir / "report_v1.pdf"
    newer = watch_dir / "report_v2.pdf"
    older.write_text(content)
    newer.write_text(content)

    now = time.time()
    os.utime(older, (now - 3600, now - 3600))
    os.utime(newer, (now, now))

    agent, notify_repo, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(watch_dir))

    # Newest survives on disk; older copy moved to vault.
    assert newer.exists()
    assert not older.exists()

    assert status["recovered_bytes"] > 0

    messages = [n["message"] for n in notify_repo.list_recent()]
    assert any("duplicate file group" in m for m in messages)
    assert any("moved to Safe Vault" in m for m in messages)
    assert any("Recovered" in m for m in messages)


def test_duplicate_detection_never_uses_filename(db_conn, tmp_path):
    """Direct regression test of the spec's core rule for this feature:
    Resume.pdf / Resume (1).pdf / Resume Copy.pdf must only be grouped if
    their SHA-256 matches -- never because of similar names."""
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()

    same_content = "actual resume content here\n" * 300
    different_content = "a totally different document\n" * 300

    (watch_dir / "Resume.pdf").write_text(same_content)
    (watch_dir / "Resume (1).pdf").write_text(same_content)
    (watch_dir / "Resume Copy.pdf").write_text(different_content)

    agent, _, _ = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch_dir))

    remaining = list(watch_dir.glob("*.pdf"))
    # The two identical files collapse to one survivor; the genuinely
    # different "Resume Copy.pdf" is never touched despite the similar name.
    assert len(remaining) == 2
    assert (watch_dir / "Resume Copy.pdf").exists()


def test_second_cycle_does_not_reflag_already_cleaned_duplicates(db_conn, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    content = "dup content\n" * 300
    (watch_dir / "a.txt").write_text(content)
    (watch_dir / "b.txt").write_text(content)

    agent, notify_repo, _ = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch_dir))

    notify_repo.mark_all_read()
    result = agent.run_cycle()

    assert result.duplicate_groups_found == 0  # nothing left to flag
    assert result.files_moved_to_vault == 0


def test_pause_skips_scheduled_cycles_but_not_manual_ones(db_conn, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "file.txt").write_text("content")

    agent, _, folder_repo = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch_dir))
    agent.pause()

    status = agent.get_status()
    assert status["paused"] is True

    # A scheduled (non-initial) cycle should be a no-op while paused.
    result = agent.run_cycle(is_initial=False)
    assert result.files_scanned == 0

    agent.resume()
    status = agent.get_status()
    assert status["paused"] is False


def test_set_folder_rejects_protected_path(db_conn, tmp_path):
    fake_system_dir = tmp_path / "Windows" / "System32"
    fake_system_dir.mkdir(parents=True)

    agent, _, _ = _build_agent(db_conn, tmp_path)
    with pytest.raises(FolderMonitorError):
        agent.set_folder(str(fake_system_dir))


def test_set_folder_rejects_nonexistent_path(db_conn, tmp_path):
    agent, _, _ = _build_agent(db_conn, tmp_path)
    with pytest.raises(FolderMonitorError):
        agent.set_folder(str(tmp_path / "does_not_exist"))


def test_selecting_a_new_folder_replaces_the_active_one(db_conn, tmp_path):
    first_dir = tmp_path / "First"
    second_dir = tmp_path / "Second"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "a.txt").write_text("a")
    (second_dir / "b.txt").write_text("b")

    agent, _, _ = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(first_dir))
    status = agent.set_folder(str(second_dir))

    assert status["path"] == str(second_dir)
    # Only one active folder at a time.
    assert agent.get_status()["path"] == str(second_dir)


def test_remove_clears_active_folder(db_conn, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("a")

    agent, _, _ = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch_dir))
    agent.remove()

    assert agent.get_status() == {"active": False}


def test_notifications_disabled_suppresses_messages(db_conn, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("a")

    agent, notify_repo, folder_repo = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch_dir))

    active = folder_repo.get_active()
    folder_repo.update_settings(active["id"], notifications_enabled=False)
    db_conn.commit()

    count_before = len(notify_repo.list_recent())
    agent.run_cycle()
    count_after = len(notify_repo.list_recent())

    assert count_after == count_before  # no new notifications while disabled
