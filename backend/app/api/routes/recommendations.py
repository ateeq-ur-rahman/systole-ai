"""
Recommendations API

Backs the AI's memory of dismissed recommendation categories -- see
app/repositories/dismissal_repository.py for the reasoning. Deliberately
minimal: the actual recommendation *computation* stays where it already
is (client-side, from duplicate group data already fetched), this only
tracks which categories the user has said "not now" or "never" to.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_container
from app.container import Container

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class DismissRequest(BaseModel):
    category: str
    snooze_days: int | None = None  # None = dismiss indefinitely


@router.get("/dismissed")
def list_dismissed(container: Container = Depends(get_container)):
    rows = container.dismissal_repo.list_active()
    return {"dismissed": [dict(r) for r in rows]}


@router.post("/dismiss")
def dismiss(request: DismissRequest, container: Container = Depends(get_container)):
    container.dismissal_repo.dismiss(request.category, request.snooze_days)
    return {"dismissed": True, "category": request.category}


@router.post("/undismiss")
def undismiss(request: DismissRequest, container: Container = Depends(get_container)):
    container.dismissal_repo.undismiss(request.category)
    return {"dismissed": False, "category": request.category}
