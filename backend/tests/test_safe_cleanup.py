from __future__ import annotations

from app.agents.safe_cleanup import SafeCleanupAgent
from app.database.models import FileRecord
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.vault_repository import VaultRepository
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault

SAME_HASH = "c" * 64


def _setup_duplicate_group(db_conn, tmp_path):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)

    survivor_path = tmp_path / "Documents" / "report.docx"
    redundant_path = tmp_path / "Downloads" / "report_copy.docx"
    survivor_path.parent.mkdir(parents=True)
    redundant_path.parent.mkdir(parents=True)
    survivor_path.write_text("same content")
    redundant_path.write_text("same content")

    survivor_id = file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=str(survivor_path), filename="report.docx",
        extension=".docx", folder=str(survivor_path.parent), size_bytes=12,
        modified_time="2024-06-01T00:00:00",
    ))
    file_repo.set_hash(survivor_id, SAME_HASH)

    redundant_id = file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=str(redundant_path), filename="report_copy.docx",
        extension=".docx", folder=str(redundant_path.parent), size_bytes=12,
        modified_time="2024-01-01T00:00:00",
    ))
    file_repo.set_hash(redundant_id, SAME_HASH)
    db_conn.commit()

    group_id = dup_repo.upsert_group(SAME_HASH, file_count=2, total_size_bytes=24,
                                      reclaimable_bytes=12, survivor_file_id=survivor_id)
    dup_repo.add_member(group_id, survivor_id, is_survivor=True, reason="latest_modified")
    dup_repo.add_member(group_id, redundant_id, is_survivor=False, reason="redundant_copy")
    db_conn.commit()

    return group_id, survivor_path, redundant_path


def test_clean_group_moves_only_non_survivor(db_conn, tmp_path):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    vault_repo = VaultRepository(db_conn)
    guard = PathGuard()
    vault = SafeVault(str(tmp_path / "vault"))
    agent = SafeCleanupAgent(file_repo, dup_repo, vault_repo, vault, guard)

    group_id, survivor_path, redundant_path = _setup_duplicate_group(db_conn, tmp_path)

    outcome = agent.clean_group(group_id)

    assert survivor_path.exists()          # survivor untouched
    assert not redundant_path.exists()     # redundant copy moved away
    assert len(outcome.moved) == 1
    assert outcome.bytes_reclaimed == 12


def test_restore_brings_file_back(db_conn, tmp_path):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    vault_repo = VaultRepository(db_conn)
    guard = PathGuard()
    vault = SafeVault(str(tmp_path / "vault"))
    agent = SafeCleanupAgent(file_repo, dup_repo, vault_repo, vault, guard)

    group_id, survivor_path, redundant_path = _setup_duplicate_group(db_conn, tmp_path)
    outcome = agent.clean_group(group_id)
    cleanup_id = outcome.moved[0]["cleanup_id"]

    restored = agent.restore(cleanup_id)

    assert restored is True
    assert redundant_path.exists()
    assert redundant_path.read_text() == "same content"


def test_cleanup_never_touches_protected_paths(db_conn, tmp_path):
    file_repo = FileRepository(db_conn)
    dup_repo = DuplicateRepository(db_conn)
    vault_repo = VaultRepository(db_conn)
    guard = PathGuard()
    vault = SafeVault(str(tmp_path / "vault"))
    agent = SafeCleanupAgent(file_repo, dup_repo, vault_repo, vault, guard)

    # Simulate a "redundant" file that happens to sit under System32 --
    # cleanup must refuse to move it even though duplicate detection
    # flagged it, because PathGuard is the final safety authority.
    protected_id = file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=r"C:\Windows\System32\fake.docx",
        filename="fake.docx", extension=".docx", folder=r"C:\Windows\System32",
        size_bytes=12, modified_time="2024-01-01T00:00:00",
    ))
    file_repo.set_hash(protected_id, SAME_HASH)
    survivor_path = tmp_path / "report.docx"
    survivor_path.write_text("same content")
    survivor_id = file_repo.upsert(FileRecord(
        id=None, drive_id=None, full_path=str(survivor_path), filename="report.docx",
        extension=".docx", folder=str(tmp_path), size_bytes=12,
        modified_time="2024-06-01T00:00:00",
    ))
    file_repo.set_hash(survivor_id, SAME_HASH)
    db_conn.commit()

    group_id = dup_repo.upsert_group(SAME_HASH, 2, 24, 12, survivor_id)
    dup_repo.add_member(group_id, survivor_id, True, "latest_modified")
    dup_repo.add_member(group_id, protected_id, False, "redundant_copy")
    db_conn.commit()

    outcome = agent.clean_group(group_id)

    assert len(outcome.moved) == 0
    assert len(outcome.skipped) == 1
    assert "protected" in outcome.skipped[0]["reason"]
