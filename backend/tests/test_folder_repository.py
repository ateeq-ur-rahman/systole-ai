from __future__ import annotations

from app.database.models import WatchedFolder
from app.repositories.folder_repository import FolderRepository


def test_add_and_get_folder(db_conn, tmp_path):
    repo = FolderRepository(db_conn)
    folder_id = repo.add(WatchedFolder(id=None, path=str(tmp_path), label="My Projects",
                                        drive_id=None, enabled=True))
    db_conn.commit()

    row = repo.get_by_id(folder_id)
    assert row["path"] == str(tmp_path)
    assert row["label"] == "My Projects"
    assert row["enabled"] == 1
    assert row["last_scan_status"] == "pending"


def test_adding_same_path_twice_updates_instead_of_duplicating(db_conn, tmp_path):
    repo = FolderRepository(db_conn)
    id1 = repo.add(WatchedFolder(id=None, path=str(tmp_path), label="First", drive_id=None, enabled=True))
    id2 = repo.add(WatchedFolder(id=None, path=str(tmp_path), label="Renamed", drive_id=None, enabled=False))
    db_conn.commit()

    assert id1 == id2
    row = repo.get_by_id(id1)
    assert row["label"] == "Renamed"
    assert row["enabled"] == 0
    assert len(repo.list_all()) == 1


def test_list_all_enabled_only(db_conn, tmp_path):
    repo = FolderRepository(db_conn)
    enabled_dir = tmp_path / "enabled"
    disabled_dir = tmp_path / "disabled"
    enabled_dir.mkdir()
    disabled_dir.mkdir()

    repo.add(WatchedFolder(id=None, path=str(enabled_dir), label=None, drive_id=None, enabled=True))
    repo.add(WatchedFolder(id=None, path=str(disabled_dir), label=None, drive_id=None, enabled=False))
    db_conn.commit()

    all_folders = repo.list_all()
    enabled_only = repo.list_all(enabled_only=True)

    assert len(all_folders) == 2
    assert len(enabled_only) == 1
    assert enabled_only[0]["path"] == str(enabled_dir)


def test_remove_folder(db_conn, tmp_path):
    repo = FolderRepository(db_conn)
    folder_id = repo.add(WatchedFolder(id=None, path=str(tmp_path), label=None, drive_id=None, enabled=True))
    db_conn.commit()

    repo.remove(folder_id)
    db_conn.commit()

    assert repo.get_by_id(folder_id) is None


def test_mark_scan_lifecycle(db_conn, tmp_path):
    repo = FolderRepository(db_conn)
    folder_id = repo.add(WatchedFolder(id=None, path=str(tmp_path), label=None, drive_id=None, enabled=True))
    db_conn.commit()

    repo.mark_scan_started(folder_id)
    db_conn.commit()
    assert repo.get_by_id(folder_id)["last_scan_status"] == "scanning"

    repo.mark_scan_finished(folder_id, "completed")
    db_conn.commit()
    row = repo.get_by_id(folder_id)
    assert row["last_scan_status"] == "completed"
    assert row["last_scanned_at"] is not None
