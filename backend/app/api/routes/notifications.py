from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.container import Container

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(limit: int = 50, container: Container = Depends(get_container)):
    rows = container.notification_repo.list_recent(limit=limit)
    return {
        "notifications": [dict(r) for r in rows],
        "unread_count": container.notification_repo.unread_count(),
    }


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, container: Container = Depends(get_container)):
    container.notification_repo.mark_read(notification_id)
    container.conn.commit()
    return {"marked_read": notification_id}


@router.post("/read-all")
def mark_all_read(container: Container = Depends(get_container)):
    container.notification_repo.mark_all_read()
    container.conn.commit()
    return {"marked_all_read": True}
