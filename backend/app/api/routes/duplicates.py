from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container
from app.container import Container

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


@router.get("")
def list_duplicate_groups(status: Optional[str] = None, container: Container = Depends(get_container)):
    groups = container.dup_repo.list_groups(status=status)
    return [dict(g) for g in groups]


@router.get("/{group_id}")
def get_duplicate_group(group_id: int, container: Container = Depends(get_container)):
    group = container.dup_repo.get_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Duplicate group not found")
    members = container.dup_repo.get_members(group_id)
    return {"group": dict(group), "members": [dict(m) for m in members]}


@router.post("/detect")
def run_duplicate_detection(container: Container = Depends(get_container)):
    """Re-run duplicate detection against the current files table without
    performing a fresh filesystem scan."""
    groups = container.duplicate_detection.detect()
    container.conn.commit()
    return {"groups_found": len(groups)}
