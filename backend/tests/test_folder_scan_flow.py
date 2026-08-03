from __future__ import annotations

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_container
from app.config import Settings
from app.container import build_container
from app.database.db import _SCHEMA_PATH
from app.database.migrations import run_migrations


@pytest.fixture
def client(tmp_path):
    """Boots the real FastAPI app but overrides the container dependency
    to bind every route to a fresh in-memory SQLite database and an
    isolated vault directory -- avoids any dependence on process-wide
    settings caching or the real $HOME/.systole directory, so tests are
    fully hermetic and order-independent."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()
    run_migrations(conn)

    settings = Settings(vault_dir=str(tmp_path / "vault"))
    container = build_container(conn, settings)

    from app.main import app
    app.dependency_overrides[get_container] = lambda: container

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    conn.close()


def test_full_folder_dedupe_flow(client, tmp_path):
    watch_dir = tmp_path / "MyProjects"
    subfolder_a = watch_dir / "backup_2023"
    subfolder_b = watch_dir / "backup_2024"
    subfolder_a.mkdir(parents=True)
    subfolder_b.mkdir(parents=True)

    # Same content in two places -> true duplicate. Different content with
    # a similar name -> must NOT be flagged. Content is padded above the
    # default 4KB minimum-duplicate-size threshold so it isn't filtered out.
    report_content = "quarterly report content\n" * 300  # ~7.8 KB
    (subfolder_a / "report.docx").write_text(report_content)
    (subfolder_b / "report.docx").write_text(report_content)
    (subfolder_a / "unique.txt").write_text("nothing else looks like this" * 300)

    # 1. Add the folder to watch.
    add_resp = client.post("/folders", json={"path": str(watch_dir), "label": "My Projects"})
    assert add_resp.status_code == 200
    folder = add_resp.json()
    assert folder["path"] == os.path.normpath(str(watch_dir))
    folder_id = folder["id"]

    # 2. It shows up in the list.
    list_resp = client.get("/folders")
    assert list_resp.status_code == 200
    assert any(f["id"] == folder_id for f in list_resp.json())

    # 3. Scan just this folder.
    scan_resp = client.post(f"/folders/{folder_id}/scan")
    assert scan_resp.status_code == 200
    scan_result = scan_resp.json()
    assert scan_result["files_scanned"] == 3
    assert scan_result["duplicates_found"] == 1

    # 4. Duplicate group is visible via the normal /duplicates endpoint.
    dup_resp = client.get("/duplicates")
    groups = dup_resp.json()
    assert len(groups) == 1
    assert groups[0]["file_count"] == 2

    # 5. Clean it up -- redundant copy moves to the vault, survivor stays.
    cleanup_resp = client.post("/cleanup", json={"group_ids": [groups[0]["id"]]})
    assert cleanup_resp.status_code == 200
    cleanup_result = cleanup_resp.json()
    assert len(cleanup_result["moved"]) == 1

    remaining_reports = list(subfolder_a.glob("report.docx")) + list(subfolder_b.glob("report.docx"))
    assert len(remaining_reports) == 1  # exactly one copy survives on disk

    # unique.txt was never touched.
    assert (subfolder_a / "unique.txt").exists()


def test_cannot_add_protected_path_as_watched_folder(client, tmp_path):
    fake_system_dir = tmp_path / "Windows" / "System32"
    fake_system_dir.mkdir(parents=True)

    resp = client.post("/folders", json={"path": str(fake_system_dir)})
    assert resp.status_code == 400
    assert "protected" in resp.json()["detail"] or "Windows" in resp.json()["detail"]


def test_cannot_add_nonexistent_folder(client, tmp_path):
    resp = client.post("/folders", json={"path": str(tmp_path / "does_not_exist")})
    assert resp.status_code == 400


def test_remove_watched_folder(client, tmp_path):
    watch_dir = tmp_path / "ToRemove"
    watch_dir.mkdir()

    add_resp = client.post("/folders", json={"path": str(watch_dir)})
    folder_id = add_resp.json()["id"]

    delete_resp = client.delete(f"/folders/{folder_id}")
    assert delete_resp.status_code == 200

    list_resp = client.get("/folders")
    assert not any(f["id"] == folder_id for f in list_resp.json())
