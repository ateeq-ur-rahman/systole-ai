from __future__ import annotations

import os
import sqlite3
from typing import Iterable, Optional

from app.database.models import FileRecord


class FileRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(self, f: FileRecord) -> int:
        cur = self._conn.execute("SELECT id, sha256 FROM files WHERE full_path = ?", (f.full_path,))
        row = cur.fetchone()
        if row:
            self._conn.execute(
                """UPDATE files SET drive_id=?, filename=?, extension=?, folder=?,
                   size_bytes=?, created_time=?, modified_time=?, accessed_time=?,
                   owner=?, permissions=?, inode_key=?, is_deleted=0, last_seen_at=datetime('now')
                   WHERE id=?""",
                (f.drive_id, f.filename, f.extension, f.folder, f.size_bytes,
                 f.created_time, f.modified_time, f.accessed_time, f.owner,
                 f.permissions, f.inode_key, row["id"]),
            )
            return row["id"]

        cur = self._conn.execute(
            """INSERT INTO files (drive_id, full_path, filename, extension, folder,
               size_bytes, created_time, modified_time, accessed_time, owner, permissions,
               inode_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f.drive_id, f.full_path, f.filename, f.extension, f.folder, f.size_bytes,
             f.created_time, f.modified_time, f.accessed_time, f.owner, f.permissions,
             f.inode_key),
        )
        return cur.lastrowid

    def set_hash(self, file_id: int, sha256: str) -> None:
        self._conn.execute(
            "UPDATE files SET sha256=?, hash_computed_at=datetime('now') WHERE id=?",
            (sha256, file_id),
        )

    def get_cached_hash(self, full_path: str, modified_time: str, size_bytes: int) -> Optional[str]:
        """Return a cached SHA-256 only if the file's mtime/size haven't
        changed since it was last hashed -- this is the hash-cache the spec
        requires ('never hash unchanged files twice')."""
        cur = self._conn.execute(
            """SELECT sha256 FROM files
               WHERE full_path=? AND modified_time=? AND size_bytes=? AND sha256 IS NOT NULL""",
            (full_path, modified_time, size_bytes),
        )
        row = cur.fetchone()
        return row["sha256"] if row else None

    def get_by_path(self, full_path: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM files WHERE full_path = ?", (full_path,))
        return cur.fetchone()

    def get_by_id(self, file_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM files WHERE id = ?", (file_id,))
        return cur.fetchone()

    def find_by_hashes_with_counts(self, min_size_bytes: int = 0, path_prefix: str | None = None) -> list[sqlite3.Row]:
        """Return sha256 values that appear on more than one non-deleted file.
        With `path_prefix`, only considers files under that folder -- this is
        what keeps the Folder Monitor Agent scoped to exactly one folder
        rather than surfacing duplicates against the rest of the system."""
        if path_prefix:
            cur = self._conn.execute(
                """SELECT sha256, COUNT(*) as cnt, SUM(size_bytes) as total_size
                   FROM files
                   WHERE sha256 IS NOT NULL AND is_deleted = 0 AND size_bytes >= ?
                     AND full_path LIKE ? ESCAPE '\\'
                   GROUP BY sha256
                   HAVING COUNT(*) > 1""",
                (min_size_bytes, self._like_prefix(path_prefix)),
            )
        else:
            cur = self._conn.execute(
                """SELECT sha256, COUNT(*) as cnt, SUM(size_bytes) as total_size
                   FROM files
                   WHERE sha256 IS NOT NULL AND is_deleted = 0 AND size_bytes >= ?
                   GROUP BY sha256
                   HAVING COUNT(*) > 1"""
                , (min_size_bytes,),
            )
        return cur.fetchall()

    def find_by_hash(self, sha256: str, path_prefix: str | None = None) -> list[sqlite3.Row]:
        if path_prefix:
            cur = self._conn.execute(
                "SELECT * FROM files WHERE sha256 = ? AND is_deleted = 0 AND full_path LIKE ? ESCAPE '\\'",
                (sha256, self._like_prefix(path_prefix)),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM files WHERE sha256 = ? AND is_deleted = 0", (sha256,)
            )
        return cur.fetchall()

    @staticmethod
    def _like_prefix(path_prefix: str) -> str:
        """Builds a SQL LIKE pattern that matches any path under
        `path_prefix`, escaping LIKE's special characters (%, _) so a
        folder name containing them doesn't act as a wildcard. Detects
        which path separator `path_prefix` actually uses (backslash for
        Windows-style paths, forward slash for POSIX paths used in tests
        that touch a real filesystem) rather than assuming one -- both
        occur in this codebase depending on context."""
        if "\\" in path_prefix:
            separator, separator_in_pattern = "\\", "\\\\"  # doubled: LIKE's escape char
        elif "/" in path_prefix:
            separator, separator_in_pattern = "/", "/"
        else:
            separator, separator_in_pattern = os.sep, ("\\\\" if os.sep == "\\" else os.sep)

        escaped = path_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if not escaped.endswith(separator_in_pattern):
            escaped += separator_in_pattern
        return escaped + "%"

    def delete_missing_under_path(self, scan_started_at: str, path_prefix: str) -> int:
        """Folder-scoped counterpart to delete_missing_before() -- marks
        files as deleted if they weren't seen in the current scan AND live
        under the given folder, without requiring a drive_id (the Folder
        Monitor Agent scans a folder directly, not a whole drive)."""
        cur = self._conn.execute(
            """UPDATE files SET is_deleted=1
               WHERE last_seen_at < ? AND is_deleted=0 AND full_path LIKE ? ESCAPE '\\'""",
            (scan_started_at, self._like_prefix(path_prefix)),
        )
        return cur.rowcount

    def count_active_under_path(self, path_prefix: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM files WHERE is_deleted=0 AND full_path LIKE ? ESCAPE '\\'",
            (self._like_prefix(path_prefix),),
        )
        return cur.fetchone()["cnt"]

    def mark_deleted(self, file_id: int) -> None:
        self._conn.execute("UPDATE files SET is_deleted=1 WHERE id=?", (file_id,))

    def mark_restored(self, file_id: int, new_path: str) -> None:
        self._conn.execute(
            "UPDATE files SET is_deleted=0, full_path=? WHERE id=?", (new_path, file_id)
        )

    def delete_missing_before(self, scan_started_at: str, drive_id: int) -> int:
        """Files not seen in the current scan are presumed removed from disk."""
        cur = self._conn.execute(
            "UPDATE files SET is_deleted=1 WHERE drive_id=? AND last_seen_at < ? AND is_deleted=0",
            (drive_id, scan_started_at),
        )
        return cur.rowcount

    def totals(self) -> sqlite3.Row:
        cur = self._conn.execute(
            "SELECT COUNT(*) as total_files, COALESCE(SUM(size_bytes),0) as total_bytes "
            "FROM files WHERE is_deleted = 0"
        )
        return cur.fetchone()

    def largest_files(self, limit: int = 25) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM files WHERE is_deleted=0 ORDER BY size_bytes DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def by_extension_group(self, extensions: Iterable[str]) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in extensions)
        cur = self._conn.execute(
            f"SELECT * FROM files WHERE is_deleted=0 AND extension IN ({placeholders})",
            tuple(extensions),
        )
        return cur.fetchall()
