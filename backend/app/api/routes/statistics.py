from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_container
from app.container import Container
from app.services.statistics_service import StatisticsService

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("")
def get_statistics(container: Container = Depends(get_container)):
    return StatisticsService(container).snapshot()


@router.get("/optimizer")
def get_optimizer_report(container: Container = Depends(get_container)):
    report = container.storage_optimizer.analyze()
    return {
        "duplicate_bytes": report.duplicate_bytes,
        "largest_files": report.largest_files,
        "largest_folders": report.largest_folders,
        "archive_bytes": report.archive_bytes,
        "iso_bytes": report.iso_bytes,
        "installer_bytes": report.installer_bytes,
        "temp_bytes": report.temp_bytes,
        "recommendations": [r.__dict__ for r in report.recommendations],
    }


@router.get("/ask")
def ask_ai(question: str, group_id: int | None = None, container: Container = Depends(get_container)):
    """Natural-language-ish Q&A endpoint mapping to the AI Explanation Agent.
    `question` is matched against a small set of known intents; unrecognized
    questions get a helpful fallback listing what can be asked."""
    agent = container.ai_explanation
    q = question.lower()

    if "why" in q and "full" in q:
        result = agent.why_storage_full()
    elif "where" in q:
        result = agent.where_storage_used()
    elif "which files are duplicate" in q or ("which" in q and "duplicate" in q and "why" not in q and "newest" not in q):
        result = agent.which_files_duplicates()
    elif "why" in q and "duplicate" in q and group_id is not None:
        result = agent.why_are_duplicates(group_id)
    elif "newest" in q and group_id is not None:
        result = agent.which_version_newest(group_id)
    elif "safely delete" in q and group_id is not None:
        result = agent.can_safely_delete(group_id)
    elif "how much" in q or "recover" in q:
        result = agent.how_much_recoverable()
    elif "today" in q or "changes" in q:
        result = agent.explain_todays_changes()
    else:
        return {
            "question": question,
            "answer": "I can answer: why storage is full, where storage is used, "
                      "which files are duplicates, why files are duplicates (needs group_id), "
                      "which version is newest (needs group_id), whether it's safe to delete "
                      "(needs group_id), how much can be recovered, or today's changes.",
            "data": {},
        }

    return {"question": result.question, "answer": result.answer, "data": result.data}
