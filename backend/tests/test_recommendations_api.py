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


def test_dismissed_starts_empty(client):
    resp = client.get("/recommendations/dismissed")
    assert resp.status_code == 200
    assert resp.json()["dismissed"] == []


def test_dismiss_then_list_shows_it(client):
    client.post("/recommendations/dismiss", json={"category": "archive"})
    resp = client.get("/recommendations/dismissed")
    categories = [d["category"] for d in resp.json()["dismissed"]]
    assert "archive" in categories


def test_dismiss_with_snooze_is_reflected(client):
    resp = client.post("/recommendations/dismiss", json={"category": "installer", "snooze_days": 14})
    assert resp.status_code == 200

    listed = client.get("/recommendations/dismissed").json()["dismissed"]
    entry = next(d for d in listed if d["category"] == "installer")
    assert entry["expires_at"] is not None  # a snooze has an expiry, unlike a permanent dismissal


def test_undismiss_removes_from_list(client):
    client.post("/recommendations/dismiss", json={"category": "archive"})
    client.post("/recommendations/undismiss", json={"category": "archive"})

    categories = [d["category"] for d in client.get("/recommendations/dismissed").json()["dismissed"]]
    assert "archive" not in categories
