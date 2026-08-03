from __future__ import annotations

import sqlite3

import pytest

from app.container import build_container
from app.config import Settings
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.services.cleanup_service import CleanupService

SAME_HASH_A = "a" * 64
SAME_HASH_B = "b" * 64


def _insert_group_with_files(conn, tmp_path, sha256, detected_hours_ago, folder_name):
    """Creates two real duplicate files on disk plus their duplicate_groups
    row, backdated to simulate a finding detected N hours ago."""
    file_repo = FileRepository(conn)
    dup_repo = DuplicateRepository(conn)

    folder = tmp_path / folder_name
    folder.mkdir()
    content = f"duplicate content for {sha256}\n" * 300
    survivor_path = folder / "keep_me.txt"
    loser_path = folder / "older_copy.txt"
    survivor_path.write_text(content)
    loser_path.write_text(content)

    from app.database.models import FileRecord
    survivor_id = file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=str(survivor_path), filename="keep_me.txt",
        extension=".txt", folder=str(folder), size_bytes=len(content),
        modified_time="2024-06-01T00:00:00",
    ))
    file_repo.set_hash(survivor_id, sha256)
    loser_id = file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=str(loser_path), filename="older_copy.txt",
        extension=".txt", folder=str(folder), size_bytes=len(content),
        modified_time="2024-01-01T00:00:00",
    ))
    file_repo.set_hash(loser_id, sha256)

    group_id = dup_repo.upsert_group(
        sha256, file_count=2, total_size_bytes=len(content) * 2,
        reclaimable_bytes=len(content), survivor_file_id=survivor_id,
    )
    dup_repo.add_member(group_id, survivor_id, True, "latest_modified")
    dup_repo.add_member(group_id, loser_id, False, "redundant_copy")

    conn.execute(
        "UPDATE duplicate_groups SET detected_at = datetime('now', ?) WHERE id = ?",
        (f"-{detected_hours_ago} hours", group_id),
    )
    conn.commit()
    return group_id, survivor_path, loser_path


def test_list_stale_pending_finds_groups_past_the_window(db_conn, tmp_path):
    dup_repo = DuplicateRepository(db_conn)
    stale_id, _, _ = _insert_group_with_files(db_conn, tmp_path, SAME_HASH_A, 30, "Stale")
    fresh_id, _, _ = _insert_group_with_files(db_conn, tmp_path, SAME_HASH_B, 2, "Fresh")

    stale = dup_repo.list_stale_pending(hours=24)
    stale_ids = {row["id"] for row in stale}

    assert stale_id in stale_ids
    assert fresh_id not in stale_ids


def test_findings_within_review_window_are_left_alone(db_conn, tmp_path):
    dup_repo = DuplicateRepository(db_conn)
    _insert_group_with_files(db_conn, tmp_path, SAME_HASH_A, 5, "Recent")

    stale = dup_repo.list_stale_pending(hours=24)
    assert len(stale) == 0


def test_auto_clean_stale_findings_moves_files_and_notifies(db_conn, tmp_path):
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(db_conn, settings)

    group_id, survivor_path, loser_path = _insert_group_with_files(
        db_conn, tmp_path, SAME_HASH_A, 30, "Downloads"
    )

    service = CleanupService(container)
    result = service.auto_clean_stale_findings(hours=24)

    assert result["groups_cleaned"] == 1
    assert result["bytes_reclaimed"] > 0

    # The older copy actually moved off disk; the kept copy is untouched.
    assert survivor_path.exists()
    assert not loser_path.exists()

    # The group itself is now resolved, not sitting pending forever.
    group = container.dup_repo.get_group(group_id)
    assert group["status"] == "cleaned"

    messages = [n["message"] for n in container.notification_repo.list_recent()]
    assert any("automatically cleaned up" in m for m in messages)
    assert any("24 hours" in m for m in messages)


def test_auto_clean_respects_configured_default_window(db_conn, tmp_path):
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    assert settings.cleanup.findings_auto_cleanup_hours == 24  # the requested default

    container = build_container(db_conn, settings)
    _insert_group_with_files(db_conn, tmp_path, SAME_HASH_A, 30, "Downloads")

    service = CleanupService(container)
    result = service.auto_clean_stale_findings()  # no explicit hours -- uses settings default
    assert result["groups_cleaned"] == 1


def test_auto_clean_does_nothing_when_nothing_is_stale(db_conn, tmp_path):
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(db_conn, settings)
    _insert_group_with_files(db_conn, tmp_path, SAME_HASH_A, 1, "Downloads")

    service = CleanupService(container)
    result = service.auto_clean_stale_findings(hours=24)

    assert result["groups_cleaned"] == 0
    assert result["bytes_reclaimed"] == 0
