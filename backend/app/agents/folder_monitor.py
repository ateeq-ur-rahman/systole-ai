"""
Folder Monitor Agent

The first production-ready agent built on top of the general Storage
Manager machinery. Deliberately narrow in scope: it manages exactly ONE
user-selected folder at a time -- never a whole drive, never Windows
system directories -- and keeps it continuously free of exact duplicate
files.

It's built entirely out of existing agents/services (FileScannerAgent,
DuplicateDetectionAgent, SafeCleanupAgent) rather than reimplementing
scanning or cleanup logic. This module's own responsibility is narrow:
own the "one active folder" lifecycle, scope every operation to that
folder's path, auto-clean what it finds (unlike the general Storage
Manager, which defaults to manual review), and narrate what happened via
notifications.

Workflow per cycle (initial scan or the periodic 2-minute verification
scan alike):
  1. Scan the folder (metadata + SHA-256, incremental via the existing
     hash cache -- unchanged files are never re-hashed).
  2. Mark files no longer present as deleted (folder-scoped).
  3. Run duplicate detection scoped to this folder's path prefix only.
  4. Auto-clean every pending group found: survivor (newest modified, per
     Version Intelligence) is kept, every other copy moves to the Safe
     Vault.
  5. Emit notifications narrating what happened.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.agents.duplicate_detection import DuplicateDetectionAgent
from app.agents.file_scanner import FileScannerAgent
from app.agents.safe_cleanup import SafeCleanupAgent
from app.database.models import MonitoredFolder, Notification
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.monitored_folder_repository import MonitoredFolderRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.vault_repository import VaultRepository
from app.utils.db_time import sqlite_utc_now
from app.utils.formatting import human_bytes
from app.utils.path_guard import PathGuard

logger = logging.getLogger("systole.folder_monitor")


@dataclass
class CycleResult:
    files_scanned: int
    files_hashed: int
    duplicate_groups_found: int
    files_moved_to_vault: int
    bytes_reclaimed: int
    errors: int


class FolderMonitorError(ValueError):
    """Raised for user-facing validation failures (bad path, protected
    location, etc.) -- callers (API routes) translate this into a 400."""


class FolderMonitorAgent:
    def __init__(self, conn, folder_repo: MonitoredFolderRepository, file_repo: FileRepository,
                 dup_repo: DuplicateRepository, vault_repo: VaultRepository,
                 notification_repo: NotificationRepository, guard: PathGuard,
                 file_scanner: FileScannerAgent, duplicate_detection: DuplicateDetectionAgent,
                 safe_cleanup: SafeCleanupAgent):
        self._conn = conn
        self._folder_repo = folder_repo
        self._file_repo = file_repo
        self._dup_repo = dup_repo
        self._vault_repo = vault_repo
        self._notify_repo = notification_repo
        self._guard = guard
        self._file_scanner = file_scanner
        self._duplicate_detection = duplicate_detection
        self._safe_cleanup = safe_cleanup

    # -- lifecycle -----------------------------------------------------

    def set_folder(self, path: str, scan_interval_seconds: int = 120) -> dict:
        """Selects a new folder to monitor, replacing whatever was
        previously active. Validates the path exists, is a directory, and
        isn't a protected system location, then runs the initial scan
        immediately so the dashboard has real numbers right away."""
        normalized = os.path.normpath(path)

        if not os.path.isdir(normalized):
            raise FolderMonitorError(f"'{normalized}' is not an accessible folder")

        check = self._guard.is_scannable(normalized)
        if not check.allowed:
            raise FolderMonitorError(
                f"'{normalized}' can't be monitored: {check.reason}. Systole never monitors "
                f"Windows system directories, even on explicit request."
            )

        try:
            self._folder_repo.set_folder(MonitoredFolder(
                id=None, path=normalized, scan_interval_seconds=scan_interval_seconds,
            ))
            self._notify("info", f"Monitoring {normalized}...")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        # run_cycle() manages its own commit/rollback around the scan
        # itself, so a scan failure here doesn't roll back the folder
        # selection we just committed above.
        self.run_cycle(is_initial=True)
        return self.get_status()

    def remove(self) -> None:
        try:
            active = self._folder_repo.get_active()
            if active:
                self._notify("info", f"Stopped monitoring {active['path']}.")
            self._folder_repo.clear()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def pause(self) -> dict:
        try:
            active = self._require_active()
            self._folder_repo.set_paused(active["id"], True)
            self._notify("info", "Monitoring paused.")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get_status()

    def resume(self) -> dict:
        try:
            active = self._require_active()
            self._folder_repo.set_paused(active["id"], False)
            self._notify("info", "Monitoring resumed.")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get_status()

    # -- the core cycle --------------------------------------------------

    def run_cycle(self, is_initial: bool = False) -> CycleResult:
        """Owns its own transaction boundary end-to-end: every write made
        during a cycle (scan results, duplicate detection, cleanup moves,
        notifications, status updates) either all commit together on
        success, or all roll back together on any failure -- including
        failures inside the ThreadPoolExecutor-parallelized hashing.
        Critically, this method NEVER re-raises without first either
        committing or rolling back: an exception that unwinds past this
        function with the transaction still open is exactly what leaves a
        write lock dangling and blocks every other thread's connection
        with 'database is locked', even ones with nothing to do with the
        original failure."""
        active = self._require_active()
        folder_id = active["id"]
        folder_path = active["path"]

        if active["paused"] and not is_initial:
            logger.debug("Skipping cycle for %s: monitoring is paused", folder_path)
            return CycleResult(0, 0, 0, 0, 0, 0)

        started_at = sqlite_utc_now()

        try:
            self._folder_repo.mark_scan_started(folder_id)
            self._conn.commit()  # visible immediately, even if the scan below takes a while
        except Exception:
            self._conn.rollback()
            raise

        try:
            stats = self._file_scanner.scan_path(folder_path, drive_id=None, compute_hashes=True)
            self._file_repo.delete_missing_under_path(started_at, folder_path)

            groups = self._duplicate_detection.detect(path_prefix=folder_path)

            moved_count = 0
            bytes_reclaimed = 0
            if groups:
                outcome = self._safe_cleanup.clean_groups([g.id for g in groups])
                moved_count = len(outcome.moved)
                bytes_reclaimed = outcome.bytes_reclaimed

            next_scan = self._compute_next_scan(active["scan_interval_seconds"])
            self._folder_repo.mark_scan_finished(folder_id, "completed", next_scan)
            self._emit_cycle_notifications(len(groups), moved_count, bytes_reclaimed)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            try:
                next_scan = self._compute_next_scan(active["scan_interval_seconds"])
                self._folder_repo.mark_scan_finished(folder_id, "failed", next_scan)
                self._notify("error", f"Scan of {folder_path} failed -- see logs for details.")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                logger.exception("Failed to even record the scan failure for %s", folder_path)
            logger.exception("Folder Monitor scan failed for %s", folder_path)
            raise

        logger.info(
            "Folder Monitor cycle complete for %s: %d files scanned, %d duplicate group(s), "
            "%d moved, %s reclaimed",
            folder_path, stats.files_scanned, len(groups), moved_count, human_bytes(bytes_reclaimed),
        )

        return CycleResult(
            files_scanned=stats.files_scanned, files_hashed=stats.files_hashed,
            duplicate_groups_found=len(groups), files_moved_to_vault=moved_count,
            bytes_reclaimed=bytes_reclaimed, errors=stats.errors,
        )

    def _emit_cycle_notifications(self, groups_found: int, moved_count: int, bytes_reclaimed: int) -> None:
        if groups_found == 0:
            self._notify("info", "No duplicates found.")
            return

        self._notify("warning", f"{groups_found} duplicate file group{'s' if groups_found != 1 else ''} detected.")
        if moved_count > 0:
            self._notify("success", f"{moved_count} file{'s' if moved_count != 1 else ''} moved to Safe Vault.")
        if bytes_reclaimed > 0:
            self._notify("success", f"Recovered {human_bytes(bytes_reclaimed)}.")

    # -- status / dashboard ------------------------------------------------

    def get_status(self) -> dict:
        active = self._folder_repo.get_active()
        if not active:
            return {"active": False}

        folder_path = active["path"]
        total_files = self._file_repo.count_active_under_path(folder_path)
        duplicate_groups = self._dup_repo.groups_under_path(folder_path, status="pending")
        duplicate_files = sum(max(g["file_count"] - 1, 0) for g in duplicate_groups)
        reclaimable_bytes = sum(g["reclaimable_bytes"] for g in duplicate_groups)
        vault_entries = self._vault_repo.list_vault_under_path(folder_path)
        recovered_bytes = sum(
            g["reclaimable_bytes"] for g in self._dup_repo.groups_under_path(folder_path, status="cleaned")
        )

        return {
            "active": True,
            "id": active["id"],
            "path": folder_path,
            "enabled": bool(active["enabled"]),
            "paused": bool(active["paused"]),
            "status": active["status"],
            "scan_interval_seconds": active["scan_interval_seconds"],
            "notifications_enabled": bool(active["notifications_enabled"]),
            "last_scan_at": active["last_scan_at"],
            "next_scan_at": active["next_scan_at"],
            "last_scan_status": active["last_scan_status"],
            "total_files": total_files,
            "duplicate_groups": len(duplicate_groups),
            "duplicate_files": duplicate_files,
            "reclaimable_bytes": reclaimable_bytes,
            "recovered_bytes": recovered_bytes,
            "vault_entries": len(vault_entries),
            "vault_bytes": sum(v["size_bytes"] for v in vault_entries),
        }

    # -- internals -----------------------------------------------------

    def _require_active(self):
        active = self._folder_repo.get_active()
        if not active:
            raise FolderMonitorError("No folder is currently being monitored")
        return active

    def _notify(self, level: str, message: str) -> None:
        active = self._folder_repo.get_active()
        if active and not active["notifications_enabled"]:
            return
        self._notify_repo.add(Notification(id=None, message=message, level=level))

    @staticmethod
    def _compute_next_scan(interval_seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).strftime("%Y-%m-%d %H:%M:%S")
