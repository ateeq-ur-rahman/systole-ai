from __future__ import annotations

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


def test_default_scan_filter_settings(client):
    resp = client.get("/settings/scan-filter")
    assert resp.status_code == 200
    body = resp.json()
    assert "documents" in body["enabled_categories"]
    assert "source_code" not in body["enabled_categories"]
    assert "node_modules" in body["ignored_folder_names"]
    assert body["minimum_file_size_bytes"] == 4096
    category_ids = [c["id"] for c in body["available_categories"]]
    assert "source_code" in category_ids  # listed even though disabled by default
    assert "system_files" in category_ids


def test_enabling_source_code_category_via_settings(client):
    resp = client.post("/settings/scan-filter", json={
        "enabled_categories": ["documents", "pdfs", "images", "videos", "office",
                                "archives", "installers", "source_code"],
    })
    assert resp.status_code == 200
    assert "source_code" in resp.json()["enabled_categories"]

    # Confirm it's actually persisted, not just echoed back.
    follow_up = client.get("/settings/scan-filter")
    assert "source_code" in follow_up.json()["enabled_categories"]


def test_updating_minimum_file_size(client):
    resp = client.post("/settings/scan-filter", json={"minimum_file_size_bytes": 1024})
    assert resp.status_code == 200
    assert resp.json()["minimum_file_size_bytes"] == 1024


def test_updating_ignored_folder_names(client):
    resp = client.post("/settings/scan-filter", json={
        "ignored_folder_names": ["node_modules", ".git", "my_custom_folder"],
    })
    assert resp.status_code == 200
    assert "my_custom_folder" in resp.json()["ignored_folder_names"]


def test_settings_change_affects_the_next_real_scan(tmp_path):
    """The whole point of storing this in settings_kv rather than only in
    the in-memory config: a change made through the API must actually
    change what the NEXT scan does, with no restart. This needs its own
    fixture (rather than the shared `client` above) because it must
    rebuild the container fresh on every request -- exactly like
    api/deps.py's real get_container() does per-request in production --
    to prove settings_kv changes actually propagate, rather than reusing
    one long-lived container instance the way the other tests in this
    file do for simplicity."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()
    run_migrations(conn)

    settings = Settings(vault_dir=str(tmp_path / "vault"))

    from app.main import app
    app.dependency_overrides[get_container] = lambda: build_container(conn, settings)

    with TestClient(app) as c:
        watch_dir = tmp_path / "Downloads"
        watch_dir.mkdir()
        (watch_dir / "tiny.txt").write_text("x" * 100)  # 100 bytes, below default 4096 minimum

        status = c.post("/folder-monitor", json={"path": str(watch_dir)}).json()
        assert status["total_files"] == 0  # filtered out by the default minimum size

        c.post("/settings/scan-filter", json={"minimum_file_size_bytes": 50})

        rescan = c.post("/folder-monitor/scan").json()
        assert rescan["files_scanned"] == 1  # now included after lowering the threshold

    app.dependency_overrides.clear()
    conn.close()


def test_installers_are_scannable_by_default_end_to_end(tmp_path):
    """Regression test: config.py's PathGuard-level excluded_extensions
    default used to include .exe/.msi as a blanket exclusion left over
    from before the category-based ScanFilter existed. That silently
    blocked installers at a layer ScanFilter never even sees, even
    though 'installers' is an enabled-by-default category and the spec
    explicitly requires EXE/MSI/ISO to be included by default. This
    proves the full stack (PathGuard + ScanFilter together) actually
    scans them."""
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
        watch_dir = tmp_path / "Downloads"
        watch_dir.mkdir()
        (watch_dir / "installer.exe").write_text("exe content padded out\n" * 300)
        (watch_dir / "setup.msi").write_text("msi content padded out\n" * 300)
        (watch_dir / "disk.iso").write_text("iso content padded out\n" * 300)

        status = c.post("/folder-monitor", json={"path": str(watch_dir)}).json()
        assert status["total_files"] == 3

    app.dependency_overrides.clear()
    conn.close()
