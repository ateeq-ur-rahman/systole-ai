from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_container
from app.api.schemas import ScanRequest
from app.container import Container
from app.services.scan_service import ScanService

router = APIRouter(prefix="/scan", tags=["scan"])


@router.post("")
def trigger_scan(request: ScanRequest, container: Container = Depends(get_container)):
    service = ScanService(container)
    try:
        if request.folder_id is not None:
            result = service.scan_folder(request.folder_id)
        elif request.drive_letter:
            result = service.scan_single_drive(request.drive_letter)
        elif request.scan_type == "incremental":
            result = service.run_incremental_scan()
        else:
            result = service.run_full_scan()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/history")
def scan_history(limit: int = 20, container: Container = Depends(get_container)):
    cur = container.conn.execute(
        "SELECT * FROM scan_history ORDER BY started_at DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in cur.fetchall()]
