from __future__ import annotations

import os
import sqlite3
import time
from unittest import mock

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


def _touch(path, seconds_ago):
    ts = time.time() - seconds_ago
    os.utime(path, (ts, ts))


def test_no_active_folder_initially(client):
    resp = client.get("/version-cleanup")
    assert resp.status_code == 200
    assert resp.json() == {"active": False}


def test_full_version_cleanup_lifecycle_via_api(client, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()

    base = watch / "systole-storage-manager"
    base.mkdir()
    _touch(base, seconds_ago=800)

    newest = watch / "systole-storage-manager (7)"
    newest.mkdir()
    _touch(newest, seconds_ago=10)

    resp = client.post("/version-cleanup", json={"path": str(watch)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["path"] == os.path.normpath(str(watch))
    assert body["version_groups_cleaned"] == 1
    assert body["storage_saved_bytes"] >= 0

    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["systole-storage-manager (7)"]

    status = client.get("/version-cleanup").json()
    assert status["path"] == os.path.normpath(str(watch))


def test_reject_protected_path_via_api(client, tmp_path):
    fake_system = tmp_path / "Windows" / "System32"
    fake_system.mkdir(parents=True)
    resp = client.post("/version-cleanup", json={"path": str(fake_system)})
    assert resp.status_code == 400


def test_pause_and_resume_via_api(client, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    (watch / "a.txt").write_text("hi")

    client.post("/version-cleanup", json={"path": str(watch)})

    pause_resp = client.post("/version-cleanup/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["paused"] is True

    resume_resp = client.post("/version-cleanup/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["paused"] is False


def test_manual_scan_now_endpoint(client, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    (watch / "a.txt").write_text("hi")

    client.post("/version-cleanup", json={"path": str(watch)})
    (watch / "b.txt").write_text("world")

    scan_resp = client.post("/version-cleanup/scan")
    assert scan_resp.status_code == 200
    assert "entries_scanned" in scan_resp.json()


def test_remove_folder_via_api(client, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    (watch / "a.txt").write_text("hi")

    client.post("/version-cleanup", json={"path": str(watch)})
    remove_resp = client.delete("/version-cleanup")
    assert remove_resp.status_code == 200

    status = client.get("/version-cleanup").json()
    assert status == {"active": False}


def test_update_settings_via_api(client, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    (watch / "a.txt").write_text("hi")

    client.post("/version-cleanup", json={"path": str(watch)})

    resp = client.post("/version-cleanup/settings", json={
        "scan_interval_seconds": 300, "automatic_cleanup": False,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["scan_interval_seconds"] == 300
    assert body["automatic_cleanup"] is False


def test_needs_confirmation_group_listed_and_confirmable_via_api(tmp_path, monkeypatch):
    """This test needs direct access to the container (to force a
    deterministic tie on the underlying agent), which the shared `client`
    fixture doesn't expose -- so it builds its own client+container here,
    same pattern as test_settings_change_affects_the_next_real_scan
    above."""
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

    watch = tmp_path / "Downloads"
    watch.mkdir()
    a = watch / "Project_backup"
    b = watch / "Project_old"
    a.write_text("identical size content!!")
    b.write_text("identical size content!!")

    # os.utime() cannot reliably force a genuine cross-tier tie: it only
    # sets access/modified time. On Linux, st_ctime happens to also get
    # bumped by utime() (coincidentally colliding), but on Windows
    # st_ctime is the file's real, untouchable creation timestamp -- two
    # sequentially-created files genuinely differ there, silently
    # resolving what should be an unresolvable tie. Directly controlling
    # what the scan reports sidesteps this platform difference entirely
    # (same fix as tests/test_version_cleanup_agent.py's
    # _force_genuine_tie helper).
    from app.database.models import VersionMember
    from app.utils.version_naming import VersionNameParser

    parser = VersionNameParser()
    same_ts = "2024-01-01T00:00:00"
    members = []
    for path in (a, b):
        parsed = parser.parse(path.stem)
        members.append(VersionMember(
            full_path=str(path), is_folder=False, base_name=parsed.base_name,
            version_label=parsed.version_label, version_number=parsed.version_number,
            size_bytes=path.stat().st_size, modified_time=same_ts, created_time=same_ts,
        ))
    group_key = members[0].base_name.lower()
    monkeypatch.setattr(
        container.version_cleanup, "_scan_and_group", lambda folder_path: {group_key: members}
    )

    with TestClient(app) as client:
        status = client.post("/version-cleanup", json={"path": str(watch)}).json()
        assert status["version_groups_needing_confirmation"] == 1

        groups = client.get("/version-cleanup/groups", params={"status": "needs_confirmation"}).json()
        assert len(groups) == 1
        group_id = groups[0]["id"]

        detail = client.get(f"/version-cleanup/groups/{group_id}").json()
        assert len(detail["members"]) == 2

        confirm_resp = client.post(
            f"/version-cleanup/groups/{group_id}/confirm", json={"kept_full_path": str(a)}
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["version_groups_cleaned"] == 1

        remaining = sorted(p.name for p in watch.iterdir())
        assert remaining == ["Project_backup"]

    app.dependency_overrides.clear()
    conn.close()


def test_learned_suggestion_appears_after_enough_confirmed_ties(tmp_path):
    """Full end-to-end proof through the real API: after this user
    consistently resolves several genuine ties the same way (always
    keeping the "_backup" version over the "_old" version, when both
    otherwise tie on every real decision tier), a brand new, never-seen
    tie with the same pattern should come back from the API with a
    suggestion pointing at the "_backup" copy -- real learning,
    exercised through the actual HTTP layer, not just the learner in
    isolation.

    Both candidates deliberately live in the SAME folder with identical
    size/timestamps/no version number, so they're a genuine tie under
    the real 5-tier decision engine too (folder priority, size, and
    time all tie) -- the only thing that differs is the naming pattern
    itself, which the deterministic engine doesn't use as a tiebreaker
    but the learner can."""
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

    from app.database.models import VersionMember

    def make_tie(index: int):
        watch = tmp_path / f"Watch{index}"
        watch.mkdir()
        backup = watch / f"Report{index}_backup.pdf"
        old = watch / f"Report{index}_old.pdf"
        backup.write_text("content")
        old.write_text("content")

        same_ts = "2024-01-01T00:00:00"
        members = [
            VersionMember(full_path=str(backup), is_folder=False, base_name=f"report{index}",
                          version_label="backup_suffix", version_number=None,
                          size_bytes=7, modified_time=same_ts, created_time=same_ts),
            VersionMember(full_path=str(old), is_folder=False, base_name=f"report{index}",
                          version_label="old_suffix", version_number=None,
                          size_bytes=7, modified_time=same_ts, created_time=same_ts),
        ]
        return watch, members, str(backup)

    with TestClient(app) as client:
        # Train: 6 separate ties, always keeping the "_backup" version.
        for i in range(6):
            watch, members, backup_path = make_tie(i)
            with mock.patch.object(
                container.version_cleanup, "_scan_and_group",
                return_value={f"report{i}": members},
            ):
                client.post("/version-cleanup", json={"path": str(watch)})

            groups = client.get("/version-cleanup/groups", params={"status": "needs_confirmation"}).json()
            assert len(groups) == 1, f"iteration {i}: expected a genuine tie, got {groups}"
            group_id = groups[0]["id"]
            client.post(f"/version-cleanup/groups/{group_id}/confirm", json={"kept_full_path": backup_path})

        # A brand new, never-seen tie with the same underlying pattern.
        watch, members, backup_path = make_tie(99)
        with mock.patch.object(
            container.version_cleanup, "_scan_and_group",
            return_value={"report99": members},
        ):
            client.post("/version-cleanup", json={"path": str(watch)})

        groups = client.get("/version-cleanup/groups", params={"status": "needs_confirmation"}).json()
        new_group_id = groups[0]["id"]
        detail = client.get(f"/version-cleanup/groups/{new_group_id}").json()

        assert detail["suggestion"] is not None
        assert detail["suggestion"]["suggested_full_path"] == backup_path
        assert detail["suggestion"]["confidence"] >= 0.55
        assert "backup" in detail["suggestion"]["reason"].lower()

    app.dependency_overrides.clear()
    conn.close()
