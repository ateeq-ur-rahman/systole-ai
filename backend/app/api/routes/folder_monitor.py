"""
/folder-monitor -- the Folder Monitor Agent's API surface.

Deliberately singular: there's one active monitored folder, not a list.
POST replaces whatever was previously selected (matching the product
requirement that selecting a new folder makes it *the* monitored folder).

Transaction handling: FolderMonitorAgent's mutating methods (set_folder,
run_cycle, pause, resume, remove) commit or roll back internally on every
code path, including exceptions -- so these routes don't need to manage
the connection themselves. That's deliberate: this same agent is also
invoked directly from run.py's background scheduler tick and real-time
watcher, outside any HTTP request at all, so the transaction safety can't
live at the route layer alone.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents.folder_monitor import FolderMonitorError
from app.api.deps import get_container
from app.api.schemas import MonitorFolderSetRequest, MonitorFolderSettingsRequest
from app.container import Container

router = APIRouter(prefix="/folder-monitor", tags=["folder-monitor"])


@router.get("")
def get_status(container: Container = Depends(get_container)):
    return container.folder_monitor.get_status()


@router.post("")
def set_folder(request: MonitorFolderSetRequest, container: Container = Depends(get_container)):
    try:
        return container.folder_monitor.set_folder(request.path, request.scan_interval_seconds)
    except FolderMonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("")
def remove_folder(container: Container = Depends(get_container)):
    container.folder_monitor.remove()
    return {"active": False}


@router.post("/scan")
def scan_now(container: Container = Depends(get_container)):
    """Manual verification scan right now, bypassing the 2-minute
    schedule -- and bypassing the pause flag too, since an explicit
    request to scan now is not the same as the automatic background
    cadence the user paused."""
    try:
        result = container.folder_monitor.run_cycle(is_initial=True)
    except FolderMonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result.__dict__


@router.post("/pause")
def pause(container: Container = Depends(get_container)):
    try:
        return container.folder_monitor.pause()
    except FolderMonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/resume")
def resume(container: Container = Depends(get_container)):
    try:
        return container.folder_monitor.resume()
    except FolderMonitorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings")
def update_settings(request: MonitorFolderSettingsRequest, container: Container = Depends(get_container)):
    active = container.monitored_folder_repo.get_active()
    if not active:
        raise HTTPException(status_code=400, detail="No folder is currently being monitored")

    try:
        updates = request.model_dump(exclude_none=True)
        container.monitored_folder_repo.update_settings(active["id"], **updates)
        container.conn.commit()
    except Exception:
        container.conn.rollback()
        raise
    return container.folder_monitor.get_status()
