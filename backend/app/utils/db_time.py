"""
Timestamp utility for values that will be string-compared against columns
populated by SQLite's own `datetime('now')` default (e.g. `last_seen_at`,
`performed_at`).

SQLite's `datetime('now')` produces `'YYYY-MM-DD HH:MM:SS'` -- a space
separator, no fractional seconds, no timezone suffix. Python's
`datetime.now(timezone.utc).isoformat()` produces `'YYYY-MM-DDTHH:MM:SS.ffffff+00:00'`
-- a 'T' separator, microseconds, and an explicit offset. These two
formats sort *differently* under plain string comparison: ASCII ' '
(0x20) sorts before 'T' (0x54), so a SQLite-stamped row's timestamp will
almost always compare as "less than" an isoformat Python timestamp
representing a moment *before* it -- entirely due to the character
mismatch, not the actual chronological order.

Concretely, this bug silently marked every freshly-scanned file as
"deleted" immediately after a scan completed: `delete_missing_before()`
compared each row's SQLite-stamped `last_seen_at` against a Python
isoformat `started_at`, and the format mismatch made `last_seen_at <
started_at` evaluate true for every row, regardless of real timing.

Fix: always generate comparison timestamps with `sqlite_utc_now()` below
instead of `datetime.now(timezone.utc).isoformat()` wherever the value
will be compared (via `<`, `>`, `BETWEEN`, etc.) against a SQLite
`datetime('now')`-populated column.
"""
from __future__ import annotations

from datetime import datetime, timezone


def sqlite_utc_now() -> str:
    """Current UTC time formatted identically to SQLite's `datetime('now')`,
    safe to compare directly against columns that use that as their
    default."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
