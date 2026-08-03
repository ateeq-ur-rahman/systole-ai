from __future__ import annotations

import sqlite3

from app.database.models import Notification


class NotificationRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, notification: Notification) -> int:
        cur = self._conn.execute(
            "INSERT INTO notifications (message, level, source) VALUES (?, ?, ?)",
            (notification.message, notification.level, notification.source),
        )
        return cur.lastrowid

    def list_recent(self, limit: int = 50) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM notifications ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def unread_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) as cnt FROM notifications WHERE read = 0")
        return cur.fetchone()["cnt"]

    def mark_read(self, notification_id: int) -> None:
        self._conn.execute("UPDATE notifications SET read=1 WHERE id=?", (notification_id,))

    def mark_all_read(self) -> None:
        self._conn.execute("UPDATE notifications SET read=1 WHERE read=0")
