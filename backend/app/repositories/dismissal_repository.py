"""
Dismissal Repository

Backs the AI's memory of which recommendation categories a user has
explicitly said "not now" or "never" to. This is genuine persisted
behavioral memory -- not a UI-only hide, not lost on restart -- directly
answering the "does the app remember frequently skipped recommendations"
gap identified in the architecture review.

A dismissal can be permanent (expires_at is NULL) or a snooze (expires_at
set to a future timestamp) -- re-surfacing automatically once it passes,
since a recommendation that was irrelevant last month may be exactly
right this month (e.g. the user's Downloads folder filled back up with
installers again).
"""
from __future__ import annotations

import sqlite3
from typing import Optional


class DismissalRepository:
    def __init__(self, conn):
        self._conn = conn

    def dismiss(self, category: str, snooze_days: Optional[int] = None) -> None:
        existing = self._conn.execute(
            "SELECT id, times_dismissed FROM dismissed_recommendations WHERE category=?",
            (category,),
        ).fetchone()

        expires_clause = f"datetime('now', '+{snooze_days} days')" if snooze_days else "NULL"

        if existing:
            self._conn.execute(
                f"""UPDATE dismissed_recommendations
                    SET dismissed_at=datetime('now'), expires_at={expires_clause},
                        times_dismissed=times_dismissed+1
                    WHERE id=?""",
                (existing["id"],),
            )
        else:
            self._conn.execute(
                f"""INSERT INTO dismissed_recommendations (category, expires_at)
                    VALUES (?, {expires_clause})""",
                (category,),
            )
        self._conn.commit()

    def undismiss(self, category: str) -> None:
        """Lets a user explicitly bring back a category they'd previously
        dismissed, if they change their mind -- memory should be
        correctable, not a one-way ratchet."""
        self._conn.execute("DELETE FROM dismissed_recommendations WHERE category=?", (category,))
        self._conn.commit()

    def is_dismissed(self, category: str) -> bool:
        row = self._conn.execute(
            """SELECT 1 FROM dismissed_recommendations
               WHERE category=? AND (expires_at IS NULL OR expires_at > datetime('now'))""",
            (category,),
        ).fetchone()
        return row is not None

    def list_active(self) -> list[sqlite3.Row]:
        """Active dismissals only -- expired snoozes are excluded, so a
        category that should now be re-surfacing doesn't get filtered
        out just because a stale row is still sitting in the table."""
        return self._conn.execute(
            """SELECT * FROM dismissed_recommendations
               WHERE expires_at IS NULL OR expires_at > datetime('now')
               ORDER BY dismissed_at DESC"""
        ).fetchall()
