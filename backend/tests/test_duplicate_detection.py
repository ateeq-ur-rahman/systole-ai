from __future__ import annotations

from app.agents.duplicate_detection import DuplicateDetectionAgent
from app.agents.version_intelligence import VersionIntelligenceAgent
from app.database.models import FileRecord
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository

SAME_HASH = "a" * 64
OTHER_HASH = "b" * 64


def _insert_file(repo: FileRepository, conn, **overrides) -> int:
    defaults = dict(
        full_path=f"C:\\file_{overrides.get('filename', 'x')}.txt",
        filename="x.txt", extension=".txt", folder="C:\\",
        size_bytes=100, modified_time="2024-01-01T00:00:00",
        created_time="2024-01-01T00:00:00", accessed_time="2024-01-01T00:00:00",
    )
    defaults.update(overrides)
    record = FileRecord(id=None, drive_id=None, **defaults)
    file_id = repo.upsert(record)
    if "sha256" in overrides:
        repo.set_hash(file_id, overrides["sha256"])
    conn.commit()
    return file_id


def test_files_with_matching_hash_are_grouped(db_conn):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)

    _insert_file(file_repo, db_conn, full_path="C:\\a.txt", filename="a.txt", sha256=SAME_HASH)
    _insert_file(file_repo, db_conn, full_path="C:\\b.txt", filename="b.txt", sha256=SAME_HASH)

    groups = agent.detect()
    assert len(groups) == 1
    assert groups[0].file_count == 2
    assert groups[0].sha256 == SAME_HASH


def test_files_with_different_hash_are_not_grouped(db_conn):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)

    _insert_file(file_repo, db_conn, full_path="C:\\a.txt", filename="a.txt", sha256=SAME_HASH)
    _insert_file(file_repo, db_conn, full_path="C:\\b.txt", filename="b.txt", sha256=OTHER_HASH)

    groups = agent.detect()
    assert len(groups) == 0


def test_same_filename_different_hash_is_never_grouped(db_conn):
    """Direct test of the spec's example: Resume.pdf / Resume Final.pdf /
    Copy.pdf should only group if their hashes match -- filename is
    irrelevant to the grouping decision."""
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)

    _insert_file(file_repo, db_conn, full_path="C:\\Resume.pdf", filename="Resume.pdf", sha256=SAME_HASH)
    _insert_file(file_repo, db_conn, full_path="C:\\Resume Final.pdf", filename="Resume Final.pdf", sha256=SAME_HASH)
    _insert_file(file_repo, db_conn, full_path="C:\\Copy.pdf", filename="Copy.pdf", sha256=OTHER_HASH)

    groups = agent.detect()
    assert len(groups) == 1
    assert groups[0].file_count == 2  # only the two matching-hash files grouped


def test_reclaimable_bytes_excludes_survivor(db_conn):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)

    _insert_file(file_repo, db_conn, full_path="C:\\a.txt", filename="a.txt",
                 sha256=SAME_HASH, size_bytes=500)
    _insert_file(file_repo, db_conn, full_path="C:\\b.txt", filename="b.txt",
                 sha256=SAME_HASH, size_bytes=500)
    _insert_file(file_repo, db_conn, full_path="C:\\c.txt", filename="c.txt",
                 sha256=SAME_HASH, size_bytes=500)

    groups = agent.detect()
    assert groups[0].total_size_bytes == 1500
    assert groups[0].reclaimable_bytes == 1000  # 3 copies, 1 survivor kept


def test_minimum_size_filter_excludes_small_duplicates(db_conn):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent, min_size_bytes=1000)

    _insert_file(file_repo, db_conn, full_path="C:\\a.txt", filename="a.txt",
                 sha256=SAME_HASH, size_bytes=50)
    _insert_file(file_repo, db_conn, full_path="C:\\b.txt", filename="b.txt",
                 sha256=SAME_HASH, size_bytes=50)

    groups = agent.detect()
    assert len(groups) == 0


def test_hardlink_of_survivor_excluded_from_reclaimable_bytes(db_conn):
    """A hardlink to the survivor shares the same physical disk data, so
    it must not inflate the 'reclaimable space' estimate -- moving that
    path away frees zero bytes while the survivor's link keeps the data
    alive."""
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)

    # survivor (latest modified) and its hardlink share inode_key "1:100"
    _insert_file(file_repo, db_conn, full_path="C:\\newest.txt", filename="newest.txt",
                 sha256=SAME_HASH, size_bytes=500, modified_time="2024-06-01T00:00:00",
                 inode_key="dev1:100")
    _insert_file(file_repo, db_conn, full_path="C:\\hardlink_of_newest.txt",
                 filename="hardlink_of_newest.txt", sha256=SAME_HASH, size_bytes=500,
                 modified_time="2024-01-01T00:00:00", inode_key="dev1:100")
    # a genuinely separate physical copy -- this one IS reclaimable
    _insert_file(file_repo, db_conn, full_path="C:\\separate_copy.txt",
                 filename="separate_copy.txt", sha256=SAME_HASH, size_bytes=500,
                 modified_time="2023-01-01T00:00:00", inode_key="dev1:200")

    groups = agent.detect()

    assert len(groups) == 1
    group = groups[0]
    assert group.file_count == 3
    assert group.total_size_bytes == 1500
    # Only the genuinely separate copy is reclaimable -- not the hardlink.
    assert group.reclaimable_bytes == 500

    members = dup_repo.get_members(group.id)
    hardlink_member = next(m for m in members if m["full_path"] == "C:\\hardlink_of_newest.txt")
    assert hardlink_member["selection_reason"] == "hardlink_of_survivor"


def test_folder_scoped_detection_ignores_files_outside_prefix(db_conn):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    version_agent = VersionIntelligenceAgent()
    agent = DuplicateDetectionAgent(file_repo, dup_repo, version_agent)

    _insert_file(file_repo, db_conn, full_path="C:\\Watched\\a.txt", filename="a.txt",
                 sha256=SAME_HASH, size_bytes=500)
    _insert_file(file_repo, db_conn, full_path="C:\\Watched\\b.txt", filename="b.txt",
                 sha256=SAME_HASH, size_bytes=500)
    # identical content, but lives outside the watched folder -- must be ignored
    _insert_file(file_repo, db_conn, full_path="C:\\Elsewhere\\c.txt", filename="c.txt",
                 sha256=SAME_HASH, size_bytes=500)

    groups = agent.detect(path_prefix="C:\\Watched")

    assert len(groups) == 1
    assert groups[0].file_count == 2  # only the two files inside C:\Watched
