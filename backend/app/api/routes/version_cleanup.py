"""
/version-cleanup -- the Version Cleanup Agent's API surface.

Same singular-active-folder shape as /folder-monitor: one folder watched
for named version patterns at a time. Transaction handling lives inside
VersionCleanupAgent itself (commits/rolls back on every code path), for
the same reason as FolderMonitorAgent -- this agent is also invoked
directly from run.py's scheduler tick and real-time watcher, not just
from HTTP requests.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents.version_cleanup import VersionCleanupError
from app.api.deps import get_container
from app.api.schemas import (
    VersionCleanupSetRequest, VersionCleanupSettingsRequest, VersionGroupConfirmRequest,
)
from app.container import Container

router = APIRouter(prefix="/version-cleanup", tags=["version-cleanup"])


@router.get("")
def get_status(container: Container = Depends(get_container)):
    return container.version_cleanup.get_status()


@router.post("")
def set_folder(request: VersionCleanupSetRequest, container: Container = Depends(get_container)):
    try:
        return container.version_cleanup.set_folder(
            request.path, request.scan_interval_seconds,
            request.automatic_cleanup, request.move_to_safe_vault,
        )
    except VersionCleanupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("")
def remove_folder(container: Container = Depends(get_container)):
    container.version_cleanup.remove()
    return {"active": False}


@router.post("/scan")
def scan_now(container: Container = Depends(get_container)):
    try:
        result = container.version_cleanup.run_cycle(is_initial=True)
    except VersionCleanupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result.__dict__


@router.post("/pause")
def pause(container: Container = Depends(get_container)):
    try:
        return container.version_cleanup.pause()
    except VersionCleanupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/resume")
def resume(container: Container = Depends(get_container)):
    try:
        return container.version_cleanup.resume()
    except VersionCleanupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings")
def update_settings(request: VersionCleanupSettingsRequest, container: Container = Depends(get_container)):
    active = container.version_cleanup_folder_repo.get_active()
    if not active:
        raise HTTPException(status_code=400, detail="No folder is currently being watched for versions")
    try:
        updates = request.model_dump(exclude_none=True)
        container.version_cleanup_folder_repo.update_settings(active["id"], **updates)
        container.conn.commit()
    except Exception:
        container.conn.rollback()
        raise
    return container.version_cleanup.get_status()


@router.get("/groups")
def list_groups(status: str | None = None, container: Container = Depends(get_container)):
    rows = container.version_group_repo.list_groups(status=status)
    return [dict(r) for r in rows]


@router.get("/groups/{group_id}")
def get_group(group_id: int, container: Container = Depends(get_container)):
    group = container.version_group_repo.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Version group not found")
    members = container.version_group_repo.get_members(group_id)

    suggestion = None
    if group["status"] == "needs_confirmation":
        prediction = container.version_cleanup.suggest_resolution(group_id)
        if prediction is not None:
            suggested_member = members[prediction.chosen_index]
            suggestion = {
                "suggested_full_path": suggested_member["full_path"],
                "confidence": prediction.confidence,
                "reason": prediction.reason,
            }

    return {
        "group": dict(group),
        "members": [dict(m) for m in members],
        "suggestion": suggestion,
    }


@router.post("/groups/{group_id}/confirm")
def confirm_group(group_id: int, request: VersionGroupConfirmRequest,
                   container: Container = Depends(get_container)):
    try:
        return container.version_cleanup.confirm_group(group_id, request.kept_full_path)
    except VersionCleanupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
