from __future__ import annotations

import time

from app.database.models import FileRecord
from app.repositories.file_repository import FileRepository
from app.utils.db_time import sqlite_utc_now


def test_sqlite_utc_now_matches_sqlite_datetime_now_format(db_conn):
    """The two must be directly, correctly comparable as strings -- this
    is the whole point of the helper."""
    row = db_conn.execute("SELECT datetime('now') as t").fetchone()
    sqlite_value = row["t"]
    python_value = sqlite_utc_now()

    # Same length, same separator style, both directly comparable.
    assert len(sqlite_value) == len(python_value) == 19
    assert sqlite_value[10] == python_value[10] == " "


def test_file_scanned_after_started_at_is_not_marked_deleted(db_conn):
    """Regression test for a real bug: comparing a Python isoformat
    timestamp (datetime.now(timezone.utc).isoformat(), 'T' separator, tz
    suffix) against SQLite's datetime('now')-populated last_seen_at (space
    separator, no tz) made every freshly-scanned file's last_seen_at
    string-compare as 'earlier' than the scan's own started_at, so
    delete_missing_before() immediately marked every file it had just
    scanned as deleted. This test scans a file, captures a started_at via
    the SAME helper the production code now uses, and asserts the file
    survives delete_missing_before()."""
    file_repo = FileRepository(db_conn)

    db_conn.execute(
        "INSERT INTO drives (letter, volume_name, filesystem, drive_type) VALUES ('C:\\\\', 'Local', 'NTFS', 'SSD')"
    )
    drive_id = db_conn.execute("SELECT id FROM drives WHERE letter='C:\\\\'").fetchone()["id"]
    db_conn.commit()

    started_at = sqlite_utc_now()
    time.sleep(1.1)  # ensure a real, second-granularity gap for SQLite's format

    file_repo.upsert(FileRecord(
        id=None, drive_id=drive_id, full_path="C:\\file.txt", filename="file.txt",
        extension=".txt", folder="C:\\", size_bytes=10,
    ))
    db_conn.commit()

    removed = file_repo.delete_missing_before(started_at, drive_id)

    row = file_repo.get_by_path("C:\\file.txt")
    assert removed == 0
    assert row["is_deleted"] == 0


def test_delete_missing_before_still_flags_genuinely_stale_files(db_conn):
    """The fix must not break the feature it's fixing -- a file that
    really was last seen before this scan started should still be marked
    deleted."""
    file_repo = FileRepository(db_conn)

    db_conn.execute(
        "INSERT INTO drives (letter, volume_name, filesystem, drive_type) VALUES ('D:\\\\', 'Data', 'NTFS', 'HDD')"
    )
    drive_id = db_conn.execute("SELECT id FROM drives WHERE letter='D:\\\\'").fetchone()["id"]
    db_conn.commit()

    file_repo.upsert(FileRecord(
        id=None, drive_id=drive_id, full_path="D:\\stale.txt", filename="stale.txt",
        extension=".txt", folder="D:\\", size_bytes=10,
    ))
    db_conn.commit()

    time.sleep(1.1)
    started_at = sqlite_utc_now()  # scan "starts" after the file was last seen

    removed = file_repo.delete_missing_before(started_at, drive_id)

    row = file_repo.get_by_path("D:\\stale.txt")
    assert removed == 1
    assert row["is_deleted"] == 1


def test_delete_missing_under_path_does_not_delete_just_scanned_files(db_conn, tmp_path):
    """Same regression, for the folder-scoped variant the Folder Monitor
    Agent uses."""
    file_repo = FileRepository(db_conn)
    folder = str(tmp_path / "Downloads")

    started_at = sqlite_utc_now()
    time.sleep(1.1)

    file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=f"{folder}/report.pdf", filename="report.pdf",
        extension=".pdf", folder=folder, size_bytes=10,
    ))
    db_conn.commit()

    removed = file_repo.delete_missing_under_path(started_at, folder)

    row = file_repo.get_by_path(f"{folder}/report.pdf")
    assert removed == 0
    assert row["is_deleted"] == 0
