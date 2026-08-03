from __future__ import annotations

import hashlib

from app.agents.hash_engine import HashEngine
from app.database.models import FileRecord
from app.repositories.file_repository import FileRepository
from app.utils.path_guard import PathGuard


def _make_file(path, content: bytes):
    path.write_bytes(content)
    return path


def test_identical_content_produces_identical_hash(db_conn, tmp_path):
    repo = FileRepository(db_conn)
    guard = PathGuard()
    engine = HashEngine(repo, guard, chunk_size=8)  # tiny chunk to exercise streaming

    f1 = _make_file(tmp_path / "a.txt", b"hello world, this is identical content")
    f2 = _make_file(tmp_path / "b_copy.txt", b"hello world, this is identical content")

    r1 = engine.hash_file(str(f1), "2024-01-01T00:00:00", f1.stat().st_size)
    r2 = engine.hash_file(str(f2), "2024-01-01T00:00:00", f2.stat().st_size)

    assert r1.sha256 == r2.sha256
    assert r1.sha256 == hashlib.sha256(b"hello world, this is identical content").hexdigest()


def test_different_content_produces_different_hash(db_conn, tmp_path):
    repo = FileRepository(db_conn)
    guard = PathGuard()
    engine = HashEngine(repo, guard)

    f1 = _make_file(tmp_path / "a.txt", b"content A")
    f2 = _make_file(tmp_path / "b.txt", b"content B, totally different")

    r1 = engine.hash_file(str(f1), "2024-01-01T00:00:00", f1.stat().st_size)
    r2 = engine.hash_file(str(f2), "2024-01-01T00:00:00", f2.stat().st_size)

    assert r1.sha256 != r2.sha256


def test_same_filename_different_content_never_matches(db_conn, tmp_path):
    """Regression test for the spec's core rule: filename must NEVER be
    used to determine duplicates."""
    repo = FileRepository(db_conn)
    guard = PathGuard()
    engine = HashEngine(repo, guard)

    dir_a = tmp_path / "folder_a"
    dir_b = tmp_path / "folder_b"
    dir_a.mkdir()
    dir_b.mkdir()

    f1 = _make_file(dir_a / "resume.pdf", b"version one of resume")
    f2 = _make_file(dir_b / "resume.pdf", b"version two of resume, edited")

    r1 = engine.hash_file(str(f1), "2024-01-01T00:00:00", f1.stat().st_size)
    r2 = engine.hash_file(str(f2), "2024-01-01T00:00:00", f2.stat().st_size)

    assert r1.sha256 != r2.sha256


def test_hash_cache_is_used_when_mtime_and_size_unchanged(db_conn, tmp_path):
    repo = FileRepository(db_conn)
    guard = PathGuard()
    engine = HashEngine(repo, guard)

    f = _make_file(tmp_path / "cached.txt", b"cache me please")
    record = FileRecord(
        id=None, drive_id=None, full_path=str(f), filename="cached.txt",
        extension=".txt", folder=str(tmp_path), size_bytes=f.stat().st_size,
        modified_time="2024-01-01T00:00:00",
    )
    file_id = repo.upsert(record)
    digest = hashlib.sha256(b"cache me please").hexdigest()
    repo.set_hash(file_id, digest)
    db_conn.commit()

    result = engine.hash_file(str(f), "2024-01-01T00:00:00", f.stat().st_size)
    assert result.from_cache is True
    assert result.sha256 == digest


def test_hash_blocked_for_protected_path(db_conn, tmp_path):
    repo = FileRepository(db_conn)
    guard = PathGuard()
    engine = HashEngine(repo, guard)

    result = engine.hash_file(r"C:\Windows\System32\ntdll.dll", "2024-01-01T00:00:00", 1234)
    assert result.sha256 is None
    assert result.error is not None
    assert "blocked" in result.error
