"""
MonitoredFolderRepository

Backs the Folder Monitor Agent's "exactly one active folder" model.
Deliberately NOT a generic multi-row CRUD repository like
WatchedFolderRepository -- `get_active()` always returns at most one row,
and `set_folder()` enforces that selecting a new folder replaces (not
adds to) whatever was previously configured, matching the product
requirement: "This folder becomes THE active monitored folder."
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from app.database.models import MonitoredFolder


class MonitoredFolderRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get_active(self) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM monitored_folder ORDER BY id DESC LIMIT 1")
        return cur.fetchone()

    def set_folder(self, folder: MonitoredFolder) -> int:
        """Replaces whatever folder was previously monitored (if any) with
        this one. We keep history simple by clearing the single-row table
        rather than modeling multiple past folders -- this agent tracks
        one active folder, by design."""
        self._conn.execute("DELETE FROM monitored_folder")
        cur = self._conn.execute(
            """INSERT INTO monitored_folder
               (path, enabled, paused, scan_interval_seconds, keep_strategy,
                delete_action, notifications_enabled, last_scan_status, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'idle')""",
            (folder.path, int(folder.enabled), int(folder.paused),
             folder.scan_interval_seconds, folder.keep_strategy,
             folder.delete_action, int(folder.notifications_enabled)),
        )
        return cur.lastrowid

    def clear(self) -> None:
        self._conn.execute("DELETE FROM monitored_folder")

    def update_settings(self, folder_id: int, **fields) -> None:
        """Generic partial update for settings-panel edits (scan interval,
        notifications toggle, etc.) without needing a bespoke setter for
        every field."""
        if not fields:
            return
        allowed = {
            "scan_interval_seconds", "keep_strategy", "delete_action",
            "notifications_enabled", "enabled", "paused",
        }
        set_clauses = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key}=?")
            values.append(int(value) if isinstance(value, bool) else value)
        if not set_clauses:
            return
        values.append(folder_id)
        self._conn.execute(
            f"UPDATE monitored_folder SET {', '.join(set_clauses)} WHERE id=?", values
        )

    def mark_scan_started(self, folder_id: int) -> None:
        self._conn.execute(
            "UPDATE monitored_folder SET last_scan_status='scanning', status='monitoring' WHERE id=?",
            (folder_id,),
        )

    def mark_scan_finished(self, folder_id: int, status: str, next_scan_at: Optional[str]) -> None:
        self._conn.execute(
            """UPDATE monitored_folder
               SET last_scan_at=datetime('now'), last_scan_status=?, next_scan_at=?,
                   status=CASE WHEN paused=1 THEN 'paused' ELSE 'monitoring' END
               WHERE id=?""",
            (status, next_scan_at, folder_id),
        )

    def set_paused(self, folder_id: int, paused: bool) -> None:
        status = "paused" if paused else "monitoring"
        self._conn.execute(
            "UPDATE monitored_folder SET paused=?, status=? WHERE id=?",
            (int(paused), status, folder_id),
        )
