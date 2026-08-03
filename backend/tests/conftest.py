from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.database.db import _SCHEMA_PATH
from app.database.migrations import run_migrations


@pytest.fixture
def db_conn():
    """A fresh in-memory SQLite DB with the full schema applied, isolated
    per test."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def tmp_tree(tmp_path: Path):
    """A small real directory tree on disk for scanner/hash/vault tests."""
    docs = tmp_path / "Documents"
    downloads = tmp_path / "Downloads"
    desktop = tmp_path / "Desktop"
    docs.mkdir()
    downloads.mkdir()
    desktop.mkdir()
    return {"root": tmp_path, "documents": docs, "downloads": downloads, "desktop": desktop}
