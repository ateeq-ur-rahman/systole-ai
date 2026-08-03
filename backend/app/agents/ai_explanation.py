"""
AI Explanation Agent

Turns raw scan/duplicate/optimizer data into plain-English answers for the
questions the product spec calls out explicitly:
  - Why is my storage full?
  - Where is my storage being used?
  - Which files are duplicates?
  - Why are these duplicates?
  - Which version is newest?
  - Can I safely delete these?
  - How much storage can I recover?
  - Explain today's storage changes.

This module is intentionally template-based rather than calling out to an
LLM: it needs to be fast, deterministic, fully explainable, and safe to run
with zero external dependencies or network access. It's structured so a
future LLM-backed "AI Assistant" agent can sit in front of it and use these
structured answers as grounded context (avoiding hallucinated claims about
the user's actual files).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.database.models import DuplicateGroup
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.vault_repository import VaultRepository
from app.utils.formatting import human_bytes


@dataclass
class Explanation:
    question: str
    answer: str
    data: dict


class AIExplanationAgent:
    def __init__(self, file_repo: FileRepository, dup_repo: DuplicateRepository,
                 vault_repo: VaultRepository):
        self._file_repo = file_repo
        self._dup_repo = dup_repo
        self._vault_repo = vault_repo

    def why_storage_full(self) -> Explanation:
        totals = self._file_repo.totals()
        dup_bytes = self._dup_repo.total_reclaimable()
        largest = self._file_repo.largest_files(limit=5)

        top_list = ", ".join(f"{r['filename']} ({human_bytes(r['size_bytes'])})" for r in largest)
        answer = (
            f"Your tracked files total {human_bytes(totals['total_bytes'])} across "
            f"{totals['total_files']} files. Of that, {human_bytes(dup_bytes)} is sitting in "
            f"confirmed duplicate copies (verified by content hash, not filename). "
            f"Your largest individual files are: {top_list or 'none tracked yet'}."
        )
        return Explanation("Why is my storage full?", answer, {
            "total_bytes": totals["total_bytes"], "total_files": totals["total_files"],
            "duplicate_bytes": dup_bytes,
        })

    def where_storage_used(self) -> Explanation:
        rows = self._file_repo.largest_files(limit=100000)
        by_folder: dict[str, int] = {}
        for r in rows:
            by_folder[r["folder"]] = by_folder.get(r["folder"], 0) + r["size_bytes"]
        ranked = sorted(by_folder.items(), key=lambda kv: kv[1], reverse=True)[:5]
        breakdown = "; ".join(f"{folder}: {human_bytes(size)}" for folder, size in ranked)
        answer = f"Your largest storage consumers by folder are — {breakdown or 'no data yet'}."
        return Explanation("Where is my storage being used?", answer, {"top_folders": ranked})

    def which_files_duplicates(self, limit: int = 10) -> Explanation:
        groups = self._dup_repo.list_groups(status="pending")[:limit]
        if not groups:
            return Explanation("Which files are duplicates?",
                                "No confirmed duplicates found yet -- run a scan first.", {})
        lines = []
        for g in groups:
            members = self._dup_repo.get_members(g["id"])
            names = ", ".join(m["filename"] for m in members)
            lines.append(f"{names} — {g['file_count']} identical copies, "
                          f"{human_bytes(g['reclaimable_bytes'])} reclaimable")
        answer = "Confirmed duplicate groups (matched by SHA-256 content hash):\n" + "\n".join(lines)
        return Explanation("Which files are duplicates?", answer,
                            {"groups": [g["id"] for g in groups]})

    def why_are_duplicates(self, group_id: int) -> Explanation:
        group = self._dup_repo.get_group(group_id)
        if not group:
            return Explanation("Why are these duplicates?", "Group not found.", {})
        members = self._dup_repo.get_members(group_id)
        answer = (
            f"These {len(members)} files share an identical SHA-256 content hash "
            f"({group['sha256'][:12]}...), meaning their contents are byte-for-byte "
            f"the same regardless of filename, folder, or timestamps. This is the only "
            f"criterion Systole uses to confirm duplicates."
        )
        return Explanation("Why are these duplicates?", answer, {"sha256": group["sha256"]})

    def which_version_newest(self, group_id: int) -> Explanation:
        group = self._dup_repo.get_group(group_id)
        members = self._dup_repo.get_members(group_id)
        survivor = next((m for m in members if m["is_survivor"]), None)
        if not survivor:
            return Explanation("Which version is newest?", "No survivor selected yet.", {})
        answer = (
            f"'{survivor['full_path']}' was selected to keep, based on: "
            f"{survivor['selection_reason']}. All other copies in this group are "
            f"byte-identical, so no data is lost by keeping only this one."
        )
        return Explanation("Which version is newest?", answer,
                            {"survivor_path": survivor["full_path"], "reason": survivor["selection_reason"]})

    def can_safely_delete(self, group_id: int) -> Explanation:
        group = self._dup_repo.get_group(group_id)
        if not group:
            return Explanation("Can I safely delete these?", "Group not found.", {})
        answer = (
            "Yes — the non-survivor copies in this group are confirmed byte-identical to "
            "the file being kept. Systole never deletes permanently: redundant copies are "
            "moved to the Safe Vault first, so you can restore them at any time before the "
            "retention period expires."
        )
        return Explanation("Can I safely delete these?", answer, {"group_id": group_id})

    def how_much_recoverable(self) -> Explanation:
        dup_bytes = self._dup_repo.total_reclaimable()
        answer = f"You can safely recover approximately {human_bytes(dup_bytes)} by cleaning up confirmed duplicate files."
        return Explanation("How much storage can I recover?", answer, {"reclaimable_bytes": dup_bytes})

    def explain_todays_changes(self) -> Explanation:
        history = self._vault_repo.get_history(limit=20)
        if not history:
            return Explanation("Explain today's storage changes.",
                                "No cleanup actions have been recorded yet today.", {})
        moved = [h for h in history if h["action"] in ("moved_to_vault", "moved_to_recycle_bin")]
        restored = [h for h in history if h["action"] == "restored"]
        total_reclaimed = sum(h["size_bytes"] for h in moved)
        answer = (
            f"Today, Systole moved {len(moved)} redundant file(s) to safety, reclaiming "
            f"{human_bytes(total_reclaimed)}, and restored {len(restored)} file(s) on your request."
        )
        return Explanation("Explain today's storage changes.", answer,
                            {"moved": len(moved), "restored": len(restored), "bytes_reclaimed": total_reclaimed})
