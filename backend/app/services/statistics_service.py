from __future__ import annotations

from app.container import Container


class StatisticsService:
    def __init__(self, container: Container):
        self._c = container

    def snapshot(self) -> dict:
        totals = self._c.file_repo.totals()
        dup_bytes = self._c.dup_repo.total_reclaimable()
        vault_bytes = self._c.vault_repo.vault_total_bytes()
        drives = self._c.drive_repo.list_all()

        return {
            "total_files": totals["total_files"],
            "total_bytes": totals["total_bytes"],
            "duplicate_reclaimable_bytes": dup_bytes,
            "vault_bytes": vault_bytes,
            "drives": [dict(d) for d in drives],
        }

    def record_snapshot(self) -> None:
        totals = self._c.file_repo.totals()
        dup_bytes = self._c.dup_repo.total_reclaimable()
        vault_bytes = self._c.vault_repo.vault_total_bytes()
        self._c.conn.execute(
            """INSERT INTO statistics
               (total_files, total_bytes, duplicate_files, duplicate_bytes, vault_bytes)
               VALUES (?, ?, ?, ?, ?)""",
            (totals["total_files"], totals["total_bytes"], 0, dup_bytes, vault_bytes),
        )
        self._c.conn.commit()
