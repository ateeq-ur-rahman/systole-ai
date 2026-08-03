"""
Safe Cleanup Agent

Executes cleanup decisions produced by Duplicate Detection + Version
Intelligence. This is the only agent with write/move access to the user's
files, and it enforces multiple independent safety layers before ever
touching disk:

  1. PathGuard.is_modifiable() -- protected dirs, locked files, running
     executables, never-delete extensions.
  2. The candidate must be a confirmed non-survivor member of a
     duplicate_group (never an arbitrary path).
  3. Files are always MOVED to the Safe Vault (or Recycle Bin), never
     unlinked directly -- see utils/safe_vault.py.
  4. Every move is recorded in cleanup_history + safe_vault so it can be
     undone via restore()/restore_all()/rollback_scan().
"""
from __future__ import annotations

import logging

from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.vault_repository import VaultRepository
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault

logger = logging.getLogger("systole.safe_cleanup")


class CleanupOutcome:
    def __init__(self):
        self.moved: list[dict] = []
        self.skipped: list[dict] = []
        self.bytes_reclaimed = 0


class SafeCleanupAgent:
    def __init__(self, file_repo: FileRepository, dup_repo: DuplicateRepository,
                 vault_repo: VaultRepository, vault: SafeVault, guard: PathGuard,
                 retention_days: int = 30, destination: str = "safe_vault"):
        self._file_repo = file_repo
        self._dup_repo = dup_repo
        self._vault_repo = vault_repo
        self._vault = vault
        self._guard = guard
        self._retention_days = retention_days
        self._destination = destination

    def clean_group(self, group_id: int) -> CleanupOutcome:
        outcome = CleanupOutcome()
        group = self._dup_repo.get_group(group_id)
        if not group:
            raise ValueError(f"No duplicate group with id={group_id}")

        members = self._dup_repo.get_members(group_id)
        for member in members:
            if member["is_survivor"]:
                continue  # never touch the file Version Intelligence selected to keep
            if member["selection_reason"] == "hardlink_of_survivor":
                # Same physical data as the survivor (hardlink) -- moving
                # this path away reclaims zero disk space while the
                # survivor's link keeps the data alive, so we leave it in
                # place rather than surprise the user by removing a link
                # they may be relying on for no storage benefit.
                outcome.skipped.append({
                    "path": member["full_path"],
                    "reason": "hardlink of the kept file -- no space to reclaim, left in place",
                })
                continue
            self._clean_single_file(member, group_id, outcome)

        if outcome.moved:
            self._dup_repo.set_status(group_id, "cleaned")
        return outcome

    def clean_groups(self, group_ids: list[int]) -> CleanupOutcome:
        combined = CleanupOutcome()
        for group_id in group_ids:
            result = self.clean_group(group_id)
            combined.moved.extend(result.moved)
            combined.skipped.extend(result.skipped)
            combined.bytes_reclaimed += result.bytes_reclaimed
        return combined

    def _clean_single_file(self, member_row, group_id: int, outcome: CleanupOutcome) -> None:
        path = member_row["full_path"]
        check = self._guard.is_modifiable(path)
        if not check.allowed:
            outcome.skipped.append({"path": path, "reason": check.reason})
            logger.info("Skipped cleanup for %s: %s", path, check.reason)
            return

        if self._destination == "recycle_bin":
            move_result = self._vault.move_to_recycle_bin(path)
            action = "moved_to_recycle_bin"
        else:
            move_result = self._vault.move_to_vault(path)
            action = "moved_to_vault"

        if not move_result.success:
            outcome.skipped.append({"path": path, "reason": move_result.error})
            logger.warning("Move failed for %s: %s", path, move_result.error)
            return

        self._file_repo.mark_deleted(member_row["id"])

        cleanup_id = self._vault_repo.record_cleanup(
            file_id=member_row["id"], group_id=group_id, original_path=path,
            vault_path=move_result.destination_path, action=action,
            size_bytes=member_row["size_bytes"], reason=member_row["selection_reason"],
        )

        if action == "moved_to_vault":
            self._vault_repo.record_vault_entry(
                cleanup_history_id=cleanup_id, vault_path=move_result.destination_path,
                original_path=path, size_bytes=member_row["size_bytes"],
                retention_days=self._retention_days,
            )

        outcome.moved.append({
            "path": path, "destination": move_result.destination_path,
            "cleanup_id": cleanup_id, "size_bytes": member_row["size_bytes"],
        })
        outcome.bytes_reclaimed += member_row["size_bytes"]

    # -- restore / rollback -----------------------------------------------

    def restore(self, cleanup_id: int) -> bool:
        record = self._vault_repo.get_cleanup_by_id(cleanup_id)
        if not record or record["restored_at"]:
            return False
        if record["action"] == "moved_to_recycle_bin":
            logger.info("Recycle bin restores must be performed via Windows Explorer for %s",
                        record["original_path"])
            return False

        result = self._vault.restore(record["vault_path"], record["original_path"])
        if not result.success:
            logger.warning("Restore failed for cleanup_id=%s: %s", cleanup_id, result.error)
            return False

        self._vault_repo.mark_restored(cleanup_id)
        if record["file_id"]:
            self._file_repo.mark_restored(record["file_id"], result.destination_path)
        return True

    def restore_all(self) -> dict:
        entries = self._vault_repo.list_vault(include_restored=False)
        restored, failed = 0, 0
        for entry in entries:
            if self.restore(entry["cleanup_history_id"]):
                restored += 1
            else:
                failed += 1
        return {"restored": restored, "failed": failed}

    def purge_expired(self) -> int:
        """Permanently remove vault entries past their retention window.
        This is the ONLY code path in the system allowed to permanently
        delete data, and it only ever acts on files already sitting inside
        Systole's own vault directory -- never on the user's live tree."""
        purged = 0
        for entry in self._vault_repo.expired_entries():
            result = self._vault.purge(entry["vault_path"])
            if result.success:
                purged += 1
        return purged
