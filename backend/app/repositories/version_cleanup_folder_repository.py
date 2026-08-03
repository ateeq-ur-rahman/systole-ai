"""
VersionCleanupFolderRepository

Same "exactly one active folder" singleton pattern as
MonitoredFolderRepository, but for a completely independent selection --
the Version Cleanup Agent and the Folder Monitor Agent are separate
features that may point at the same folder, different folders, or only
one of them may be configured at all.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from app.database.models import VersionCleanupFolder


class VersionCleanupFolderRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get_active(self) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM version_cleanup_folder ORDER BY id DESC LIMIT 1")
        return cur.fetchone()

    def set_folder(self, folder: VersionCleanupFolder) -> int:
        self._conn.execute("DELETE FROM version_cleanup_folder")
        cur = self._conn.execute(
            """INSERT INTO version_cleanup_folder
               (path, enabled, paused, scan_interval_seconds, automatic_cleanup,
                move_to_safe_vault, notifications_enabled, last_scan_status, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'idle')""",
            (folder.path, int(folder.enabled), int(folder.paused), folder.scan_interval_seconds,
             int(folder.automatic_cleanup), int(folder.move_to_safe_vault),
             int(folder.notifications_enabled)),
        )
        return cur.lastrowid

    def clear(self) -> None:
        self._conn.execute("DELETE FROM version_cleanup_folder")

    def update_settings(self, folder_id: int, **fields) -> None:
        allowed = {
            "scan_interval_seconds", "automatic_cleanup", "move_to_safe_vault",
            "notifications_enabled", "enabled", "paused",
        }
        set_clauses, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key}=?")
            values.append(int(value) if isinstance(value, bool) else value)
        if not set_clauses:
            return
        values.append(folder_id)
        self._conn.execute(
            f"UPDATE version_cleanup_folder SET {', '.join(set_clauses)} WHERE id=?", values
        )

    def mark_scan_started(self, folder_id: int) -> None:
        self._conn.execute(
            "UPDATE version_cleanup_folder SET last_scan_status='scanning', status='monitoring' WHERE id=?",
            (folder_id,),
        )

    def mark_scan_finished(self, folder_id: int, status: str, next_scan_at: Optional[str]) -> None:
        self._conn.execute(
            """UPDATE version_cleanup_folder
               SET last_scan_at=datetime('now'), last_scan_status=?, next_scan_at=?,
                   status=CASE WHEN paused=1 THEN 'paused' ELSE 'monitoring' END
               WHERE id=?""",
            (status, next_scan_at, folder_id),
        )

    def set_paused(self, folder_id: int, paused: bool) -> None:
        status = "paused" if paused else "monitoring"
        self._conn.execute(
            "UPDATE version_cleanup_folder SET paused=?, status=? WHERE id=?",
            (int(paused), status, folder_id),
        )
