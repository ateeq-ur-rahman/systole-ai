from __future__ import annotations

import os

from app.agents.file_scanner import FileScannerAgent
from app.agents.hash_engine import HashEngine
from app.repositories.file_repository import FileRepository
from app.utils.path_guard import PathGuard


def test_parallel_hashing_many_files_does_not_corrupt_the_shared_connection(db_conn, tmp_path):
    """Regression test for a real production bug: FileScannerAgent used to
    submit HashEngine.hash_file (which reads from the SQLite cache, i.e.
    touches the shared connection) directly into a ThreadPoolExecutor.
    With only a handful of files in tests this rarely manifested, but
    against a real folder with 100+ files and multiple worker threads, it
    reliably raised sqlite3.InterfaceError: bad parameter or other API
    misuse -- a single sqlite3.Connection is not safe to use concurrently
    from multiple threads, even with check_same_thread=False. This test
    creates enough files, with enough worker threads, to have reproduced
    the bug before the fix (cache lookups + writes now happen only on the
    calling thread; only pure hashing runs in the pool).

    Note: because this was a genuine thread-scheduling race, it was
    NON-DETERMINISTIC even before the fix -- confirmed by running this
    exact test repeatedly against the unfixed code, which failed on some
    runs and passed on others. A single green run here is not proof the
    bug is absent; the actual guarantee comes from the architectural fix
    (no SQLite access from worker threads at all, verified by code
    review), not from this test's ability to catch a race under load."""
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard, max_workers=8)

    file_count = 150
    for i in range(file_count):
        content = f"file number {i} with some padding content\n".encode() * 200
        (tmp_path / f"file_{i:04d}.dat").write_bytes(content)

    stats = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == file_count
    assert stats.errors == 0
    assert stats.files_hashed == file_count

    rows = file_repo.largest_files(limit=file_count + 10)
    hashed = [r for r in rows if r["sha256"] is not None]
    assert len(hashed) == file_count


def test_second_scan_of_same_large_folder_uses_cache_and_still_succeeds(db_conn, tmp_path):
    """The cache-hit path (files unchanged since last scan) also must not
    touch the connection from worker threads -- this exercises that path
    at the same scale as the bug report (all files cached on the second
    pass, zero actually re-hashed)."""
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard, max_workers=8)

    file_count = 60
    for i in range(file_count):
        (tmp_path / f"file_{i:04d}.dat").write_bytes(f"content {i}\n".encode() * 100)

    first = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)
    second = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert first.files_hashed == file_count
    assert first.errors == 0
    assert second.files_hashed == 0  # everything served from cache
    assert second.errors == 0
