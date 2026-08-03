-- Systole AI - Storage Manager
-- SQLite schema. Applied idempotently at startup by database/db.py.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS drives (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    letter          TEXT NOT NULL UNIQUE,
    volume_name     TEXT,
    filesystem      TEXT,
    drive_type      TEXT NOT NULL,          -- SSD | HDD | USB | EXTERNAL_HDD | NETWORK | MEMORY_CARD | UNKNOWN
    capacity_bytes  INTEGER NOT NULL DEFAULT 0,
    used_bytes      INTEGER NOT NULL DEFAULT 0,
    free_bytes      INTEGER NOT NULL DEFAULT 0,
    health          TEXT NOT NULL DEFAULT 'unknown',   -- ok | warning | critical | unknown
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_id        INTEGER REFERENCES drives(id) ON DELETE CASCADE,
    full_path       TEXT NOT NULL UNIQUE,
    filename        TEXT NOT NULL,
    extension       TEXT,
    folder          TEXT,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    created_time    TEXT,
    modified_time   TEXT,
    accessed_time   TEXT,
    owner           TEXT,
    permissions     TEXT,
    sha256          TEXT,
    hash_computed_at TEXT,
    is_deleted      INTEGER NOT NULL DEFAULT 0,   -- soft-deleted from disk (moved to vault)
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_scan_id    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_drive ON files(drive_id);
CREATE INDEX IF NOT EXISTS idx_files_extension ON files(extension);
CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(is_deleted);

CREATE TABLE IF NOT EXISTS duplicate_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256              TEXT NOT NULL UNIQUE,
    file_count          INTEGER NOT NULL DEFAULT 0,
    total_size_bytes    INTEGER NOT NULL DEFAULT 0,
    reclaimable_bytes   INTEGER NOT NULL DEFAULT 0,
    survivor_file_id    INTEGER REFERENCES files(id),
    detected_at         TEXT NOT NULL DEFAULT (datetime('now')),
    status              TEXT NOT NULL DEFAULT 'pending'  -- pending | reviewed | cleaned | ignored
);

CREATE TABLE IF NOT EXISTS duplicate_group_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    is_survivor     INTEGER NOT NULL DEFAULT 0,
    selection_reason TEXT,     -- e.g. "latest_modified", "preferred_folder:Documents", "shortest_path"
    UNIQUE(group_id, file_id)
);

CREATE TABLE IF NOT EXISTS cleanup_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER REFERENCES files(id),
    group_id        INTEGER REFERENCES duplicate_groups(id),
    original_path   TEXT NOT NULL,
    vault_path      TEXT,
    action          TEXT NOT NULL,      -- moved_to_vault | moved_to_recycle_bin | restored | purged
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    reason          TEXT,
    performed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    restored_at     TEXT,
    is_restorable   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS safe_vault (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cleanup_history_id INTEGER NOT NULL REFERENCES cleanup_history(id) ON DELETE CASCADE,
    vault_path      TEXT NOT NULL UNIQUE,
    original_path   TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    moved_at        TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at      TEXT,               -- retention_days after moved_at
    restored        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_type       TEXT NOT NULL,      -- full | incremental | realtime
    drive_id        INTEGER REFERENCES drives(id),
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT,
    files_scanned   INTEGER NOT NULL DEFAULT 0,
    files_hashed    INTEGER NOT NULL DEFAULT 0,
    bytes_scanned   INTEGER NOT NULL DEFAULT 0,
    duplicates_found INTEGER NOT NULL DEFAULT 0,
    errors          INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'running'  -- running | completed | failed | cancelled
);

