# Architecture

Systole AI - Storage Manager is the first agent of the Systole AI Operating
System for Windows. This document describes how it's structured, and the
extension points future agents (RAM Manager, CPU Manager, Battery Manager,
Driver Manager, Network Manager, Security Manager...) will plug into.

## Layered design

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (React + TypeScript + Tauri)                   │
│  Dashboard, Duplicate review, Safe Vault, Settings        │
└───────────────────────┬─────────────────────────────────┘
                         │ HTTP (localhost only)
┌───────────────────────▼─────────────────────────────────┐
│  API layer (FastAPI)                                      │
│  app/api/routes/*.py — thin, translates HTTP <-> services  │
└───────────────────────┬─────────────────────────────────┘
┌───────────────────────▼─────────────────────────────────┐
│  Services (orchestration)                                 │
│  ScanService, CleanupService, StatisticsService            │
│  Coordinates multiple agents into one user-facing action   │
└───────────────────────┬─────────────────────────────────┘
┌───────────────────────▼─────────────────────────────────┐
│  Agents (business logic, the "AI" in AI Storage Manager)  │
│  DriveDiscovery · FileScanner · HashEngine ·                │
│  DuplicateDetection · VersionIntelligence · StorageOptimizer │
│  SafeCleanup · AIExplanation · RealtimeMonitor · Scheduler   │
└───────────────────────┬─────────────────────────────────┘
┌───────────────────────▼─────────────────────────────────┐
│  Repositories (data access)                                │
│  DriveRepository · FileRepository · DuplicateRepository ·   │
│  VaultRepository                                            │
└───────────────────────┬─────────────────────────────────┘
┌───────────────────────▼─────────────────────────────────┐
│  SQLite (app/database/schema.sql)                          │
└─────────────────────────────────────────────────────────┘
```

Each layer only talks to the layer directly below it. Agents never touch
SQL directly — they call repositories. The API layer never touches
repositories directly — it calls services. This keeps every layer
independently testable and replaceable, per the "every module must be
replaceable independently" requirement.

## The most important rule, enforced in code

Duplicate detection is decided **exclusively** by SHA-256 content hash.
This isn't just a docstring promise — it's structurally enforced:

- `HashEngine` is the only thing that ever sets `files.sha256`.
- `DuplicateDetectionAgent.detect()` queries `files` grouped by `sha256`
  (`file_repository.find_by_hashes_with_counts`) — filename, timestamp,
  and folder never appear in that query.
- `VersionIntelligenceAgent` is only ever called with a list of files
  **already confirmed identical**. It decides which one survives; it
  never decides whether they're duplicates in the first place.

See `tests/test_duplicate_detection.py::test_same_filename_different_hash_is_never_grouped`
for the regression test that pins this down.

## Safety architecture

Three independent layers stand between any agent and permanent data loss:

1. **PathGuard** (`app/utils/path_guard.py`) — the single gatekeeper every
   file read/write passes through. `is_scannable()` blocks protected
   system directories/files/extensions before a file is even opened.
   `is_modifiable()` adds locked-file and never-delete-extension checks
   on top, and is the only check `SafeCleanupAgent` trusts before moving
   anything.
2. **Move, never delete** (`app/utils/safe_vault.py`) — `SafeCleanupAgent`
   never calls `os.remove()` on a user file. Redundant copies are moved
   to Systole's Safe Vault (or the Windows Recycle Bin), and every move
   is recorded in `cleanup_history` / `safe_vault` so it can be reversed.
3. **Audit trail + restore** — `restore()`, `restore_all()`, and
   `purge_expired()` in `SafeCleanupAgent` are the only code paths that
   read `cleanup_history`; `purge_expired()` is the *only* code path in
   the entire system permitted to permanently delete a file, and it only
   ever acts on files already inside Systole's own vault directory that
   have passed their retention window.

## Extending with future agents

The `Container` (`app/container.py`) is the intended extension point. A
future `RamManagerAgent` would:

1. Add its own repository (if it needs new tables) under
   `app/repositories/`, and its schema under `database/schema.sql`.
2. Add its agent class under `app/agents/`.
3. Add a `ram_manager: RamManagerAgent` field + factory line to
   `Container` / `build_container()`.
4. Add its own route module under `app/api/routes/`, following the same
   `Depends(get_container)` pattern used by every existing route.

No existing agent, repository, or route needs to change for this to work
— that's the "must work independently... future agents can plug in
without changing the Storage Manager's core architecture" requirement in
concrete terms.

## Performance posture

- **Incremental by default.** `FileRepository.get_cached_hash()` skips
  re-hashing any file whose `(path, mtime, size)` hasn't changed —
  this is what makes scanning millions of files on a schedule feasible.
- **Parallel hashing, sequential metadata.** `FileScannerAgent` writes
  cheap filesystem metadata for a batch first, then hashes that batch
  across a thread pool (`ThreadPoolExecutor`), sized by
  `performance.max_worker_threads`.
- **Directory pruning, not post-filtering.** `os.walk`'s `dirnames` list
  is mutated in place so protected directories are never even descended
  into — see `FileScannerAgent.scan_path`.
- **Pause conditions.** `RealtimeMonitorAgent.should_pause()` checks
  battery-saver and fullscreen-app (gaming proxy) state before triggering
  a rescan from a filesystem event.
