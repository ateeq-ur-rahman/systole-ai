from __future__ import annotations

import sqlite3
from typing import Optional


class VaultRepository:
    """Persists cleanup_history and safe_vault rows -- the audit trail that
    makes Undo / Restore / Rollback possible."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def record_cleanup(self, file_id: Optional[int], group_id: Optional[int],
                        original_path: str, vault_path: Optional[str],
                        action: str, size_bytes: int, reason: str) -> int:
        cur = self._conn.execute(
            """INSERT INTO cleanup_history
               (file_id, group_id, original_path, vault_path, action, size_bytes, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_id, group_id, original_path, vault_path, action, size_bytes, reason),
        )
        return cur.lastrowid

    def record_vault_entry(self, cleanup_history_id: int, vault_path: str,
                            original_path: str, size_bytes: int, retention_days: int) -> int:
        cur = self._conn.execute(
            """INSERT INTO safe_vault
               (cleanup_history_id, vault_path, original_path, size_bytes, expires_at)
               VALUES (?, ?, ?, ?, datetime('now', ?))""",
            (cleanup_history_id, vault_path, original_path, size_bytes, f"+{retention_days} days"),
        )
        return cur.lastrowid

    def mark_restored(self, cleanup_history_id: int) -> None:
        self._conn.execute(
            "UPDATE cleanup_history SET restored_at=datetime('now') WHERE id=?",
            (cleanup_history_id,),
        )
        self._conn.execute(
            "UPDATE safe_vault SET restored=1 WHERE cleanup_history_id=?",
            (cleanup_history_id,),
        )

    def get_history(self, limit: int = 100) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM cleanup_history ORDER BY performed_at DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def get_cleanup_by_id(self, cleanup_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM cleanup_history WHERE id=?", (cleanup_id,))
        return cur.fetchone()

    def get_vault_entry_by_cleanup_id(self, cleanup_id: int) -> Optional[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM safe_vault WHERE cleanup_history_id=?", (cleanup_id,)
        )
        return cur.fetchone()

    def list_vault(self, include_restored: bool = False) -> list[sqlite3.Row]:
        if include_restored:
            cur = self._conn.execute("SELECT * FROM safe_vault ORDER BY moved_at DESC")
        else:
            cur = self._conn.execute(
                "SELECT * FROM safe_vault WHERE restored=0 ORDER BY moved_at DESC"
            )
        return cur.fetchall()

    def expired_entries(self) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM safe_vault WHERE restored=0 AND expires_at < datetime('now')"
        )
        return cur.fetchall()

    def entries_expiring_within(self, minutes: int) -> list[sqlite3.Row]:
        """Vault entries not yet expired, not yet restored, not yet warned
        about, whose expires_at falls within the next `minutes` -- the
        candidates for a 'this will be permanently deleted soon' notice."""
        cur = self._conn.execute(
            """SELECT * FROM safe_vault
               WHERE restored = 0
                 AND warning_sent_at IS NULL
                 AND expires_at > datetime('now')
                 AND expires_at <= datetime('now', ?)""",
            (f"+{minutes} minutes",),
        )
        return cur.fetchall()

    def mark_warning_sent(self, vault_entry_id: int) -> None:
        self._conn.execute(
            "UPDATE safe_vault SET warning_sent_at=datetime('now') WHERE id=?",
            (vault_entry_id,),
        )

    def vault_total_bytes(self) -> int:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(size_bytes),0) as total FROM safe_vault WHERE restored=0"
        )
        return cur.fetchone()["total"]

    def list_vault_under_path(self, path_prefix: str, include_restored: bool = False) -> list[sqlite3.Row]:
        from app.repositories.file_repository import FileRepository
        like_pattern = FileRepository._like_prefix(path_prefix)
        restored_clause = "" if include_restored else "AND restored = 0"
        cur = self._conn.execute(
            f"""SELECT * FROM safe_vault
                WHERE original_path LIKE ? ESCAPE '\\' {restored_clause}
                ORDER BY moved_at DESC""",
            (like_pattern,),
        )
        return cur.fetchall()

    def search_vault(self, query: str = "", from_date: Optional[str] = None,
                      to_date: Optional[str] = None, include_restored: bool = True) -> list[sqlite3.Row]:
        """Powers Safe Vault search/filter -- by filename/path substring
        and/or a moved_at date range."""
        clauses = []
        params: list = []
        if query:
            clauses.append("(original_path LIKE ? ESCAPE '\\')")
            params.append(f"%{query}%")
        if from_date:
            clauses.append("moved_at >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("moved_at <= ?")
            params.append(to_date)
        if not include_restored:
            clauses.append("restored = 0")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(f"SELECT * FROM safe_vault {where} ORDER BY moved_at DESC", params)
        return cur.fetchall()
