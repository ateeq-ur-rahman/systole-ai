"""
PathGuard: the single choke point every agent must pass a path through
before reading, hashing, moving, or deleting it.

Design intent: it is far safer to have ONE conservative gatekeeper that
every agent calls, than to trust every agent to reimplement the same
exclusion logic correctly. When in doubt, PathGuard says "protected".
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.core.constants import (
    NEVER_TOUCH_FILENAMES,
    NEVER_TOUCH_EXTENSIONS,
    matches_never_touch_dir,
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str = ""


class PathGuard:
    """Stateless safety checks. Instantiate once per process; cheap to reuse."""

    def __init__(self, extra_excluded_dirs: list[str] | None = None,
                 extra_excluded_extensions: list[str] | None = None):
        self._extra_dirs = [
            self._normalize(d).rstrip("\\") for d in (extra_excluded_dirs or [])
        ]
        self._extra_exts = {e.lower() for e in (extra_excluded_extensions or [])}

    @staticmethod
    def _normalize(path: str) -> str:
        # Normalize separators to backslash and lowercase for matching,
        # regardless of the host OS the code is exercised on (dev/test on
        # Linux, production on Windows).
        return str(Path(path)).replace("/", "\\").lower()

    def is_scannable(self, path: str) -> GuardResult:
        """Can this path be read/hashed at all?"""
        norm = self._normalize(path)

        if matches_never_touch_dir(norm):
            return GuardResult(False, "path under protected system directory")

        for extra in self._extra_dirs:
            if extra and extra in norm:
                return GuardResult(False, "path matches user-configured exclusion")

        filename = os.path.basename(norm)
        if filename in NEVER_TOUCH_FILENAMES:
            return GuardResult(False, "protected system file")

        ext = os.path.splitext(filename)[1]
        if ext in NEVER_TOUCH_EXTENSIONS or ext in self._extra_exts:
            return GuardResult(False, f"excluded extension '{ext}'")

        return GuardResult(True)

    def is_modifiable(self, path: str) -> GuardResult:
        """Can this path be moved to the vault / recycle bin?
        Strictly stronger than is_scannable -- adds locked-file checks on
        top of everything is_scannable already enforces (protected dirs,
        protected filenames, and the hard NEVER_TOUCH_EXTENSIONS list,
        which already covers every extension that should never be
        touched -- there is deliberately no second, separate
        "never-delete" extension list; see constants.py)."""
        scan_check = self.is_scannable(path)
        if not scan_check.allowed:
            return scan_check

        try:
            if self._is_locked(path):
                return GuardResult(False, "file is locked or in use")
        except OSError:
            # If we can't even stat it, treat as protected out of caution.
            return GuardResult(False, "unable to verify file state")

        return GuardResult(True)

    @staticmethod
    def _is_locked(path: str) -> bool:
        """Best-effort check for open/locked files.

        On Windows, attempting to open a file that's exclusively locked by
        another process raises PermissionError. On POSIX (used in dev/test),
        we fall back to checking read-only/executable-in-use heuristics.
        """
        if not os.path.exists(path):
            return False

        # Directories can never be opened via open() -- that's not a lock,
        # it's just how every filesystem works (IsADirectoryError on
        # POSIX, similar on Windows). Moving a directory with open file
        # handles inside it will fail at the OS level during the actual
        # move, which SafeVault surfaces as a move failure -- that's the
        # right place to detect it, not here.
        if os.path.isdir(path):
            return False

        # A file with the "system" or "hidden+system" attribute combo, or
        # one that is currently executing, is treated as locked.
        try:
            mode = os.stat(path).st_mode
            if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode):
                return True
        except OSError:
            return True

        try:
            # Attempt a non-destructive open in read+write mode; on Windows
            # this fails for files locked exclusively by another process.
            with open(path, "r+b"):
                pass
        except PermissionError:
            return True
        except OSError:
            # e.g. read-only file opened r+b -- not necessarily "locked",
            # re-check with a pure read.
            try:
                with open(path, "rb"):
                    pass
            except OSError:
                return True
        return False


_default_guard: PathGuard | None = None


def get_default_guard() -> PathGuard:
    global _default_guard
    if _default_guard is None:
        from app.config import get_settings
        settings = get_settings()
        _default_guard = PathGuard(
            extra_excluded_dirs=settings.excluded_dirs,
            extra_excluded_extensions=settings.excluded_extensions,
        )
    return _default_guard
