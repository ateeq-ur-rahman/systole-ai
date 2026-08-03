from __future__ import annotations

import sqlite3

import pytest

from app.container import build_container
from app.config import Settings
from app.repositories.vault_repository import VaultRepository
from app.services.cleanup_service import CleanupService


def _insert_vault_entry(conn: sqlite3.Connection, expires_in_minutes: float, restored: int = 0) -> int:
    cur = conn.execute(
        """INSERT INTO cleanup_history (original_path, vault_path, action, size_bytes, reason)
           VALUES (?, ?, 'moved_to_vault', 1000, 'redundant_copy')""",
        (f"C:\\Downloads\\file_{expires_in_minutes}.txt", f"C:\\vault\\{expires_in_minutes}.txt"),
    )
    cleanup_id = cur.lastrowid
    sign = "+" if expires_in_minutes >= 0 else ""  # SQLite modifiers already carry their own "-"
    cur = conn.execute(
        """INSERT INTO safe_vault (cleanup_history_id, vault_path, original_path, size_bytes, expires_at, restored)
           VALUES (?, ?, ?, 1000, datetime('now', ?), ?)""",
        (cleanup_id, f"C:\\vault\\{expires_in_minutes}.txt", f"C:\\Downloads\\file_{expires_in_minutes}.txt",
         f"{sign}{expires_in_minutes} minutes", restored),
    )
    return cur.lastrowid


def test_entries_expiring_within_window_are_found(db_conn):
    repo = VaultRepository(db_conn)
    soon_id = _insert_vault_entry(db_conn, expires_in_minutes=30)      # within 60-min window
    later_id = _insert_vault_entry(db_conn, expires_in_minutes=200)    # outside window
    db_conn.commit()

    due = repo.entries_expiring_within(60)
    due_ids = {row["id"] for row in due}

    assert soon_id in due_ids
    assert later_id not in due_ids


def test_already_expired_entries_are_not_double_counted_as_warnings(db_conn):
    """An entry that's already past its expiry belongs to purge_expired(),
    not the pre-deletion warning -- entries_expiring_within only looks
    forward, never backward."""
    repo = VaultRepository(db_conn)
    already_expired_id = _insert_vault_entry(db_conn, expires_in_minutes=-10)
    db_conn.commit()

    due = repo.entries_expiring_within(60)
    assert already_expired_id not in {row["id"] for row in due}
    assert already_expired_id in {row["id"] for row in repo.expired_entries()}


def test_restored_entries_are_never_warned_about(db_conn):
    repo = VaultRepository(db_conn)
    restored_id = _insert_vault_entry(db_conn, expires_in_minutes=10, restored=1)
    db_conn.commit()

    due = repo.entries_expiring_within(60)
    assert restored_id not in {row["id"] for row in due}


def test_warning_is_sent_only_once_per_entry(db_conn):
    repo = VaultRepository(db_conn)
    entry_id = _insert_vault_entry(db_conn, expires_in_minutes=15)
    db_conn.commit()

    first_pass = repo.entries_expiring_within(60)
    assert entry_id in {row["id"] for row in first_pass}

    repo.mark_warning_sent(entry_id)
    db_conn.commit()

    second_pass = repo.entries_expiring_within(60)
    assert entry_id not in {row["id"] for row in second_pass}


def test_send_expiry_warnings_creates_notifications_and_marks_sent(db_conn, tmp_path):
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(db_conn, settings)

    _insert_vault_entry(db_conn, expires_in_minutes=20)
    db_conn.commit()

    service = CleanupService(container)
    warned_count = service.send_expiry_warnings(lead_minutes=60)

    assert warned_count == 1

    notifications = container.notification_repo.list_recent()
    messages = [n["message"] for n in notifications]
    assert any("permanently deleted" in m for m in messages)

    # Running it again immediately must not re-warn the same entry.
    second_run = service.send_expiry_warnings(lead_minutes=60)
    assert second_run == 0


def test_send_expiry_warnings_uses_configured_default_lead_time(db_conn, tmp_path):
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    assert settings.cleanup.warning_lead_time_minutes == 60  # the requested "1 hour" default
    assert settings.cleanup.retention_days == 1  # the requested "1 day" default

    container = build_container(db_conn, settings)
    _insert_vault_entry(db_conn, expires_in_minutes=45)  # within the default 60-minute lead
    db_conn.commit()

    service = CleanupService(container)
    warned_count = service.send_expiry_warnings()  # no explicit lead_minutes -- uses settings default
    assert warned_count == 1


def test_purge_expired_still_works_alongside_warnings(db_conn, tmp_path):
    """The warning mechanism and the actual purge are independent --
    purge_expired() must still correctly remove entries whose retention
    window has fully elapsed, regardless of whether they were warned about."""
    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(db_conn, settings)

    import os
    vault_dir = tmp_path / "vault" / "abc123"
    vault_dir.mkdir(parents=True)
    vault_file = vault_dir / "old_duplicate.txt"
    vault_file.write_text("stale content")

    cur = db_conn.execute(
        """INSERT INTO cleanup_history (original_path, vault_path, action, size_bytes, reason)
           VALUES (?, ?, 'moved_to_vault', 13, 'redundant_copy')""",
        ("C:\\Downloads\\old_duplicate.txt", str(vault_file)),
    )
    cleanup_id = cur.lastrowid
    db_conn.execute(
        """INSERT INTO safe_vault (cleanup_history_id, vault_path, original_path, size_bytes, expires_at, restored)
           VALUES (?, ?, ?, 13, datetime('now', '-5 minutes'), 0)""",
        (cleanup_id, str(vault_file), "C:\\Downloads\\old_duplicate.txt"),
    )
    db_conn.commit()

    service = CleanupService(container)
    purged_count = service.purge_expired()

    assert purged_count == 1
    assert not vault_file.exists()
