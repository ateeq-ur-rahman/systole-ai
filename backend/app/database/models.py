"""
Lightweight dataclasses mirroring the SQLite schema. These are plain data
carriers (no ORM magic) used by repositories and services -- keeps the
dependency graph simple and makes unit testing trivial (no DB required to
construct one).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Drive:
    id: Optional[int]
    letter: str
    volume_name: str
    filesystem: str
    drive_type: str
    capacity_bytes: int
    used_bytes: int
    free_bytes: int
    health: str = "unknown"


@dataclass
class FileRecord:
    id: Optional[int]
    drive_id: Optional[int]
    full_path: str
    filename: str
    extension: str
    folder: str
    size_bytes: int
    created_time: Optional[str] = None
    modified_time: Optional[str] = None
    accessed_time: Optional[str] = None
    owner: Optional[str] = None
    permissions: Optional[str] = None
    sha256: Optional[str] = None
    hash_computed_at: Optional[str] = None
    is_deleted: bool = False
    inode_key: Optional[str] = None
    is_reparse_point: bool = False


@dataclass
class DuplicateGroup:
    id: Optional[int]
    sha256: str
    file_count: int
    total_size_bytes: int
    reclaimable_bytes: int
    survivor_file_id: Optional[int]
    status: str = "pending"
    members: list[FileRecord] = field(default_factory=list)


@dataclass
class CleanupRecord:
    id: Optional[int]
    file_id: Optional[int]
    group_id: Optional[int]
    original_path: str
    vault_path: Optional[str]
    action: str
    size_bytes: int
    reason: str
    is_restorable: bool = True


@dataclass
class VersionCleanupFolder:
    id: Optional[int]
    path: str
    enabled: bool = True
    paused: bool = False
    scan_interval_seconds: int = 120
    automatic_cleanup: bool = True
    move_to_safe_vault: bool = True
    notifications_enabled: bool = True
    last_scan_at: Optional[str] = None
    next_scan_at: Optional[str] = None
    last_scan_status: str = "pending"
    status: str = "idle"


@dataclass
class VersionMember:
    full_path: str
    is_folder: bool
    base_name: str
    version_label: str
    version_number: Optional[int]
    size_bytes: int
    modified_time: str
    created_time: str


@dataclass
class MonitoredFolder:
    id: Optional[int]
    path: str
    enabled: bool = True
    paused: bool = False
    scan_interval_seconds: int = 120
    keep_strategy: str = "newest_modified"
    delete_action: str = "safe_vault"
    notifications_enabled: bool = True
    last_scan_at: Optional[str] = None
    next_scan_at: Optional[str] = None
    last_scan_status: str = "pending"
    status: str = "idle"


@dataclass
class Notification:
    id: Optional[int]
    message: str
    level: str = "info"
    source: str = "folder_monitor"
    read: bool = False


@dataclass
class WatchedFolder:
    id: Optional[int]
    path: str
    label: Optional[str]
    drive_id: Optional[int]
    enabled: bool = True
    last_scanned_at: Optional[str] = None
    last_scan_status: Optional[str] = None


@dataclass
class ScanRun:
    id: Optional[int]
    scan_type: str
    drive_id: Optional[int]
    files_scanned: int = 0
    files_hashed: int = 0
    bytes_scanned: int = 0
    duplicates_found: int = 0
    errors: int = 0
    status: str = "running"
