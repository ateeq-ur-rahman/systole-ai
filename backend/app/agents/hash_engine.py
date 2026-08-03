"""
Hash Engine

The single source of truth for "are two files actually identical". Per the
product spec this is the MOST IMPORTANT RULE in the whole system: duplicate
detection is decided ONLY by SHA-256 content hash -- never filename, never
timestamp, never folder name.

Design notes:
- Streams files in fixed-size chunks so multi-GB files don't blow up memory.
- Uses the file_repository hash cache (path + mtime + size match) so an
  unchanged file is never re-hashed -- this is what makes incremental scans
  of millions of files feasible.
- Every read goes through PathGuard first.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from app.repositories.file_repository import FileRepository
from app.utils.path_guard import PathGuard
from app.utils.winpath import to_long_path

logger = logging.getLogger("systole.hash_engine")


@dataclass
class HashResult:
    path: str
    sha256: Optional[str]
    from_cache: bool
    error: Optional[str] = None


class HashEngine:
    def __init__(self, file_repo: FileRepository, guard: PathGuard,
                 chunk_size: int = 1024 * 1024, algorithm: str = "sha256"):
        self._file_repo = file_repo
        self._guard = guard
        self._chunk_size = chunk_size
        self._algorithm = algorithm

    def hash_file(self, path: str, modified_time: str, size_bytes: int) -> HashResult:
        """DB-aware convenience wrapper: checks the cache, then computes if
        needed. Safe to call from the main thread only -- it touches the
        shared SQLite connection via file_repo. For parallel hashing
        across a thread pool, use compute_only() instead (see
        FileScannerAgent._process_batch), which never touches the
        database."""
        guard_check = self._guard.is_scannable(path)
        if not guard_check.allowed:
            return HashResult(path, None, from_cache=False, error=f"blocked: {guard_check.reason}")

        cached = self._file_repo.get_cached_hash(path, modified_time, size_bytes)
        if cached:
            return HashResult(path, cached, from_cache=True)

        return self.compute_only(path)

    def compute_only(self, path: str) -> HashResult:
        """Pure, DB-free hashing -- reads the file and computes SHA-256,
        nothing else. This is the only method of this class safe to call
        concurrently from multiple worker threads: it never touches
        file_repo/the SQLite connection, which (even with
        check_same_thread=False) is not safe for concurrent use from more
        than one thread at a time. Cache lookups and all database writes
        must happen on the caller's own thread, sequentially -- see
        FileScannerAgent._process_batch for the pattern."""
        guard_check = self._guard.is_scannable(path)
        if not guard_check.allowed:
            return HashResult(path, None, from_cache=False, error=f"blocked: {guard_check.reason}")
        try:
            digest = self._compute(path)
            return HashResult(path, digest, from_cache=False)
        except (OSError, PermissionError) as exc:
            logger.warning("Failed to hash %s: %s", path, exc)
            return HashResult(path, None, from_cache=False, error=str(exc))

    def _compute(self, path: str) -> str:
        hasher = hashlib.new(self._algorithm)
        with open(to_long_path(path), "rb") as fh:
            while True:
                chunk = fh.read(self._chunk_size)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
