"""
Version Cleanup Agent

Monitors ONE user-selected folder and detects multiple *named* versions
of the same file or folder -- "Project", "Project (1)", "Project_v2",
"Copy of Project" -- keeping only the newest and moving the rest to the
Safe Vault. This is deliberately independent from both the Folder
Monitor Agent (content-hash duplicate detection) and Watched Folders:
here the grouping signal is the *name pattern*, not SHA-256, because
versions in this sense may genuinely have different content (that's the
whole point of a version).

Workflow per cycle:
  1. List the folder's immediate (non-recursive) contents -- files and
     subfolders alike.
  2. Parse each name with VersionNameParser to find a base name + version
     marker. Files are grouped by (base_name, extension) so a "Report.pdf"
     is never grouped with an unrelated "Report.docx"; folders are
     grouped by base_name alone.
  3. Any group with 2+ members is a genuine version group. Score it with
     VersionDecisionEngine.
  4. If the engine is confident, keep the winner and move every other
     member to the Safe Vault (when automatic cleanup + move-to-vault are
     both enabled -- both default on, but either can be turned off from
     settings without disabling the other).
  5. If the engine can't decide (every tiebreak tier still tied), NOTHING
     is moved. The group is recorded as needs_confirmation and surfaced
     for the user to resolve manually via confirm_group().
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.agents.version_decision import VersionDecisionEngine
from app.database.models import Notification, VersionCleanupFolder, VersionMember
from app.repositories.notification_repository import NotificationRepository
from app.repositories.vault_repository import VaultRepository
from app.repositories.version_cleanup_folder_repository import VersionCleanupFolderRepository
from app.repositories.version_group_repository import VersionGroupRepository
from app.utils.formatting import human_bytes
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault
from app.utils.version_naming import VersionNameParser
from app.utils.winpath import is_reparse_point

logger = logging.getLogger("systole.version_cleanup")


@dataclass
class VersionCycleResult:
    entries_scanned: int
    groups_detected: int
    groups_cleaned: int
    groups_needing_confirmation: int
    files_moved: int
    bytes_reclaimed: int
    errors: int


class VersionCleanupError(ValueError):
    """User-facing validation failures -- API routes turn this into a 400."""


class VersionCleanupAgent:
    def __init__(self, conn, folder_repo: VersionCleanupFolderRepository,
                 group_repo: VersionGroupRepository, vault_repo: VaultRepository,
                 notification_repo: NotificationRepository, guard: PathGuard, vault: SafeVault,
                 parser: VersionNameParser | None = None,
                 decision_engine: VersionDecisionEngine | None = None,
                 retention_days: int = 30):
        self._conn = conn
        self._folder_repo = folder_repo
        self._group_repo = group_repo
        self._vault_repo = vault_repo
        self._notify_repo = notification_repo
        self._guard = guard
        self._vault = vault
        self._parser = parser or VersionNameParser()
        self._decision_engine = decision_engine or VersionDecisionEngine()
        self._retention_days = retention_days

    # -- lifecycle -----------------------------------------------------

    def set_folder(self, path: str, scan_interval_seconds: int = 120,
                    automatic_cleanup: bool = True, move_to_safe_vault: bool = True) -> dict:
        normalized = os.path.normpath(path)

        if not os.path.isdir(normalized):
            raise VersionCleanupError(f"'{normalized}' is not an accessible folder")

        check = self._guard.is_scannable(normalized)
        if not check.allowed:
            raise VersionCleanupError(
                f"'{normalized}' can't be monitored: {check.reason}. Systole never monitors "
                f"Windows system directories, even on explicit request."
            )

        try:
            self._folder_repo.set_folder(VersionCleanupFolder(
                id=None, path=normalized, scan_interval_seconds=scan_interval_seconds,
                automatic_cleanup=automatic_cleanup, move_to_safe_vault=move_to_safe_vault,
            ))
            self._notify("info", f"Watching {normalized} for older versions...")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        self.run_cycle(is_initial=True)
        return self.get_status()

    def remove(self) -> None:
        try:
            active = self._folder_repo.get_active()
            if active:
                self._notify("info", f"Stopped watching {active['path']} for versions.")
            self._folder_repo.clear()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def pause(self) -> dict:
        try:
            active = self._require_active()
            self._folder_repo.set_paused(active["id"], True)
            self._notify("info", "Version cleanup paused.")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get_status()

    def resume(self) -> dict:
        try:
            active = self._require_active()
            self._folder_repo.set_paused(active["id"], False)
            self._notify("info", "Version cleanup resumed.")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get_status()

    def confirm_group(self, group_id: int, kept_full_path: str) -> dict:
        """Resolves a needs_confirmation group with the user's explicit
        choice -- the only path by which an uncertain group ever gets
        cleaned up, matching the 'do not delete, ask' safety rule."""
        try:
            group = self._group_repo.get_group(group_id)
            if not group:
                raise VersionCleanupError(f"No version group with id={group_id}")
            members = self._group_repo.get_members(group_id)
            member_paths = {m["full_path"] for m in members}
            if kept_full_path not in member_paths:
                raise VersionCleanupError("Chosen path is not a member of this version group")

            active = self._folder_repo.get_active()
            move_enabled = bool(active["move_to_safe_vault"]) if active else True

            moved = 0
            bytes_saved = 0
            for m in members:
                if m["full_path"] == kept_full_path:
                    self._group_repo.set_member_move_status(group_id, m["full_path"], "skipped")
                    continue
                if not move_enabled:
                    continue
                result = self._move_member_to_vault(m, reason="user_confirmed")
                if result:
                    moved += 1
                    bytes_saved += m["size_bytes"]

            status = "cleaned" if moved > 0 or not move_enabled else "pending"
            self._group_repo.resolve_group(group_id, kept_full_path, bytes_saved, status, "user_confirmed")
            self._notify("success", f"Keeping {os.path.basename(kept_full_path)} (your choice).")
            if moved:
                self._notify("success", f"Moved {moved} older version(s) into Safe Vault.")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return self.get_status()

    # -- the core cycle --------------------------------------------------

    def run_cycle(self, is_initial: bool = False) -> VersionCycleResult:
        active = self._require_active()
        folder_id = active["id"]
        folder_path = active["path"]

        if active["paused"] and not is_initial:
            logger.debug("Skipping version cleanup cycle for %s: paused", folder_path)
            return VersionCycleResult(0, 0, 0, 0, 0, 0, 0)

        try:
            self._folder_repo.mark_scan_started(folder_id)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        try:
            result = self._scan_and_process(folder_path, bool(active["automatic_cleanup"]),
                                             bool(active["move_to_safe_vault"]))
            next_scan = self._compute_next_scan(active["scan_interval_seconds"])
            self._folder_repo.mark_scan_finished(folder_id, "completed", next_scan)
            self._emit_summary_notifications(result)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            try:
                next_scan = self._compute_next_scan(active["scan_interval_seconds"])
                self._folder_repo.mark_scan_finished(folder_id, "failed", next_scan)
                self._notify("error", f"Version scan of {folder_path} failed -- see logs for details.")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                logger.exception("Failed to even record the version-scan failure for %s", folder_path)
            logger.exception("Version Cleanup scan failed for %s", folder_path)
            raise

        return result

    def _scan_and_process(self, folder_path: str, automatic_cleanup: bool,
                           move_to_safe_vault: bool) -> VersionCycleResult:
        members_by_group = self._scan_and_group(folder_path)

        groups_detected = 0
        groups_cleaned = 0
        groups_needing_confirmation = 0
        files_moved = 0
        bytes_reclaimed = 0
        errors = 0
        entries_scanned = sum(len(v) for v in members_by_group.values())

        for group_key, members in members_by_group.items():
            if len(members) < 2:
                continue
            groups_detected += 1
            base_name = members[0].base_name
            decision = self._decision_engine.decide(members)

            if decision.needs_confirmation:
                groups_needing_confirmation += 1
                group_id = self._group_repo.upsert_group(
                    base_name, len(members), None, 0, "needs_confirmation", "uncertain"
                )
                for m in members:
                    self._add_member_row(group_id, m, is_kept=False, move_status="pending")
                self._notify(
                    "warning",
                    f"Multiple versions detected for '{base_name}'. Please confirm which version should be kept.",
                )
                continue

            kept = decision.kept
            losers = [m for m in members if m is not kept]
            storage_saved = sum(m.size_bytes for m in losers)

            group_id = self._group_repo.upsert_group(
                base_name, len(members), kept.full_path, storage_saved, "pending", decision.reason
            )
            self._add_member_row(group_id, kept, is_kept=True, move_status="skipped")

            moved_this_group = 0
            if automatic_cleanup and move_to_safe_vault:
                for loser in losers:
                    row = {"full_path": loser.full_path, "size_bytes": loser.size_bytes}
                    if self._move_member_to_vault(row, reason=f"older_version:{decision.reason}"):
                        self._add_member_row(group_id, loser, is_kept=False, move_status="moved")
                        moved_this_group += 1
                        files_moved += 1
                    else:
                        self._add_member_row(group_id, loser, is_kept=False, move_status="failed")
                        errors += 1

                if moved_this_group == len(losers) and losers:
                    self._group_repo.resolve_group(group_id, kept.full_path, storage_saved,
                                                     "cleaned", decision.reason)
                    groups_cleaned += 1
                    bytes_reclaimed += storage_saved
                    self._notify("success", f"Keeping {os.path.basename(kept.full_path)}.")
            else:
                for loser in losers:
                    self._add_member_row(group_id, loser, is_kept=False, move_status="pending")

        return VersionCycleResult(
            entries_scanned=entries_scanned, groups_detected=groups_detected,
            groups_cleaned=groups_cleaned, groups_needing_confirmation=groups_needing_confirmation,
            files_moved=files_moved, bytes_reclaimed=bytes_reclaimed, errors=errors,
        )

    def _add_member_row(self, group_id: int, m: VersionMember, is_kept: bool, move_status: str) -> None:
        self._group_repo.add_member(
            group_id, m.full_path, m.is_folder, m.version_label, m.version_number,
            m.size_bytes, m.modified_time, m.created_time, is_kept, move_status,
        )

    def _move_member_to_vault(self, member: dict, reason: str) -> bool:
        """Moves a single file or folder to the Safe Vault, recording full
        audit history. Returns False (never raises) on any failure --
        PathGuard rejection, a locked file, or a filesystem error --
        so one bad member never aborts the rest of the group."""
        full_path = member["full_path"]
        check = self._guard.is_modifiable(full_path)
        if not check.allowed:
            logger.info("Skipped version-cleanup move for %s: %s", full_path, check.reason)
            return False

        move_result = self._vault.move_to_vault(full_path)
        if not move_result.success:
            logger.warning("Version-cleanup move failed for %s: %s", full_path, move_result.error)
            return False

        cleanup_id = self._vault_repo.record_cleanup(
            file_id=None, group_id=None, original_path=full_path,
            vault_path=move_result.destination_path, action="moved_to_vault",
            size_bytes=member["size_bytes"], reason=reason,
        )
        self._vault_repo.record_vault_entry(
            cleanup_history_id=cleanup_id, vault_path=move_result.destination_path,
            original_path=full_path, size_bytes=member["size_bytes"],
            retention_days=self._retention_days,
        )
        return True

    def _emit_summary_notifications(self, result: VersionCycleResult) -> None:
        if result.groups_detected == 0:
            self._notify("info", "No older versions found.")
            return
        if result.files_moved > 0:
            self._notify(
                "success",
                f"Moved {result.files_moved} older version{'s' if result.files_moved != 1 else ''} into Safe Vault.",
            )
        if result.bytes_reclaimed > 0:
            self._notify("success", f"Recovered {human_bytes(result.bytes_reclaimed)}.")

    # -- scanning --------------------------------------------------------

    def _scan_and_group(self, folder_path: str) -> dict[str, list[VersionMember]]:
        """Non-recursive: only the folder's immediate children are
        considered for version grouping, matching the product's own
        example (top-level entries directly inside Downloads). Deeper
        recursion would risk grouping unrelated, deeply-nested files that
        happen to share a name pattern by coincidence."""
        groups: dict[str, list[VersionMember]] = {}

        try:
            entries = list(os.scandir(folder_path))
        except OSError as exc:
            logger.warning("Could not list %s: %s", folder_path, exc)
            return groups

        for entry in entries:
            full_path = entry.path
            if is_reparse_point(full_path):
                continue
            check = self._guard.is_scannable(full_path)
            if not check.allowed:
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                logger.debug("Could not stat %s: %s", full_path, exc)
                continue

            if is_dir:
                name = entry.name
                extension = ""
                size_bytes = self._folder_size(full_path)
            else:
                stem, extension = os.path.splitext(entry.name)
                name = stem
                extension = extension.lower()
                size_bytes = st.st_size

            parsed = self._parser.parse(name)
            group_key = f"{parsed.base_name.lower()}{extension}" if not is_dir else parsed.base_name.lower()

            member = VersionMember(
                full_path=full_path, is_folder=is_dir, base_name=parsed.base_name,
                version_label=parsed.version_label, version_number=parsed.version_number,
                size_bytes=size_bytes, modified_time=self._iso(st.st_mtime),
                created_time=self._iso(st.st_ctime),
            )
            groups.setdefault(group_key, []).append(member)

        return groups

    @staticmethod
    def _folder_size(path: str) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for filename in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, filename))
                except OSError:
                    continue
        return total

    @staticmethod
    def _iso(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    # -- status / dashboard ------------------------------------------------

    def get_status(self) -> dict:
        active = self._folder_repo.get_active()
        if not active:
            return {"active": False}

        pending_groups = self._group_repo.list_groups(status="pending")
        confirmation_groups = self._group_repo.list_groups(status="needs_confirmation")
        cleaned_groups = self._group_repo.list_groups(status="cleaned")
        storage_saved = self._group_repo.total_storage_saved()

        return {
            "active": True,
            "id": active["id"],
            "path": active["path"],
            "enabled": bool(active["enabled"]),
            "paused": bool(active["paused"]),
            "status": active["status"],
            "scan_interval_seconds": active["scan_interval_seconds"],
            "automatic_cleanup": bool(active["automatic_cleanup"]),
            "move_to_safe_vault": bool(active["move_to_safe_vault"]),
            "notifications_enabled": bool(active["notifications_enabled"]),
            "last_scan_at": active["last_scan_at"],
            "next_scan_at": active["next_scan_at"],
            "last_scan_status": active["last_scan_status"],
            "version_groups_pending": len(pending_groups),
            "version_groups_needing_confirmation": len(confirmation_groups),
            "version_groups_cleaned": len(cleaned_groups),
            "storage_saved_bytes": storage_saved,
        }

    # -- internals -----------------------------------------------------

    def _require_active(self):
        active = self._folder_repo.get_active()
        if not active:
            raise VersionCleanupError("No folder is currently being watched for versions")
        return active

    def _notify(self, level: str, message: str) -> None:
        active = self._folder_repo.get_active()
        if active and not active["notifications_enabled"]:
            return
        self._notify_repo.add(Notification(id=None, message=message, level=level, source="version_cleanup"))

    @staticmethod
    def _compute_next_scan(interval_seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)).strftime("%Y-%m-%d %H:%M:%S")
