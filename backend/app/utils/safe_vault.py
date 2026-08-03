"""
Safe Vault: physical move operations backing the Safe Cleanup Agent.

Nothing in this codebase calls os.remove()/unlink() on a user file. Files
are always MOVED (never deleted) to either:
  - Systole's own Safe Vault directory (default), preserving full original
    path as metadata so a restore is a simple reverse-move, or
  - the Windows Recycle Bin, via `send2trash`, which is itself already
    reversible by the user through Windows Explorer.
"""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MoveResult:
    success: bool
    destination_path: str | None
    error: str | None = None


class SafeVault:
    def __init__(self, vault_dir: str):
        self._vault_dir = Path(vault_dir)
        self._vault_dir.mkdir(parents=True, exist_ok=True)

    def move_to_vault(self, source_path: str) -> MoveResult:
        try:
            src = Path(source_path)
            if not src.exists():
                return MoveResult(False, None, "source file does not exist")

            # Namespace by a UUID subfolder to guarantee no collisions even
            # if two files share a basename from different original paths.
            dest_dir = self._vault_dir / uuid.uuid4().hex[:12]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / src.name

            shutil.move(str(src), str(dest_path))
            return MoveResult(True, str(dest_path))
        except (OSError, shutil.Error) as exc:
            return MoveResult(False, None, str(exc))

    def move_to_recycle_bin(self, source_path: str) -> MoveResult:
        try:
            import send2trash
            send2trash.send2trash(source_path)
            return MoveResult(True, "<recycle_bin>")
        except ImportError:
            return MoveResult(False, None, "send2trash not installed")
        except Exception as exc:  # send2trash raises platform-specific errors
            return MoveResult(False, None, str(exc))

    def restore(self, vault_path: str, original_path: str) -> MoveResult:
        try:
            src = Path(vault_path)
            if not src.exists():
                return MoveResult(False, None, "vault file no longer exists")

            dest = Path(original_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                # Never silently overwrite something that now occupies the
                # original path -- restore alongside it instead.
                dest = dest.with_name(f"{dest.stem}_restored{dest.suffix}")

            shutil.move(str(src), str(dest))

            # Clean up the now-empty UUID vault subfolder, best-effort.
            try:
                src.parent.rmdir()
            except OSError:
                pass

            return MoveResult(True, str(dest))
        except (OSError, shutil.Error) as exc:
            return MoveResult(False, None, str(exc))

    def purge(self, vault_path: str) -> MoveResult:
        """Permanent delete -- ONLY called for entries past their retention
        period, and only from the vault (never from the user's live tree)."""
        try:
            path = Path(vault_path)
            if path.exists():
                path.unlink()
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
            return MoveResult(True, None)
        except OSError as exc:
            return MoveResult(False, None, str(exc))
