from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.api.schemas import CleanupRequest
from app.container import Container
from app.services.cleanup_service import CleanupService

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


@router.post("")
def run_cleanup(request: CleanupRequest, container: Container = Depends(get_container)):
    service = CleanupService(container)
    if request.group_ids:
        return service.clean_groups(request.group_ids)
    return service.clean_all_pending()


@router.get("/history")
def cleanup_history(limit: int = 50, container: Container = Depends(get_container)):
    rows = container.vault_repo.get_history(limit=limit)
    return [dict(r) for r in rows]


@router.get("/vault")
def list_vault(include_restored: bool = False, container: Container = Depends(get_container)):
    rows = container.vault_repo.list_vault(include_restored=include_restored)
    return [dict(r) for r in rows]


@router.post("/purge-expired")
def purge_expired(container: Container = Depends(get_container)):
    count = CleanupService(container).purge_expired()
    return {"purged": count}
