from __future__ import annotations

import sqlite3
from typing import Optional

from app.repositories.file_repository import FileRepository


class DuplicateRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert_group(self, sha256: str, file_count: int, total_size_bytes: int,
                      reclaimable_bytes: int, survivor_file_id: Optional[int]) -> int:
        cur = self._conn.execute("SELECT id FROM duplicate_groups WHERE sha256=?", (sha256,))
        row = cur.fetchone()
        if row:
            self._conn.execute(
                """UPDATE duplicate_groups SET file_count=?, total_size_bytes=?,
                   reclaimable_bytes=?, survivor_file_id=?, status='pending'
                   WHERE id=?""",
                (file_count, total_size_bytes, reclaimable_bytes, survivor_file_id, row["id"]),
            )
            group_id = row["id"]
        else:
            cur = self._conn.execute(
                """INSERT INTO duplicate_groups
                   (sha256, file_count, total_size_bytes, reclaimable_bytes, survivor_file_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (sha256, file_count, total_size_bytes, reclaimable_bytes, survivor_file_id),
            )
            group_id = cur.lastrowid

        # reset members for idempotent re-detection
        self._conn.execute("DELETE FROM duplicate_group_members WHERE group_id=?", (group_id,))
        return group_id

    def add_member(self, group_id: int, file_id: int, is_survivor: bool, reason: str) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO duplicate_group_members
               (group_id, file_id, is_survivor, selection_reason)
               VALUES (?, ?, ?, ?)""",
            (group_id, file_id, int(is_survivor), reason),
        )

    def list_groups(self, status: Optional[str] = None) -> list[sqlite3.Row]:
        if status:
            cur = self._conn.execute(
                "SELECT * FROM duplicate_groups WHERE status=? ORDER BY reclaimable_bytes DESC",
                (status,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM duplicate_groups ORDER BY reclaimable_bytes DESC"
            )
        return cur.fetchall()

    def get_group(self, group_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM duplicate_groups WHERE id=?", (group_id,))
        return cur.fetchone()

    def list_stale_pending(self, hours: int) -> list[sqlite3.Row]:
        """Pending (undecided) duplicate groups that AI detected more than
        `hours` ago and the user hasn't acted on. These are the
        candidates for automatic cleanup -- AI gives the user a review
        window before acting on their behalf."""
        cur = self._conn.execute(
            """SELECT * FROM duplicate_groups
               WHERE status = 'pending' AND detected_at <= datetime('now', ?)
               ORDER BY detected_at ASC""",
            (f"-{hours} hours",),
        )
        return cur.fetchall()

    def get_members(self, group_id: int) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """SELECT files.*, duplicate_group_members.is_survivor, duplicate_group_members.selection_reason
               FROM duplicate_group_members
               JOIN files ON files.id = duplicate_group_members.file_id
               WHERE duplicate_group_members.group_id = ?""",
            (group_id,),
        )
        return cur.fetchall()

    def set_status(self, group_id: int, status: str) -> None:
        self._conn.execute("UPDATE duplicate_groups SET status=? WHERE id=?", (status, group_id))

    def total_reclaimable(self) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(reclaimable_bytes),0) as total FROM duplicate_groups WHERE status != 'cleaned'"
        )
        return cur.fetchone()["total"]

    def groups_under_path(self, path_prefix: str, status: Optional[str] = None) -> list[sqlite3.Row]:
        """Duplicate groups where at least one member file lives under
        `path_prefix`. Used by the Folder Monitor Agent's dashboard status,
        since duplicate_groups itself has no folder scope (a hash could in
        principle be shared with files outside the monitored folder)."""
        like_pattern = FileRepository._like_prefix(path_prefix)
        params: list = [like_pattern]
        status_clause = ""
        if status:
            status_clause = "AND dg.status = ?"
            params.append(status)
        cur = self._conn.execute(
            f"""SELECT DISTINCT dg.* FROM duplicate_groups dg
                JOIN duplicate_group_members dgm ON dgm.group_id = dg.id
                JOIN files f ON f.id = dgm.file_id
                WHERE f.full_path LIKE ? ESCAPE '\\' {status_clause}
                ORDER BY dg.reclaimable_bytes DESC""",
            params,
        )
        return cur.fetchall()
