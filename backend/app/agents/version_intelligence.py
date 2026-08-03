"""
Version Intelligence Agent

Given a set of files that Duplicate Detection has already confirmed are
byte-for-byte identical (matching SHA-256), decide which single copy
should survive and which are redundant. This module NEVER decides
"are these duplicates" -- that's solely the Hash Engine's job. It only
answers "given identical content, which copy do we keep?"

Priority chain (first tiebreaker that produces a unique winner wins):
  1. Latest Modified Timestamp
  2. Latest Created Timestamp
  3. Latest Access Timestamp
  4. Preferred Folder Priority (Documents > Desktop > Projects > Pictures >
     Videos > Downloads > Temp)
  5. Shortest path
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.database.models import FileRecord

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class SurvivorDecision:
    survivor: FileRecord
    reason: str
    tie_breaks_applied: list[str]


class VersionIntelligenceAgent:
    def __init__(self, folder_priority_order: list[str] | None = None):
        # Lower index = higher priority.
        self._folder_priority = [f.lower() for f in (folder_priority_order or [
            "documents", "desktop", "projects", "pictures", "videos", "downloads", "temp",
        ])]

    def select_survivor(self, candidates: list[FileRecord]) -> SurvivorDecision:
        if not candidates:
            raise ValueError("select_survivor requires at least one candidate")
        if len(candidates) == 1:
            return SurvivorDecision(candidates[0], "only_copy", [])

        pool = list(candidates)
        trail: list[str] = []

        pool, applied = self._narrow(pool, key=self._modified_key, reverse=True)
        if applied:
            trail.append("latest_modified")
        if len(pool) == 1:
            return SurvivorDecision(pool[0], "latest_modified", trail)

        pool, applied = self._narrow(pool, key=self._created_key, reverse=True)
        if applied:
            trail.append("latest_created")
        if len(pool) == 1:
            return SurvivorDecision(pool[0], "latest_created", trail)

        pool, applied = self._narrow(pool, key=self._accessed_key, reverse=True)
        if applied:
            trail.append("latest_accessed")
        if len(pool) == 1:
            return SurvivorDecision(pool[0], "latest_accessed", trail)

        pool, applied = self._narrow(pool, key=self._folder_priority_key, reverse=False)
        if applied:
            trail.append("preferred_folder")
        if len(pool) == 1:
            winning_folder = self._matched_folder_label(pool[0])
            reason = f"preferred_folder:{winning_folder}" if winning_folder else "preferred_folder"
            return SurvivorDecision(pool[0], reason, trail)

        pool, applied = self._narrow(pool, key=lambda f: len(f.full_path), reverse=False)
        if applied:
            trail.append("shortest_path")
        # Final deterministic tiebreaker if everything above is still tied
        # (e.g. two literal hardlinks with identical everything): sort by
        # full_path lexicographically so results are stable across runs.
        pool.sort(key=lambda f: f.full_path)
        return SurvivorDecision(pool[0], "shortest_path" if applied else "deterministic_tiebreak", trail)

    # -- key extractors -----------------------------------------------

    @staticmethod
    def _parse_ts(value: str | None) -> datetime:
        if not value:
            return _EPOCH
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return _EPOCH

    def _modified_key(self, f: FileRecord):
        return self._parse_ts(f.modified_time)

    def _created_key(self, f: FileRecord):
        return self._parse_ts(f.created_time)

    def _accessed_key(self, f: FileRecord):
        return self._parse_ts(f.accessed_time)

    def _folder_priority_key(self, f: FileRecord):
        folder_lower = (f.folder or "").lower()
        for idx, tier in enumerate(self._folder_priority):
            if tier in folder_lower:
                return idx
        return len(self._folder_priority)  # unranked folders sort last

    def _matched_folder_label(self, f: FileRecord) -> str | None:
        folder_lower = (f.folder or "").lower()
        for tier in self._folder_priority:
            if tier in folder_lower:
                return tier.capitalize()
        return None

    # -- narrowing helper -----------------------------------------------

    @staticmethod
    def _narrow(pool: list[FileRecord], key, reverse: bool) -> tuple[list[FileRecord], bool]:
        """Reduce `pool` to only the members sharing the best key value.
        Returns (narrowed_pool, whether_this_step_actually_broke_a_tie)."""
        if len(pool) <= 1:
            return pool, False
        best = max(pool, key=key) if reverse else min(pool, key=key)
        best_value = key(best)
        narrowed = [f for f in pool if key(f) == best_value]
        return narrowed, len(narrowed) < len(pool)
