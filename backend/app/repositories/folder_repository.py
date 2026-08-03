from __future__ import annotations

import sqlite3
from typing import Optional

from app.database.models import WatchedFolder


class FolderRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, folder: WatchedFolder) -> int:
        existing = self.get_by_path(folder.path)
        if existing:
            self._conn.execute(
                "UPDATE watched_folders SET enabled=?, label=?, drive_id=? WHERE id=?",
                (int(folder.enabled), folder.label, folder.drive_id, existing["id"]),
            )
            return existing["id"]

        cur = self._conn.execute(
            """INSERT INTO watched_folders (path, label, drive_id, enabled, last_scan_status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (folder.path, folder.label, folder.drive_id, int(folder.enabled)),
        )
        return cur.lastrowid

    def get_by_path(self, path: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM watched_folders WHERE path = ?", (path,))
        return cur.fetchone()

    def get_by_id(self, folder_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM watched_folders WHERE id = ?", (folder_id,))
        return cur.fetchone()

    def list_all(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        if enabled_only:
            cur = self._conn.execute(
                "SELECT * FROM watched_folders WHERE enabled = 1 ORDER BY added_at"
            )
        else:
            cur = self._conn.execute("SELECT * FROM watched_folders ORDER BY added_at")
        return cur.fetchall()

    def set_enabled(self, folder_id: int, enabled: bool) -> None:
        self._conn.execute(
            "UPDATE watched_folders SET enabled=? WHERE id=?", (int(enabled), folder_id)
        )

    def mark_scan_started(self, folder_id: int) -> None:
        self._conn.execute(
            "UPDATE watched_folders SET last_scan_status='scanning' WHERE id=?", (folder_id,)
        )

    def mark_scan_finished(self, folder_id: int, status: str) -> None:
        self._conn.execute(
            """UPDATE watched_folders SET last_scanned_at=datetime('now'), last_scan_status=?
               WHERE id=?""",
            (status, folder_id),
        )

    def remove(self, folder_id: int) -> None:
        self._conn.execute("DELETE FROM watched_folders WHERE id=?", (folder_id,))
