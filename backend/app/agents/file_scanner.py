"""
File Scanner Agent

Walks a drive/directory tree, collects filesystem metadata for every
accessible file, and persists it via FileRepository. Hashing is delegated
to HashEngine and is only triggered for files whose (path, mtime, size)
aren't already cached -- keeping incremental scans cheap.

Every path is checked with PathGuard.is_scannable() before descent (for
directories) or read (for files), so protected system locations are never
even walked into, not just filtered out after the fact.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agents.hash_engine import HashEngine
from app.database.models import FileRecord
from app.repositories.file_repository import FileRepository
from app.utils.path_guard import PathGuard
from app.utils.scan_filter import ScanFilter
from app.utils.winpath import inode_key, is_reparse_point, to_long_path

logger = logging.getLogger("systole.file_scanner")


@dataclass
class ScanStats:
    files_scanned: int = 0
    files_hashed: int = 0
    bytes_scanned: int = 0
    errors: int = 0
    skipped_protected: int = 0
    skipped_reparse_points: int = 0
    skipped_by_filter: int = 0
    error_paths: list[str] = field(default_factory=list)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class FileScannerAgent:
    def __init__(self, file_repo: FileRepository, hash_engine: HashEngine,
                 guard: PathGuard, max_workers: int = 4, batch_size: int = 500,
                 scan_filter: ScanFilter | None = None):
        self._file_repo = file_repo
        self._hash_engine = hash_engine
        self._guard = guard
        self._max_workers = max_workers
        self._batch_size = batch_size
        # None = no category/folder-name/size filtering at all (every
        # existing caller that doesn't pass one keeps scanning everything
        # PathGuard allows, same as before this feature existed).
        # Production wiring (see container.py) always supplies a real
        # ScanFilter built from Settings so the "scan only user files by
        # default" behavior is live for actual usage.
        self._scan_filter = scan_filter

    def scan_path(self, root_path: str, drive_id: int | None, compute_hashes: bool = True) -> ScanStats:
        stats = ScanStats()
        for dirpath, dirnames, filenames in os.walk(root_path, onerror=self._on_walk_error, topdown=True):
            # Prune protected directories, reparse points (symlinks, NTFS
            # junctions, mount points), AND filter-ignored dev/build
            # folders (node_modules, .git, etc.) in-place so os.walk never
            # descends into any of them. This is both the "never scan
            # aggressively" safety requirement and the performance
            # requirement to skip large, irrelevant folder trees entirely
            # rather than walking in and filtering files out one by one.
            kept_dirnames = []
            for d in dirnames:
                full_dir = os.path.join(dirpath, d)
                if is_reparse_point(full_dir):
                    stats.skipped_reparse_points += 1
                    continue
                if not self._guard.is_scannable(full_dir).allowed:
                    continue
                if self._scan_filter and self._scan_filter.is_folder_ignored(d):
                    stats.skipped_by_filter += 1
                    continue
                kept_dirnames.append(d)
            dirnames[:] = kept_dirnames

            file_batch = []
            for filename in filenames:
                full_path = os.path.join(dirpath, filename)
                if is_reparse_point(full_path):
                    stats.skipped_reparse_points += 1
                    continue
                check = self._guard.is_scannable(full_path)
                if not check.allowed:
                    stats.skipped_protected += 1
                    continue
                if self._scan_filter:
                    extension = os.path.splitext(filename)[1].lower()
                    if not self._scan_filter.is_extension_included(extension):
                        # Excluded before any stat/hash/DB work happens at
                        # all -- this is the "never hash ignored files"
                        # requirement enforced at the cheapest possible
                        # point (a filename string check, no disk I/O).
                        stats.skipped_by_filter += 1
                        continue
                file_batch.append(full_path)

            if file_batch:
                self._process_batch(file_batch, drive_id, compute_hashes, stats)

        return stats

    def _process_batch(self, paths: list[str], drive_id: int | None,
                        compute_hashes: bool, stats: ScanStats) -> None:
        records: list[tuple[str, FileRecord]] = []
        for path in paths:
            try:
                st = os.stat(to_long_path(path))
            except (OSError, PermissionError) as exc:
                stats.errors += 1
                stats.error_paths.append(path)
                logger.debug("stat failed for %s: %s", path, exc)
                continue

            if self._scan_filter and not self._scan_filter.passes_size_filter(st.st_size):
                # Below the minimum-size threshold -- skipped before it
                # ever reaches the database, not just before hashing.
                stats.skipped_by_filter += 1
                continue

            folder = os.path.dirname(path)
            filename = os.path.basename(path)
            extension = os.path.splitext(filename)[1].lower()

            record = FileRecord(
                id=None,
                drive_id=drive_id,
                full_path=path,
                filename=filename,
                extension=extension,
                folder=folder,
                size_bytes=st.st_size,
                created_time=_iso(st.st_ctime),
                modified_time=_iso(st.st_mtime),
                accessed_time=_iso(st.st_atime),
                owner=self._safe_owner(path),
                permissions=oct(st.st_mode)[-3:],
                inode_key=inode_key(st),
            )
            records.append((path, record))
            stats.files_scanned += 1
            stats.bytes_scanned += st.st_size

        # Persist metadata first (cheap), then hash (expensive).
        file_ids: dict[str, int] = {}
        for path, record in records:
            file_ids[path] = self._file_repo.upsert(record)

        if not compute_hashes:
            return

        # Cache lookups run sequentially on the main thread -- cheap, and
        # critically, this is the only place file_repo (the shared SQLite
        # connection) gets touched for hashing purposes. Only genuine
        # cache misses get their bytes actually hashed, and that pure
        # disk-I/O work (no DB access at all) is what gets parallelized
        # below. A single sqlite3.Connection is not safe to use
        # concurrently from multiple threads even with
        # check_same_thread=False -- doing the cache check here (instead
        # of inside the worker threads) is what keeps every DB call on
        # one thread at a time.
        to_hash: list[tuple[str, FileRecord]] = []
        for path, record in records:
            cached = self._file_repo.get_cached_hash(path, record.modified_time, record.size_bytes)
            if cached:
                self._file_repo.set_hash(file_ids[path], cached)
            else:
                to_hash.append((path, record))

        if not to_hash:
            return

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._hash_engine.compute_only, path): (path, record)
                for path, record in to_hash
            }
            for future in as_completed(futures):
                path, record = futures[future]
                result = future.result()
                if result.error:
                    stats.errors += 1
                    stats.error_paths.append(path)
                    continue
                if result.sha256:
                    stats.files_hashed += 1
                    self._file_repo.set_hash(file_ids[path], result.sha256)

    @staticmethod
    def _safe_owner(path: str) -> str:
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return "unknown"

    @staticmethod
    def _on_walk_error(exc: OSError) -> None:
        logger.debug("Walk error: %s", exc)
