"""
Windows path utilities.

Two focused responsibilities:

1. Long path support (>260 characters). Windows' traditional MAX_PATH
   limit of 260 characters still applies to most Win32 API calls unless
   the path is prefixed with the `\\\\?\\` extended-length prefix (or
   `\\\\?\\UNC\\` for network paths). Python's `open()`/`os.stat()` on
   Windows go through these APIs, so without this prefix, deeply nested
   project folders or long filenames silently fail to scan/hash/move.

2. Reparse point detection (symlinks, junctions, mount points). These can
   point anywhere -- including in a loop back to a parent directory -- so
   the File Scanner must recognize and skip them explicitly rather than
   relying only on `os.walk(followlinks=False)`, which does not reliably
   catch NTFS junctions (a different reparse tag than symlinks) on every
   Python version.
"""
from __future__ import annotations

import os
import platform

_IS_WINDOWS = platform.system() == "Windows"
_LONG_PATH_PREFIX = "\\\\?\\"
_LONG_PATH_UNC_PREFIX = "\\\\?\\UNC\\"
_LONG_PATH_THRESHOLD = 240  # leave headroom under the 260-char MAX_PATH limit

# Windows FILE_ATTRIBUTE_REPARSE_POINT flag (winnt.h), exposed via
# os.stat().st_file_attributes on Windows (Python 3.5+).
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def to_long_path(path: str) -> str:
    """Prefix a path with the Windows extended-length prefix if it's long
    enough to need it. No-op on non-Windows platforms and on paths that
    are already prefixed or are relative (the prefix only works with
    absolute paths)."""
    if not _IS_WINDOWS or len(path) < _LONG_PATH_THRESHOLD:
        return path
    if path.startswith(_LONG_PATH_PREFIX):
        return path
    if not os.path.isabs(path):
        return path  # can't safely prefix a relative path

    if path.startswith("\\\\"):  # UNC network path: \\server\share\...
        return _LONG_PATH_UNC_PREFIX + path.lstrip("\\")
    return _LONG_PATH_PREFIX + path


def strip_long_path_prefix(path: str) -> str:
    """Inverse of to_long_path -- for display/storage, we always want the
    human-readable form, never the \\\\?\\-prefixed one."""
    if path.startswith(_LONG_PATH_UNC_PREFIX):
        return "\\\\" + path[len(_LONG_PATH_UNC_PREFIX):]
    if path.startswith(_LONG_PATH_PREFIX):
        return path[len(_LONG_PATH_PREFIX):]
    return path


def is_reparse_point(path: str) -> bool:
    """True if `path` is a symlink, NTFS junction, or other reparse point.
    The File Scanner uses this to prune such entries during directory
    traversal -- both to avoid infinite loops (a junction pointing at an
    ancestor directory) and to avoid double-scanning/double-hashing
    content that physically lives elsewhere."""
    if os.path.islink(path):
        return True
    if not _IS_WINDOWS:
        return False
    try:
        attrs = os.stat(path, follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
        return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        # st_file_attributes doesn't exist on this platform/Python build,
        # or the path couldn't be stat'd (e.g. permission denied) --
        # either way, fail safe by not treating it as a reparse point and
        # letting the normal PathGuard/permission-error handling apply.
        return False


def inode_key(stat_result: os.stat_result) -> str | None:
    """A stable identity key for the *physical* file behind a path, used
    to detect hardlinks (multiple paths pointing at the same on-disk
    data). On Windows, `st_ino` has held the NTFS File ID since Python
    3.5; on POSIX it's the traditional inode number. Returns None if the
    platform doesn't populate a meaningful value (st_ino == 0), so
    hardlink-aware logic degrades gracefully to treating each path as a
    distinct physical file rather than raising."""
    if not stat_result.st_ino:
        return None
    return f"{stat_result.st_dev}:{stat_result.st_ino}"
