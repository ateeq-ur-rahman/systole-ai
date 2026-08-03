from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.api.schemas import ScanFilterSettingsUpdateRequest, SettingsUpdateRequest
from app.container import Container
from app.utils.scan_filter import (
    KV_KEY_ENABLED_CATEGORIES,
    KV_KEY_IGNORED_FOLDER_NAMES,
    KV_KEY_MINIMUM_FILE_SIZE_BYTES,
    CATEGORY_EXTENSIONS,
    ScanFilter,
    load_scan_filter,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings_kv(container: Container = Depends(get_container)):
    cur = container.conn.execute("SELECT key, value FROM settings_kv")
    return {row["key"]: json.loads(row["value"]) for row in cur.fetchall()}


@router.post("")
def update_settings(request: SettingsUpdateRequest, container: Container = Depends(get_container)):
    """Persists user-adjustable settings as key/value overrides. These are
    read back by the scheduler/monitor on next scan cycle; a full restart
    is not required for most values."""
    updates = request.model_dump(exclude_none=True)
    for key, value in updates.items():
        container.conn.execute(
            """INSERT INTO settings_kv (key, value, updated_at) VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')""",
            (key, json.dumps(value)),
        )
    container.conn.commit()
    return {"updated": list(updates.keys())}


@router.get("/scan-filter")
def get_scan_filter_settings(container: Container = Depends(get_container)):
    """Current effective scan-filter configuration (live overrides merged
    with config defaults), plus the full category catalog with example
    extensions -- everything the Settings page needs to render toggle
    switches without hardcoding category names on the frontend."""
    settings = container.settings
    current = load_scan_filter(
        container.conn,
        default_enabled_categories=settings.scan_filter.enabled_categories,
        default_ignored_folder_names=settings.scan_filter.ignored_folder_names,
        default_minimum_file_size_bytes=settings.scan_filter.minimum_file_size_bytes,
    )
    return {
        "enabled_categories": sorted(current.enabled_categories),
        "ignored_folder_names": sorted(current.ignored_folder_names),
        "minimum_file_size_bytes": current.minimum_file_size_bytes,
        "available_categories": [
            {"id": name, "extensions": sorted(exts)}
            for name, exts in sorted(CATEGORY_EXTENSIONS.items())
        ],
    }


@router.post("/scan-filter")
def update_scan_filter_settings(request: ScanFilterSettingsUpdateRequest,
                                 container: Container = Depends(get_container)):
    """Updates live scan-filter overrides. Takes effect starting with the
    next scan cycle for every agent that uses the shared FileScannerAgent
    (general drive scans, Watched Folders, Folder Monitor) -- no restart
    required, since containers (and the ScanFilter they build) are
    reconstructed fresh on every request/scheduler tick."""
    updates = request.model_dump(exclude_none=True)
    key_map = {
        "enabled_categories": KV_KEY_ENABLED_CATEGORIES,
        "ignored_folder_names": KV_KEY_IGNORED_FOLDER_NAMES,
        "minimum_file_size_bytes": KV_KEY_MINIMUM_FILE_SIZE_BYTES,
    }
    for field, kv_key in key_map.items():
        if field in updates:
            container.conn.execute(
                """INSERT INTO settings_kv (key, value, updated_at) VALUES (?, ?, datetime('now'))
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')""",
                (kv_key, json.dumps(updates[field])),
            )
    container.conn.commit()
    return get_scan_filter_settings(container)
