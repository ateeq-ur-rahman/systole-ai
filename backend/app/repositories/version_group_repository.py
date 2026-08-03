from __future__ import annotations

import sqlite3
from typing import Optional


class VersionGroupRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert_group(self, base_name: str, member_count: int, kept_member_path: Optional[str],
                      storage_saved_bytes: int, status: str, decision_reason: str) -> int:
        cur = self._conn.execute(
            "SELECT id FROM version_groups WHERE base_name = ? AND status != 'cleaned'", (base_name,)
        )
        row = cur.fetchone()
        if row:
            group_id = row["id"]
            self._conn.execute(
                """UPDATE version_groups SET member_count=?, kept_member_path=?,
                   storage_saved_bytes=?, status=?, decision_reason=? WHERE id=?""",
                (member_count, kept_member_path, storage_saved_bytes, status, decision_reason, group_id),
            )
            self._conn.execute("DELETE FROM version_group_members WHERE group_id=?", (group_id,))
        else:
            cur = self._conn.execute(
                """INSERT INTO version_groups
                   (base_name, member_count, kept_member_path, storage_saved_bytes, status, decision_reason)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (base_name, member_count, kept_member_path, storage_saved_bytes, status, decision_reason),
            )
            group_id = cur.lastrowid
        return group_id

    def add_member(self, group_id: int, full_path: str, is_folder: bool, version_label: str,
                    version_number: Optional[int], size_bytes: int, modified_time: str,
                    created_time: str, is_kept: bool, move_status: str = "pending") -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO version_group_members
               (group_id, full_path, is_folder, version_label, version_number, size_bytes,
                modified_time, created_time, is_kept, move_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (group_id, full_path, int(is_folder), version_label, version_number, size_bytes,
             modified_time, created_time, int(is_kept), move_status),
        )

    def set_member_move_status(self, group_id: int, full_path: str, status: str) -> None:
        self._conn.execute(
            "UPDATE version_group_members SET move_status=? WHERE group_id=? AND full_path=?",
            (status, group_id, full_path),
        )

    def resolve_group(self, group_id: int, kept_member_path: str, storage_saved_bytes: int,
                       status: str, decision_reason: str) -> None:
        self._conn.execute(
            """UPDATE version_groups SET kept_member_path=?, storage_saved_bytes=?,
               status=?, decision_reason=?, resolved_at=datetime('now') WHERE id=?""",
            (kept_member_path, storage_saved_bytes, status, decision_reason, group_id),
        )

    def get_group(self, group_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM version_groups WHERE id=?", (group_id,))
        return cur.fetchone()

    def get_members(self, group_id: int) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM version_group_members WHERE group_id=? ORDER BY full_path", (group_id,)
        )
        return cur.fetchall()

    def list_groups(self, status: Optional[str] = None) -> list[sqlite3.Row]:
        if status:
            cur = self._conn.execute(
                "SELECT * FROM version_groups WHERE status=? ORDER BY detected_at DESC", (status,)
            )
        else:
            cur = self._conn.execute("SELECT * FROM version_groups ORDER BY detected_at DESC")
        return cur.fetchall()

    def total_storage_saved(self) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(storage_saved_bytes),0) as total FROM version_groups WHERE status='cleaned'"
        )
        return cur.fetchone()["total"]
