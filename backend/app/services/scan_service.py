"""
ScanService

Orchestrates a full end-to-end scan cycle: discover drives -> scan files ->
detect duplicates -> record scan_history. This is what the API's
POST /scan endpoint and the Scheduler's full/incremental jobs both call --
keeping the orchestration logic in one place instead of duplicated between
the API layer and the background scheduler.
"""
from __future__ import annotations

import logging
import sqlite3

from app.container import Container
from app.database.models import Drive
from app.utils.db_time import sqlite_utc_now

logger = logging.getLogger("systole.scan_service")


class ScanService:
    def __init__(self, container: Container):
        self._c = container

    def run_full_scan(self) -> dict:
        return self._run_scan(scan_type="full", compute_hashes=True)

    def run_incremental_scan(self) -> dict:
        return self._run_scan(scan_type="incremental", compute_hashes=True)

    def scan_single_drive(self, letter: str) -> dict:
        return self._run_scan(scan_type="incremental", compute_hashes=True, only_letter=letter)

    def scan_folder(self, folder_id: int) -> dict:
        """Scan a single user-added watched folder (see /folders), then run
        duplicate detection across the whole database (duplicates can span
        multiple watched folders/drives, so detection always looks at
        everything scanned so far, not just this one folder)."""
        folder = self._c.folder_repo.get_by_id(folder_id)
        if not folder:
            raise ValueError(f"No watched folder with id={folder_id}")

        conn: sqlite3.Connection = self._c.conn
        started_at = sqlite_utc_now()

        self._c.folder_repo.mark_scan_started(folder_id)
        conn.commit()

        cur = conn.execute(
            "INSERT INTO scan_history (scan_type, drive_id, started_at, status) "
            "VALUES ('folder', ?, ?, 'running')",
            (folder["drive_id"], started_at),
        )
        scan_history_id = cur.lastrowid
        conn.commit()

        try:
            stats = self._c.file_scanner.scan_path(folder["path"], folder["drive_id"], compute_hashes=True)

            conn.execute(
                """UPDATE scan_history SET finished_at=datetime('now'), files_scanned=?,
                   files_hashed=?, bytes_scanned=?, errors=?, status='completed' WHERE id=?""",
                (stats.files_scanned, stats.files_hashed, stats.bytes_scanned,
                 stats.errors, scan_history_id),
            )
            self._c.folder_repo.mark_scan_finished(folder_id, "completed")
            conn.commit()
        except Exception:
            # Roll back whatever partial work happened before the failure
            # first -- committing on top of an aborted transaction can
            # otherwise mix partial scan state with the failure marker,
            # or fail outright if the exception left the connection in an
            # inconsistent state.
            conn.rollback()
            try:
                conn.execute(
                    "UPDATE scan_history SET finished_at=datetime('now'), status='failed' WHERE id=?",
                    (scan_history_id,),
                )
                self._c.folder_repo.mark_scan_finished(folder_id, "failed")
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("Failed to even record the scan failure for folder %s", folder["path"])
            logger.exception("Scan failed for watched folder %s", folder["path"])
            raise

        groups = self._c.duplicate_detection.detect()
        conn.commit()

        return {
            "folder": folder["path"],
            "files_scanned": stats.files_scanned,
            "files_hashed": stats.files_hashed,
            "bytes_scanned": stats.bytes_scanned,
            "errors": stats.errors,
            "duplicates_found": len(groups),
        }

    def _run_scan(self, scan_type: str, compute_hashes: bool, only_letter: str | None = None) -> dict:
        started_at = sqlite_utc_now()
        conn: sqlite3.Connection = self._c.conn

        drives = self._c.drive_discovery.discover()
        if only_letter:
            drives = [d for d in drives if d.letter == only_letter]

        totals = {"files_scanned": 0, "files_hashed": 0, "bytes_scanned": 0,
                  "errors": 0, "drives_scanned": 0, "duplicates_found": 0}

        for drive in drives:
            drive_id = self._c.drive_repo.upsert(drive)

            cur = conn.execute(
                "INSERT INTO scan_history (scan_type, drive_id, started_at, status) VALUES (?, ?, ?, 'running')",
                (scan_type, drive_id, started_at),
            )
            scan_history_id = cur.lastrowid
            conn.commit()

            try:
                stats = self._c.file_scanner.scan_path(drive.letter, drive_id, compute_hashes)
                self._c.file_repo.delete_missing_before(started_at, drive_id)

                totals["files_scanned"] += stats.files_scanned
                totals["files_hashed"] += stats.files_hashed
                totals["bytes_scanned"] += stats.bytes_scanned
                totals["errors"] += stats.errors
                totals["drives_scanned"] += 1

                conn.execute(
                    """UPDATE scan_history SET finished_at=datetime('now'), files_scanned=?,
                       files_hashed=?, bytes_scanned=?, errors=?, status='completed' WHERE id=?""",
                    (stats.files_scanned, stats.files_hashed, stats.bytes_scanned,
                     stats.errors, scan_history_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                try:
                    conn.execute(
                        "UPDATE scan_history SET finished_at=datetime('now'), status='failed' WHERE id=?",
                        (scan_history_id,),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    logger.exception("Failed to even record the scan failure for drive %s", drive.letter)
                logger.exception("Scan failed for drive %s", drive.letter)

        groups = self._c.duplicate_detection.detect()
        totals["duplicates_found"] = len(groups)
        conn.commit()

        logger.info("Scan complete (%s): %s", scan_type, totals)
        return totals
