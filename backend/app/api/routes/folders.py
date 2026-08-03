"""
/folders — lets the user point Systole at any specific folder (not just a
whole drive) to scan and monitor for duplicates, e.g. "C:\\Users\\alice\\
Projects" or "D:\\Photos". This is the entry point for the "give it a
folder path and it monitors + dedupes just that folder" flow.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container
from app.api.schemas import FolderCreateRequest
from app.container import Container
from app.database.models import WatchedFolder
from app.services.scan_service import ScanService

router = APIRouter(prefix="/folders", tags=["folders"])


def _resolve_drive_id(container: Container, path: str) -> int | None:
    """Best-effort match of a folder path to an already-discovered drive,
    so files scanned under it link back to drives.<id> like everything
    else. Falls back to None (the files table allows a NULL drive_id) if
    no drive has been discovered yet -- run a drive scan/refresh first for
    full linkage, but it's not required to add or scan a folder."""
    norm = os.path.splitdrive(path)[0].lower()  # e.g. "c:" from "C:\Users\..."
    if not norm:
        return None
    for drive in container.drive_repo.list_all():
        if drive["letter"].lower().startswith(norm):
            return drive["id"]
    return None


@router.get("")
def list_folders(container: Container = Depends(get_container)):
    rows = container.folder_repo.list_all()
    return [dict(r) for r in rows]


@router.post("")
def add_folder(request: FolderCreateRequest, container: Container = Depends(get_container)):
    path = os.path.normpath(request.path)

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail=f"'{path}' is not an accessible folder")

    guard_check = container.guard.is_scannable(path)
    if not guard_check.allowed:
        raise HTTPException(
            status_code=400,
            detail=f"'{path}' can't be watched: {guard_check.reason}. Systole never scans "
                   f"protected Windows system locations, even on request.",
        )

    drive_id = _resolve_drive_id(container, path)
    folder_id = container.folder_repo.add(WatchedFolder(
        id=None, path=path, label=request.label, drive_id=drive_id, enabled=request.enabled,
    ))
    container.conn.commit()

    return dict(container.folder_repo.get_by_id(folder_id))


@router.delete("/{folder_id}")
def remove_folder(folder_id: int, container: Container = Depends(get_container)):
    folder = container.folder_repo.get_by_id(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Watched folder not found")
    container.folder_repo.remove(folder_id)
    container.conn.commit()
    return {"removed": folder_id}


@router.post("/{folder_id}/enable")
def enable_folder(folder_id: int, enabled: bool = True, container: Container = Depends(get_container)):
    folder = container.folder_repo.get_by_id(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Watched folder not found")
    container.folder_repo.set_enabled(folder_id, enabled)
    container.conn.commit()
    return dict(container.folder_repo.get_by_id(folder_id))


@router.post("/{folder_id}/scan")
def scan_folder(folder_id: int, container: Container = Depends(get_container)):
    """Scan this one folder now and run duplicate detection immediately --
    this is the main action behind 'give it a path and it dedupes that
    folder' rather than waiting for the next scheduled/real-time pass."""
    folder = container.folder_repo.get_by_id(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Watched folder not found")

    if not os.path.isdir(folder["path"]):
        raise HTTPException(status_code=400, detail=f"'{folder['path']}' is no longer accessible")

    service = ScanService(container)
    try:
        return service.scan_folder(folder_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