CREATE TABLE IF NOT EXISTS statistics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at         TEXT NOT NULL DEFAULT (datetime('now')),
    total_files         INTEGER NOT NULL DEFAULT 0,
    total_bytes         INTEGER NOT NULL DEFAULT 0,
    duplicate_files     INTEGER NOT NULL DEFAULT 0,
    duplicate_bytes     INTEGER NOT NULL DEFAULT 0,
    reclaimed_bytes     INTEGER NOT NULL DEFAULT 0,
    vault_bytes         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS folder_signatures (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path         TEXT NOT NULL UNIQUE,
    signature           TEXT NOT NULL,     -- hash of sorted (relative_path, sha256) pairs of all descendant files
    file_count          INTEGER NOT NULL DEFAULT 0,
    total_size_bytes    INTEGER NOT NULL DEFAULT 0,
    computed_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_folder_signatures_signature ON folder_signatures(signature);

-- ==================================================================
-- Folder Monitor Agent: monitors exactly ONE user-selected folder at a
-- time (not the whole drive). This is deliberately a separate, simpler
-- concept from watched_folders (which supports many folders) -- it's the
-- first production agent, and correctness/reliability for a single
-- folder was prioritized over breadth.
-- ==================================================================

CREATE TABLE IF NOT EXISTS monitored_folder (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    path                    TEXT NOT NULL UNIQUE,
    enabled                 INTEGER NOT NULL DEFAULT 1,      -- monitoring ON/OFF
    paused                  INTEGER NOT NULL DEFAULT 0,      -- explicit user pause (distinct from disabled/removed)
    scan_interval_seconds   INTEGER NOT NULL DEFAULT 120,    -- verification scan cadence, default 2 minutes
    keep_strategy           TEXT NOT NULL DEFAULT 'newest_modified',
    delete_action           TEXT NOT NULL DEFAULT 'safe_vault',   -- safe_vault | recycle_bin
    notifications_enabled   INTEGER NOT NULL DEFAULT 1,
    added_at                TEXT NOT NULL DEFAULT (datetime('now')),
    last_scan_at            TEXT,
    next_scan_at            TEXT,
    last_scan_status        TEXT NOT NULL DEFAULT 'pending',  -- pending | scanning | completed | failed
    status                  TEXT NOT NULL DEFAULT 'idle'      -- idle | monitoring | paused | error
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message     TEXT NOT NULL,
    level       TEXT NOT NULL DEFAULT 'info',   -- info | success | warning | error
    source      TEXT NOT NULL DEFAULT 'folder_monitor',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    read        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at);

-- ==================================================================
-- Version Cleanup Agent: monitors ONE user-selected folder (separate,
-- independent selection from Folder Monitor Agent's monitored_folder --
-- these are two different features that may point at the same or
-- different folders) and groups files/folders by NAME-PATTERN version
-- (e.g. "Project", "Project (1)", "Project_v2", "Copy of Project") --
-- unlike duplicate detection elsewhere, which groups ONLY by SHA-256
-- content hash. Here the filename pattern IS the signal; content may
-- genuinely differ between versions (that's the whole point).
-- ==================================================================

CREATE TABLE IF NOT EXISTS version_cleanup_folder (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    path                    TEXT NOT NULL UNIQUE,
    enabled                 INTEGER NOT NULL DEFAULT 1,
    paused                  INTEGER NOT NULL DEFAULT 0,
    scan_interval_seconds   INTEGER NOT NULL DEFAULT 120,
    automatic_cleanup       INTEGER NOT NULL DEFAULT 1,
    move_to_safe_vault      INTEGER NOT NULL DEFAULT 1,
    notifications_enabled   INTEGER NOT NULL DEFAULT 1,
    added_at                TEXT NOT NULL DEFAULT (datetime('now')),
    last_scan_at            TEXT,
    next_scan_at            TEXT,
    last_scan_status        TEXT NOT NULL DEFAULT 'pending',
    status                  TEXT NOT NULL DEFAULT 'idle'
);

CREATE TABLE IF NOT EXISTS version_groups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    base_name           TEXT NOT NULL,       -- normalized project/base name shared by all versions
    member_count        INTEGER NOT NULL DEFAULT 0,
    kept_member_path    TEXT,                -- NULL while status='needs_confirmation'
    storage_saved_bytes INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending | cleaned | needs_confirmation | ignored
    decision_reason     TEXT,
    detected_at         TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_version_groups_base_name ON version_groups(base_name);
CREATE INDEX IF NOT EXISTS idx_version_groups_status ON version_groups(status);

CREATE TABLE IF NOT EXISTS version_group_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL REFERENCES version_groups(id) ON DELETE CASCADE,
    full_path       TEXT NOT NULL,
    is_folder       INTEGER NOT NULL DEFAULT 0,
    version_label   TEXT,                -- e.g. "(7)", "_v2", "Copy of", "" for the bare base name
    version_number  INTEGER,             -- NULL if not numerically parseable
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    modified_time   TEXT,
    created_time    TEXT,
    is_kept         INTEGER NOT NULL DEFAULT 0,
    move_status     TEXT NOT NULL DEFAULT 'pending',   -- pending | moved | skipped | failed
    UNIQUE(group_id, full_path)
);

CREATE TABLE IF NOT EXISTS watched_folders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,
    label           TEXT,
    drive_id        INTEGER REFERENCES drives(id) ON DELETE SET NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,     -- realtime-monitored while enabled
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    last_scanned_at TEXT,
    last_scan_status TEXT   -- pending | scanning | completed | failed
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
