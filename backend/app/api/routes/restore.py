from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container
from app.api.schemas import RestoreRequest
from app.container import Container
from app.services.cleanup_service import CleanupService

router = APIRouter(prefix="/restore", tags=["restore"])


@router.post("")
def restore(request: RestoreRequest, container: Container = Depends(get_container)):
    service = CleanupService(container)
    if request.cleanup_id is not None:
        success = service.restore(request.cleanup_id)
        if not success:
            raise HTTPException(status_code=400, detail="Restore failed or already restored")
        return {"restored": True, "cleanup_id": request.cleanup_id}
    return service.restore_all()
