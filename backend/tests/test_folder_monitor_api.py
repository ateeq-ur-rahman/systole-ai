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


def test_no_active_folder_initially(client):
    resp = client.get("/folder-monitor")
    assert resp.status_code == 200
    assert resp.json() == {"active": False}


def test_set_folder_and_verify_status(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("hello" * 1000)

    resp = client.post("/folder-monitor", json={"path": str(watch_dir), "scan_interval_seconds": 60})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["path"] == os.path.normpath(str(watch_dir))
    assert body["total_files"] == 1
    assert body["scan_interval_seconds"] == 60

    status = client.get("/folder-monitor").json()
    assert status["path"] == os.path.normpath(str(watch_dir))


def test_full_duplicate_lifecycle_via_api(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    content = "identical file content\n" * 300

    (watch_dir / "photo.jpg").write_text(content)
    (watch_dir / "photo_copy.jpg").write_text(content)

    resp = client.post("/folder-monitor", json={"path": str(watch_dir)})
    body = resp.json()

    assert body["total_files"] == 1  # duplicate auto-cleaned, one survivor remains indexed
    assert body["recovered_bytes"] > 0
    assert body["vault_entries"] == 1

    remaining = list(watch_dir.glob("*.jpg"))
    assert len(remaining) == 1  # exactly one survives on disk


def test_reject_protected_path_via_api(client, tmp_path):
    fake_system = tmp_path / "Windows" / "System32"
    fake_system.mkdir(parents=True)

    resp = client.post("/folder-monitor", json={"path": str(fake_system)})
    assert resp.status_code == 400


def test_pause_and_resume_via_api(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("hello")

    client.post("/folder-monitor", json={"path": str(watch_dir)})

    pause_resp = client.post("/folder-monitor/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["paused"] is True

    resume_resp = client.post("/folder-monitor/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["paused"] is False


def test_manual_scan_now_endpoint(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("hello" * 1000)

    client.post("/folder-monitor", json={"path": str(watch_dir)})

    (watch_dir / "b.txt").write_text("world" * 1000)  # add a file after the initial scan

    scan_resp = client.post("/folder-monitor/scan")
    assert scan_resp.status_code == 200
    assert scan_resp.json()["files_scanned"] == 2


def test_remove_folder_via_api(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("hello")

    client.post("/folder-monitor", json={"path": str(watch_dir)})
    remove_resp = client.delete("/folder-monitor")
    assert remove_resp.status_code == 200

    status = client.get("/folder-monitor").json()
    assert status == {"active": False}


def test_update_settings_via_api(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("hello")

    client.post("/folder-monitor", json={"path": str(watch_dir)})

    resp = client.post("/folder-monitor/settings", json={"scan_interval_seconds": 300,
                                                            "notifications_enabled": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_interval_seconds"] == 300
    assert body["notifications_enabled"] is False


def test_notifications_are_listed_and_readable(client, tmp_path):
    watch_dir = tmp_path / "Downloads"
    watch_dir.mkdir()
    (watch_dir / "a.txt").write_text("hello")

    client.post("/folder-monitor", json={"path": str(watch_dir)})

    list_resp = client.get("/notifications")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["unread_count"] > 0
    assert any("Monitoring" in n["message"] for n in body["notifications"])

    mark_all_resp = client.post("/notifications/read-all")
    assert mark_all_resp.status_code == 200

    after = client.get("/notifications").json()
    assert after["unread_count"] == 0
