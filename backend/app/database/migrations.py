"""
Lightweight migration runner.

schema.sql uses `CREATE TABLE IF NOT EXISTS`, which is perfect for new
installs but does nothing for columns added to a table that already
exists on someone's machine from a previous version. This module is the
other half: idempotent `ALTER TABLE ... ADD COLUMN` statements that are
safe to run on every startup, on both fresh and existing databases.

Design constraints (deliberate, not accidental):
- Every migration is additive only (new column, new index, new table).
  Nothing here ever drops or renames a column -- that would break
  backward compatibility with any existing installation's data.
- Each statement is wrapped so "duplicate column name" errors (meaning
  the migration already ran previously) are swallowed silently; any other
  OperationalError is re-raised, since that indicates a real problem.
- Migrations run in a fixed, numbered order and are safe to re-run on
  every application startup -- there is no separate "have I migrated"
  bookkeeping table, because idempotent ADD COLUMN calls don't need one.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("systole.migrations")

# (description, DDL statement) pairs, applied in order.
_MIGRATIONS: list[tuple[str, str]] = [
    ("files.inode_key for hardlink-aware duplicate accounting",
     "ALTER TABLE files ADD COLUMN inode_key TEXT"),
    ("files.is_reparse_point to record symlink/junction skips",
     "ALTER TABLE files ADD COLUMN is_reparse_point INTEGER NOT NULL DEFAULT 0"),

    ("duplicate_group_members.is_hardlink_of_survivor for accurate reclaimable-space accounting",
     "ALTER TABLE duplicate_group_members ADD COLUMN is_hardlink_of_survivor INTEGER NOT NULL DEFAULT 0"),

    ("cleanup_history.sha256 -- denormalized so Vault entries remain fully "
     "self-describing even if the source files row is later purged",
     "ALTER TABLE cleanup_history ADD COLUMN sha256 TEXT"),
    ("cleanup_history.original_drive_letter (denormalized)",
     "ALTER TABLE cleanup_history ADD COLUMN original_drive_letter TEXT"),
    ("cleanup_history.owner (denormalized)",
     "ALTER TABLE cleanup_history ADD COLUMN owner TEXT"),
    ("cleanup_history.permissions (denormalized)",
     "ALTER TABLE cleanup_history ADD COLUMN permissions TEXT"),
    ("cleanup_history.original_created_time (denormalized)",
     "ALTER TABLE cleanup_history ADD COLUMN original_created_time TEXT"),
    ("cleanup_history.original_modified_time (denormalized)",
     "ALTER TABLE cleanup_history ADD COLUMN original_modified_time TEXT"),
    ("cleanup_history.original_accessed_time (denormalized)",
     "ALTER TABLE cleanup_history ADD COLUMN original_accessed_time TEXT"),

    ("scan_history.paused_at / cancelled_at for pause/resume/cancel support",
     "ALTER TABLE scan_history ADD COLUMN paused_at TEXT"),
    ("scan_history.cancelled_at",
     "ALTER TABLE scan_history ADD COLUMN cancelled_at TEXT"),
    ("scan_history.job_id -- links a DB row to an in-memory ScanJobManager job",
     "ALTER TABLE scan_history ADD COLUMN job_id TEXT"),

    ("index on cleanup_history.performed_at for Vault search/filter by date range",
     "CREATE INDEX IF NOT EXISTS idx_cleanup_history_performed_at ON cleanup_history(performed_at)"),
    ("index on safe_vault.original_path for Vault search",
     "CREATE INDEX IF NOT EXISTS idx_safe_vault_original_path ON safe_vault(original_path)"),
    ("index on files.inode_key for fast hardlink-sibling lookups",
     "CREATE INDEX IF NOT EXISTS idx_files_inode_key ON files(inode_key)"),

    ("safe_vault.warning_sent_at -- tracks whether the pre-deletion warning "
     "notification has already fired for this entry, so it's only sent once",
     "ALTER TABLE safe_vault ADD COLUMN warning_sent_at TEXT"),

    ("tie_break_choices -- local, on-device training data for the version "
     "cleanup tie-break learner. Records every genuinely-tied group a user "
     "manually resolves, so the model can learn this user's own preferences "
     "over time. Nothing here ever leaves the device; it's just structured "
     "history of decisions already made locally.",
     """CREATE TABLE IF NOT EXISTS tie_break_choices (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        candidates_json TEXT NOT NULL,
        chosen_index    INTEGER NOT NULL,
        decided_at      TEXT NOT NULL DEFAULT (datetime('now'))
     )"""),

    ("dismissed_recommendations -- AI memory of recommendation categories "
     "the user has explicitly dismissed, so they stop resurfacing "
     "indefinitely (dismissed forever) or for a chosen snooze period. "
     "This is what makes 'you dismissed this before, I won't suggest it "
     "again' a real, persisted fact rather than an aspiration.",
     """CREATE TABLE IF NOT EXISTS dismissed_recommendations (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        category     TEXT NOT NULL,
        dismissed_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at   TEXT,
        times_dismissed INTEGER NOT NULL DEFAULT 1
     )"""),

    ("index for fast dismissal lookups by category",
     "CREATE INDEX IF NOT EXISTS idx_dismissed_recommendations_category ON dismissed_recommendations(category)"),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    for description, statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "duplicate column name" in message or "already exists" in message:
                continue  # already applied in a previous run -- expected, not an error
            logger.error("Migration failed (%s): %s", description, exc)
            raise
    conn.commit()
