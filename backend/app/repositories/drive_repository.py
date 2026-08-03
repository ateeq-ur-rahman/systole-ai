from __future__ import annotations

import sqlite3
from typing import Optional

from app.database.models import Drive


class DriveRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def upsert(self, drive: Drive) -> int:
        cur = self._conn.execute(
            "SELECT id FROM drives WHERE letter = ?", (drive.letter,)
        )
        row = cur.fetchone()
        if row:
            self._conn.execute(
                """UPDATE drives SET volume_name=?, filesystem=?, drive_type=?,
                   capacity_bytes=?, used_bytes=?, free_bytes=?, health=?,
                   last_seen_at=datetime('now') WHERE id=?""",
                (drive.volume_name, drive.filesystem, drive.drive_type,
                 drive.capacity_bytes, drive.used_bytes, drive.free_bytes,
                 drive.health, row["id"]),
            )
            return row["id"]

        cur = self._conn.execute(
            """INSERT INTO drives (letter, volume_name, filesystem, drive_type,
               capacity_bytes, used_bytes, free_bytes, health)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (drive.letter, drive.volume_name, drive.filesystem, drive.drive_type,
             drive.capacity_bytes, drive.used_bytes, drive.free_bytes, drive.health),
        )
        return cur.lastrowid

    def get_by_letter(self, letter: str) -> Optional[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM drives WHERE letter = ?", (letter,))
        return cur.fetchone()

    def list_all(self) -> list[sqlite3.Row]:
        cur = self._conn.execute("SELECT * FROM drives ORDER BY letter")
        return cur.fetchall()
