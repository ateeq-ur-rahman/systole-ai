from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.container import Container

router = APIRouter(prefix="/drives", tags=["drives"])


@router.get("")
def list_drives(container: Container = Depends(get_container)):
    rows = container.drive_repo.list_all()
    return [dict(r) for r in rows]


@router.post("/refresh")
def refresh_drives(container: Container = Depends(get_container)):
    """Re-discover drives without doing a full file scan -- fast, used to
    refresh capacity/health numbers on the dashboard."""
    drives = container.drive_discovery.discover()
    for drive in drives:
        container.drive_repo.upsert(drive)
    container.conn.commit()
    return [dict(r) for r in container.drive_repo.list_all()]
