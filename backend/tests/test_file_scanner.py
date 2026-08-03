from __future__ import annotations

import os

from app.agents.file_scanner import FileScannerAgent
from app.agents.hash_engine import HashEngine
from app.repositories.file_repository import FileRepository
from app.utils.path_guard import PathGuard


def test_scan_path_collects_files_and_hashes(db_conn, tmp_tree):
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard, max_workers=2)

    (tmp_tree["documents"] / "notes.txt").write_text("meeting notes")
    (tmp_tree["downloads"] / "installer.zip").write_bytes(b"fake zip bytes")

    stats = scanner.scan_path(str(tmp_tree["root"]), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == 2
    assert stats.files_hashed == 2
    assert stats.errors == 0

    row = file_repo.get_by_path(str(tmp_tree["documents"] / "notes.txt"))
    assert row is not None
    assert row["sha256"] is not None


def test_scan_path_prunes_protected_subdirectories(db_conn, tmp_path):
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard)

    normal_dir = tmp_path / "Documents"
    normal_dir.mkdir()
    (normal_dir / "keep.txt").write_text("keep this")

    # Simulate an AppData-style protected subfolder inside the scan root.
    appdata_dir = tmp_path / "Users" / "alice" / "AppData" / "Local"
    appdata_dir.mkdir(parents=True)
    (appdata_dir / "secret_cache.dat").write_bytes(b"should never be scanned")

    stats = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == 1  # only keep.txt
    assert file_repo.get_by_path(str(appdata_dir / "secret_cache.dat")) is None


def test_incremental_scan_does_not_rehash_unchanged_file(db_conn, tmp_path):
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard)

    f = tmp_path / "stable.txt"
    f.write_text("unchanging content")

    stats_first = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)
    stats_second = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert stats_first.files_hashed == 1
    assert stats_second.files_hashed == 0  # served from cache, not rehashed


def test_symlinked_directory_is_pruned_not_followed(db_conn, tmp_path):
    """A symlinked directory must never be descended into -- both to avoid
    double-scanning content that lives elsewhere, and to avoid infinite
    loops from a link that points back at an ancestor."""
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard)

    real_dir = tmp_path / "real_target"
    real_dir.mkdir()
    (real_dir / "linked_content.txt").write_text("lives elsewhere")

    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    (watch_dir / "normal.txt").write_text("normal file")
    (watch_dir / "link_to_real").symlink_to(real_dir, target_is_directory=True)

    stats = scanner.scan_path(str(watch_dir), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == 1  # only normal.txt
    assert stats.skipped_reparse_points >= 1
    assert file_repo.get_by_path(str(real_dir / "linked_content.txt")) is None


def test_hardlinked_files_share_inode_key(db_conn, tmp_path):
    """Two hardlinks to the same physical file must be recognized as the
    same underlying data via inode_key -- this is what lets duplicate
    detection later avoid reporting 'reclaimable space' for a hardlink
    pair, since moving one link away doesn't free any disk space while
    the other link still exists."""
    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard)

    original = tmp_path / "original.txt"
    original.write_text("shared physical content")
    linked = tmp_path / "hardlink_copy.txt"
    os.link(original, linked)

    scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    row_a = file_repo.get_by_path(str(original))
    row_b = file_repo.get_by_path(str(linked))

    assert row_a["inode_key"] is not None
    assert row_a["inode_key"] == row_b["inode_key"]


def test_scan_filter_excludes_disabled_categories(db_conn, tmp_path):
    from app.utils.scan_filter import ScanFilter

    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scan_filter = ScanFilter()  # defaults: documents/images/videos/pdfs/office/archives/installers
    scanner = FileScannerAgent(file_repo, hash_engine, guard, scan_filter=scan_filter)

    (tmp_path / "report.pdf").write_bytes(b"x" * 5000)          # included (pdfs)
    (tmp_path / "photo.jpg").write_bytes(b"x" * 5000)           # included (images)
    (tmp_path / "script.py").write_bytes(b"x" * 5000)           # excluded (source_code, off by default)
    (tmp_path / "app.dll").write_bytes(b"x" * 5000)             # excluded (system_files, off by default)

    stats = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == 2
    # script.py is caught by ScanFilter (source_code category disabled).
    # app.dll is caught earlier, by PathGuard's unconditional safety layer
    # (.dll is in NEVER_TOUCH_EXTENSIONS) -- correct layering: the hard
    # safety check runs before the configurable relevance filter.
    assert stats.skipped_by_filter == 1
    assert stats.skipped_protected == 1
    assert file_repo.get_by_path(str(tmp_path / "report.pdf")) is not None
    assert file_repo.get_by_path(str(tmp_path / "photo.jpg")) is not None
    assert file_repo.get_by_path(str(tmp_path / "script.py")) is None
    assert file_repo.get_by_path(str(tmp_path / "app.dll")) is None


def test_scan_filter_prunes_ignored_dev_folders(db_conn, tmp_path):
    from app.utils.scan_filter import ScanFilter

    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scanner = FileScannerAgent(file_repo, hash_engine, guard, scan_filter=ScanFilter())

    (tmp_path / "Documents").mkdir()
    (tmp_path / "Documents" / "report.pdf").write_bytes(b"x" * 5000)

    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "package.json").write_bytes(b"x" * 5000)
    nested = node_modules / "some-package" / "deep" / "file.pdf"  # even a "user" extension inside node_modules
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x" * 5000)

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_bytes(b"x" * 5000)

    stats = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == 1  # only Documents/report.pdf
    assert file_repo.get_by_path(str(tmp_path / "Documents" / "report.pdf")) is not None
    assert file_repo.get_by_path(str(nested)) is None
    assert file_repo.get_by_path(str(git_dir / "config")) is None


def test_scan_filter_skips_files_below_minimum_size(db_conn, tmp_path):
    from app.utils.scan_filter import ScanFilter

    file_repo = FileRepository(db_conn)
    guard = PathGuard()
    hash_engine = HashEngine(file_repo, guard)
    scan_filter = ScanFilter(minimum_file_size_bytes=4096)
    scanner = FileScannerAgent(file_repo, hash_engine, guard, scan_filter=scan_filter)

    (tmp_path / "tiny.pdf").write_bytes(b"x" * 100)     # below minimum
    (tmp_path / "normal.pdf").write_bytes(b"x" * 5000)  # above minimum

    stats = scanner.scan_path(str(tmp_path), drive_id=None, compute_hashes=True)

    assert stats.files_scanned == 1
    assert file_repo.get_by_path(str(tmp_path / "tiny.pdf")) is None
    assert file_repo.get_by_path(str(tmp_path / "normal.pdf")) is not None
