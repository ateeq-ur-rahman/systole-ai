"""
Duplicate Detection Agent

Groups files ONLY by identical SHA-256 hash. This module deliberately
never looks at filename, timestamp, or folder name to decide whether files
are duplicates -- that decision belongs entirely to the Hash Engine's
output. Filenames are used later, by Version Intelligence, only to decide
which identical copy survives -- never to decide if they're duplicates.
"""
from __future__ import annotations

import logging

from app.agents.version_intelligence import VersionIntelligenceAgent
from app.database.models import DuplicateGroup, FileRecord
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository

logger = logging.getLogger("systole.duplicate_detection")


def _row_to_record(row) -> FileRecord:
    return FileRecord(
        id=row["id"], drive_id=row["drive_id"], full_path=row["full_path"],
        filename=row["filename"], extension=row["extension"], folder=row["folder"],
        size_bytes=row["size_bytes"], created_time=row["created_time"],
        modified_time=row["modified_time"], accessed_time=row["accessed_time"],
        owner=row["owner"], permissions=row["permissions"], sha256=row["sha256"],
        hash_computed_at=row["hash_computed_at"], is_deleted=bool(row["is_deleted"]),
        inode_key=row["inode_key"] if "inode_key" in row.keys() else None,
    )


class DuplicateDetectionAgent:
    def __init__(self, file_repo: FileRepository, dup_repo: DuplicateRepository,
                 version_agent: VersionIntelligenceAgent, min_size_bytes: int = 0):
        self._file_repo = file_repo
        self._dup_repo = dup_repo
        self._version_agent = version_agent
        self._min_size_bytes = min_size_bytes

    def detect(self, path_prefix: str | None = None) -> list[DuplicateGroup]:
        """Scan the files table for hash collisions and materialize
        duplicate_groups + duplicate_group_members. Idempotent: re-running
        after a fresh scan simply refreshes existing groups.

        With `path_prefix`, only files under that folder are considered at
        all (used by the Folder Monitor Agent to stay scoped to exactly
        one folder, never surfacing duplicates against the rest of the
        system)."""
        hash_counts = self._file_repo.find_by_hashes_with_counts(self._min_size_bytes, path_prefix)
        groups: list[DuplicateGroup] = []

        for row in hash_counts:
            sha256 = row["sha256"]
            member_rows = self._file_repo.find_by_hash(sha256, path_prefix)
            members = [_row_to_record(r) for r in member_rows]
            if len(members) < 2:
                continue  # hash count changed between queries (rare race) -- skip safely

            decision = self._version_agent.select_survivor(members)
            survivor_inode = decision.survivor.inode_key

            # Reclaimable space accounting: a file that's a HARDLINK to the
            # survivor (same physical data on disk, same inode) contributes
            # zero reclaimable bytes -- moving that path away doesn't free
            # any space while the survivor's link to the same data remains.
            # Without this, hardlinked duplicates would inflate the
            # "storage you can recover" estimate with space that was never
            # actually being duplicated on disk.
            reclaimable = 0
            for member in members:
                if member.id == decision.survivor.id:
                    continue
                if survivor_inode and member.inode_key == survivor_inode:
                    continue  # hardlink sibling of the survivor -- no space to reclaim
                reclaimable += member.size_bytes

            group_id = self._dup_repo.upsert_group(
                sha256=sha256,
                file_count=len(members),
                total_size_bytes=sum(m.size_bytes for m in members),
                reclaimable_bytes=reclaimable,
                survivor_file_id=decision.survivor.id,
            )

            for member in members:
                is_survivor = member.id == decision.survivor.id
                if is_survivor:
                    reason = decision.reason
                elif survivor_inode and member.inode_key == survivor_inode:
                    reason = "hardlink_of_survivor"
                else:
                    reason = "redundant_copy"
                self._dup_repo.add_member(group_id, member.id, is_survivor, reason)

            group = DuplicateGroup(
                id=group_id, sha256=sha256, file_count=len(members),
                total_size_bytes=sum(m.size_bytes for m in members),
                reclaimable_bytes=reclaimable, survivor_file_id=decision.survivor.id,
                members=members,
            )
            groups.append(group)

        logger.info("Duplicate detection complete: %d groups found (scope=%s)",
                    len(groups), path_prefix or "all")
        return groups
