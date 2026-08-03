"""
Hard safety boundaries for Systole AI - Storage Manager.

These constants are intentionally NOT configurable via settings.yaml.
Anything in NEVER_TOUCH_* is excluded from scanning, hashing, duplicate
detection, and cleanup, unconditionally. This is the single source of
truth that app.utils.path_guard enforces on every filesystem operation.
"""
from __future__ import annotations

import re

# Directory fragments (case-insensitive) that must never be scanned or
# modified. Matched against the normalized path of every file/dir before
# any read, hash, or move operation is attempted.
NEVER_TOUCH_DIR_FRAGMENTS: list[str] = [
    r"\\windows\\",
    r"\\windows$",
    r"\\system32\\",
    r"\\program files\\",
    r"\\program files \(x86\)\\",
    r"\\programdata\\",
    r"\\users\\[^\\]+\\appdata\\",
    r"\\recovery\\",
    r"\\boot\\",
    r"\\efi\\",
    r"\\drivers\\",
    r"\\windows defender\\",
    r"\$recycle\.bin",
    r"\\system volume information\\",
]

# Specific filenames that must never be touched regardless of location.
NEVER_TOUCH_FILENAMES: set[str] = {
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    "ntuser.dat",
    "ntuser.dat.log1",
    "ntuser.dat.log2",
    "bootmgr",
    "bootnxt",
}

# Registry hives / extensions that must never be modified.
NEVER_TOUCH_EXTENSIONS: set[str] = {
    ".sys",
    ".dll",
    ".drv",
    ".reg",
    ".hiv",
}

_COMPILED_DIR_PATTERNS = [re.compile(p, re.IGNORECASE) for p in NEVER_TOUCH_DIR_FRAGMENTS]


def matches_never_touch_dir(normalized_path: str) -> bool:
    """Return True if the given (lowercased, backslash-normalized) path
    falls under a protected system directory."""
    return any(p.search(normalized_path) for p in _COMPILED_DIR_PATTERNS)


# Folder-priority tiers used by the Version Intelligence Agent (Priority 4).
# Lower index == higher priority == more likely to be kept as the survivor.
FOLDER_PRIORITY_ORDER: list[str] = [
    "documents",
    "desktop",
    "projects",
    "pictures",
    "videos",
    "downloads",
    "temp",
]

# NOTE: there is deliberately no separate "never delete" extension list
# here anymore. Executables/installers (.exe/.msi) are NOT hard-blocked
# from being moved to the Safe Vault -- "duplicate installers" is an
# advertised, first-class feature (see ScanFilter's installers category
# and the AI Recommendations card), and moving one to the vault is always
# reversible. The extensions that genuinely should never be touched
# (.dll/.sys/.drv/.reg/.hiv) are already covered, unconditionally, by
# NEVER_TOUCH_EXTENSIONS above -- which PathGuard.is_modifiable() also
# enforces (it calls is_scannable() first). A second, separate
# "never-delete" list here would just duplicate that protection while
# never actually being reachable.
