"""
Scan Filter

Decides, BEFORE any hashing happens, whether a file or folder is even
worth scanning at all. This is deliberately separate from PathGuard:

- PathGuard is a SAFETY layer -- it protects Windows system directories,
  locked files, and running executables, and its rules are hard-coded,
  non-configurable, and apply unconditionally everywhere in the app.
- ScanFilter is a PERFORMANCE/RELEVANCE layer -- it decides which of the
  files PathGuard allows are actually worth a consumer duplicate-finder
  caring about (skip node_modules, .git, build artifacts, tiny files,
  file types nobody asked to scan). It's fully user-configurable via
  Settings, and skipping something here just means "not scanned this
  time," never "unsafe to touch."

The two layers compose: a path must pass BOTH PathGuard.is_scannable()
AND ScanFilter checks before FileScannerAgent ever stats, indexes, or
hashes it. Nothing about SHA-256 duplicate detection itself changes --
this only controls what gets fed into that unchanged pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Extension -> category mapping. Deliberately data, not control flow, so
# it's easy to extend from Settings without touching matching logic.
CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "documents": {".doc", ".docx", ".rtf", ".odt", ".txt", ".md", ".tex"},
    "pdfs": {".pdf"},
    "images": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp",
        ".heic", ".heif", ".svg", ".raw", ".cr2", ".nef", ".dng",
    },
    "videos": {
        ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v",
        ".mpg", ".mpeg",
    },
    "office": {".xls", ".xlsx", ".xlsm", ".ppt", ".pptx", ".csv", ".ods", ".odp"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "installers": {".exe", ".msi", ".iso"},
    "source_code": {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
        ".cs", ".go", ".rs", ".rb", ".php", ".html", ".css", ".json",
        ".yaml", ".yml", ".sql", ".sh", ".ps1",
    },
    "system_files": {".dll", ".sys", ".ini", ".log", ".bak", ".tmp", ".dat"},
}

# Categories that make sense for a consumer "find my duplicate files" tool
# to include right out of the box -- documents, media, install packages.
# Source code and raw system files are opt-in: most people running this
# on a Downloads folder don't want their node_modules tree indexed.
DEFAULT_ENABLED_CATEGORIES: set[str] = {
    "documents", "pdfs", "images", "videos", "office", "archives", "installers",
}

# Folder basenames skipped anywhere they appear in the tree -- build
# artifacts and dependency caches that are large, numerous, churn
# constantly, and are never what a user means by "my files." This is
# distinct from PathGuard's NEVER_TOUCH list (Windows/Program
# Files/AppData/ProgramData/etc.), which stays enforced unconditionally
# regardless of these settings -- see path_guard.py.
DEFAULT_IGNORED_FOLDER_NAMES: set[str] = {
    "node_modules", ".git", "build", "dist", "bin", "obj", ".cache",
    "venv", ".venv", "__pycache__", "temp", "tmp",
}

DEFAULT_MINIMUM_FILE_SIZE_BYTES = 4096


@dataclass
class ScanFilter:
    enabled_categories: set[str] = field(default_factory=lambda: set(DEFAULT_ENABLED_CATEGORIES))
    ignored_folder_names: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORED_FOLDER_NAMES))
    minimum_file_size_bytes: int = DEFAULT_MINIMUM_FILE_SIZE_BYTES

    def __post_init__(self):
        # Normalize once at construction so every check is a cheap,
        # case-insensitive set lookup.
        self.ignored_folder_names = {n.lower() for n in self.ignored_folder_names}
        self.enabled_categories = {c.lower() for c in self.enabled_categories}

    def is_folder_ignored(self, folder_basename: str) -> bool:
        return folder_basename.lower() in self.ignored_folder_names

    def is_extension_included(self, extension: str) -> bool:
        """True if this extension belongs to at least one enabled
        category. An extension that doesn't appear in ANY known category
        at all (something not in CATEGORY_EXTENSIONS) is treated as
        excluded by default -- this is an allowlist, not a denylist, per
        'scan only user files by default.'"""
        ext = extension.lower()
        for category in self.enabled_categories:
            if ext in CATEGORY_EXTENSIONS.get(category, ()):
                return True
        return False

    def passes_size_filter(self, size_bytes: int) -> bool:
        return size_bytes >= self.minimum_file_size_bytes

    @classmethod
    def all_categories(cls) -> list[str]:
        return sorted(CATEGORY_EXTENSIONS.keys())


# settings_kv keys used to persist live, user-toggleable overrides (set
# via POST /settings/scan-filter) that take effect on the next scan
# without an application restart.
KV_KEY_ENABLED_CATEGORIES = "scan_filter.enabled_categories"
KV_KEY_IGNORED_FOLDER_NAMES = "scan_filter.ignored_folder_names"
KV_KEY_MINIMUM_FILE_SIZE_BYTES = "scan_filter.minimum_file_size_bytes"


def load_scan_filter(conn, default_enabled_categories: list[str] | None = None,
                      default_ignored_folder_names: list[str] | None = None,
                      default_minimum_file_size_bytes: int | None = None) -> "ScanFilter":
    """Builds a ScanFilter for the current scan, using live overrides from
    settings_kv where present (set via the Settings page) and falling
    back to the config-file/environment defaults otherwise. Called fresh
    on every container build, so a category toggle made through the API
    takes effect on the very next scan cycle -- no restart required."""
    enabled_categories = list(default_enabled_categories or DEFAULT_ENABLED_CATEGORIES)
    ignored_folder_names = list(default_ignored_folder_names or DEFAULT_IGNORED_FOLDER_NAMES)
    minimum_file_size_bytes = (
        default_minimum_file_size_bytes
        if default_minimum_file_size_bytes is not None
        else DEFAULT_MINIMUM_FILE_SIZE_BYTES
    )

    try:
        cur = conn.execute(
            "SELECT key, value FROM settings_kv WHERE key IN (?, ?, ?)",
            (KV_KEY_ENABLED_CATEGORIES, KV_KEY_IGNORED_FOLDER_NAMES, KV_KEY_MINIMUM_FILE_SIZE_BYTES),
        )
        rows = {row["key"]: row["value"] for row in cur.fetchall()}
    except Exception:
        rows = {}

    if KV_KEY_ENABLED_CATEGORIES in rows:
        try:
            enabled_categories = json.loads(rows[KV_KEY_ENABLED_CATEGORIES])
        except (ValueError, TypeError):
            pass
    if KV_KEY_IGNORED_FOLDER_NAMES in rows:
        try:
            ignored_folder_names = json.loads(rows[KV_KEY_IGNORED_FOLDER_NAMES])
        except (ValueError, TypeError):
            pass
    if KV_KEY_MINIMUM_FILE_SIZE_BYTES in rows:
        try:
            minimum_file_size_bytes = int(json.loads(rows[KV_KEY_MINIMUM_FILE_SIZE_BYTES]))
        except (ValueError, TypeError):
            pass

    return ScanFilter(
        enabled_categories=set(enabled_categories),
        ignored_folder_names=set(ignored_folder_names),
        minimum_file_size_bytes=minimum_file_size_bytes,
    )
