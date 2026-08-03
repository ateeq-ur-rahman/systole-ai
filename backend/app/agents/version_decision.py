"""
Version Decision Engine

Given a group of files/folders that the Version Name Parser has grouped
together as "versions of the same thing," decides which one to keep.

Priority chain (first tier that narrows to exactly one member wins):
    1. Latest Modified Time
    2. Latest Created Time
    3. Highest Version Number
    4. Largest File Size
    5. Preferred Folder Priority

Critically: if the group is STILL tied after all five tiers, this engine
refuses to guess. It returns needs_confirmation=True with no kept member,
matching the product's explicit safety requirement -- "if there is
uncertainty, DO NOT DELETE, show 'multiple versions detected, please
confirm.'" This is a deliberate difference from VersionIntelligenceAgent
(used for confirmed-duplicate cleanup elsewhere), which always picks a
final deterministic tiebreaker, because that engine only ever runs on
files already confirmed byte-identical by SHA-256 -- there's no "wrong"
choice there. Here, versions can have genuinely different content, so an
unresolvable tie must stop and ask rather than guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.core.constants import FOLDER_PRIORITY_ORDER
from app.database.models import VersionMember

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class VersionDecision:
    kept: Optional[VersionMember]
    reason: str
    needs_confirmation: bool
    tie_breaks_applied: list[str]


class VersionDecisionEngine:
    def __init__(self, folder_priority_order: list[str] | None = None):
        self._folder_priority = [f.lower() for f in (folder_priority_order or FOLDER_PRIORITY_ORDER)]

    def decide(self, members: list[VersionMember]) -> VersionDecision:
        if not members:
            raise ValueError("decide() requires at least one member")
        if len(members) == 1:
            return VersionDecision(members[0], "only_version", False, [])

        pool = list(members)
        trail: list[str] = []

        pool, applied = self._narrow(pool, key=self._modified_key, reverse=True)
        if applied:
            trail.append("latest_modified")
        if len(pool) == 1:
            return VersionDecision(pool[0], "latest_modified", False, trail)

        pool, applied = self._narrow(pool, key=self._created_key, reverse=True)
        if applied:
            trail.append("latest_created")
        if len(pool) == 1:
            return VersionDecision(pool[0], "latest_created", False, trail)

        pool, applied = self._narrow(pool, key=self._version_number_key, reverse=True)
        if applied:
            trail.append("highest_version_number")
        if len(pool) == 1:
            return VersionDecision(pool[0], "highest_version_number", False, trail)

        pool, applied = self._narrow(pool, key=lambda m: m.size_bytes, reverse=True)
        if applied:
            trail.append("largest_size")
        if len(pool) == 1:
            return VersionDecision(pool[0], "largest_size", False, trail)

        pool, applied = self._narrow(pool, key=self._folder_priority_key, reverse=False)
        if applied:
            trail.append("preferred_folder")
        if len(pool) == 1:
            return VersionDecision(pool[0], "preferred_folder", False, trail)

        # Every tier exhausted and still tied -- refuse to guess.
        return VersionDecision(None, "uncertain", True, trail)

    # -- key extractors -----------------------------------------------

    @staticmethod
    def _parse_ts(value: str | None) -> datetime:
        if not value:
            return _EPOCH
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return _EPOCH

    def _modified_key(self, m: VersionMember):
        return self._parse_ts(m.modified_time)

    def _created_key(self, m: VersionMember):
        return self._parse_ts(m.created_time)

    @staticmethod
    def _version_number_key(m: VersionMember):
        # A member with no parseable version number ranks below any
        # explicitly numbered member at this tier (but may still win on
        # an earlier tier like modified time).
        return m.version_number if m.version_number is not None else -1

    def _folder_priority_key(self, m: VersionMember):
        path_lower = m.full_path.lower()
        for idx, tier in enumerate(self._folder_priority):
            if tier in path_lower:
                return idx
        return len(self._folder_priority)

    # -- narrowing helper -----------------------------------------------

    @staticmethod
    def _narrow(pool: list[VersionMember], key, reverse: bool) -> tuple[list[VersionMember], bool]:
        if len(pool) <= 1:
            return pool, False
        best = max(pool, key=key) if reverse else min(pool, key=key)
        best_value = key(best)
        narrowed = [m for m in pool if key(m) == best_value]
        return narrowed, len(narrowed) < len(pool)
