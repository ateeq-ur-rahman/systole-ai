"""
CleanupService

Thin orchestration wrapper around SafeCleanupAgent for the API layer:
translates request payloads into agent calls and commits the transaction.
"""
from __future__ import annotations

from app.database.models import Notification
from app.container import Container
from app.utils.formatting import human_bytes


class CleanupService:
    def __init__(self, container: Container):
        self._c = container

    def clean_groups(self, group_ids: list[int]) -> dict:
        outcome = self._c.safe_cleanup.clean_groups(group_ids)
        self._c.conn.commit()
        return {
            "moved": outcome.moved,
            "skipped": outcome.skipped,
            "bytes_reclaimed": outcome.bytes_reclaimed,
        }

    def clean_all_pending(self) -> dict:
        groups = self._c.dup_repo.list_groups(status="pending")
        return self.clean_groups([g["id"] for g in groups])

    def restore(self, cleanup_id: int) -> bool:
        result = self._c.safe_cleanup.restore(cleanup_id)
        self._c.conn.commit()
        return result

    def restore_all(self) -> dict:
        result = self._c.safe_cleanup.restore_all()
        self._c.conn.commit()
        return result

    def purge_expired(self) -> int:
        result = self._c.safe_cleanup.purge_expired()
        self._c.conn.commit()
        return result

    def auto_clean_stale_findings(self, hours: int | None = None) -> dict:
        """AI gives you a review window after finding a duplicate group
        before acting on it automatically -- default 24 hours. Anything
        still sitting as 'pending' past that window gets cleaned up on
        its own (moved to the Safe Vault, exactly like a manual cleanup
        -- never a permanent delete). This is what keeps AI Findings from
        piling up indefinitely if you never revisit the app."""
        window = hours if hours is not None else self._c.settings.cleanup.findings_auto_cleanup_hours
        stale = self._c.dup_repo.list_stale_pending(window)
        if not stale:
            return {"groups_cleaned": 0, "bytes_reclaimed": 0}

        outcome = self._c.safe_cleanup.clean_groups([g["id"] for g in stale])

        if outcome.moved:
            self._c.notification_repo.add(Notification(
                id=None,
                message=(
                    f"AI automatically cleaned up {len(stale)} duplicate file group"
                    f"{'s' if len(stale) != 1 else ''} that had been waiting for review for "
                    f"over {self._format_lead(window * 60)} — "
                    f"{human_bytes(outcome.bytes_reclaimed)} moved to the AI Vault."
                ),
                level="info", source="ai_findings",
            ))

        self._c.conn.commit()
        return {"groups_cleaned": len(stale), "bytes_reclaimed": outcome.bytes_reclaimed}

    def send_expiry_warnings(self, lead_minutes: int | None = None) -> int:
        """Notifies the user once per vault entry, shortly before it's
        permanently purged -- e.g. 'This file will be permanently deleted
        in about 1 hour.' Never re-warns the same entry twice (tracked via
        safe_vault.warning_sent_at), and never fires for entries the user
        has already restored. Returns the number of entries warned about."""
        lead = lead_minutes if lead_minutes is not None else self._c.settings.cleanup.warning_lead_time_minutes
        entries = self._c.vault_repo.entries_expiring_within(lead)
        if not entries:
            return 0

        for entry in entries:
            name = entry["original_path"].split("\\")[-1].split("/")[-1]
            message = (
                f"\"{name}\" will be permanently deleted from the Safe Vault in about "
                f"{self._format_lead(lead)} unless you restore it."
            )
            self._c.notification_repo.add(Notification(
                id=None, message=message, level="warning", source="safe_vault",
            ))
            self._c.vault_repo.mark_warning_sent(entry["id"])

        if len(entries) > 1:
            total_bytes = sum(e["size_bytes"] for e in entries)
            self._c.notification_repo.add(Notification(
                id=None,
                message=f"{len(entries)} files ({human_bytes(total_bytes)}) will be permanently "
                        f"deleted from the Safe Vault in about {self._format_lead(lead)} unless restored.",
                level="warning", source="safe_vault",
            ))

        self._c.conn.commit()
        return len(entries)

    @staticmethod
    def _format_lead(minutes: int) -> str:
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        hours = minutes / 60
        if hours == int(hours):
            hours = int(hours)
        return f"{hours} hour{'s' if hours != 1 else ''}"
