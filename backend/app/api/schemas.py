from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class DriveOut(BaseModel):
    id: int
    letter: str
    volume_name: Optional[str]
    filesystem: Optional[str]
    drive_type: str
    capacity_bytes: int
    used_bytes: int
    free_bytes: int
    health: str


class DuplicateGroupOut(BaseModel):
    id: int
    sha256: str
    file_count: int
    total_size_bytes: int
    reclaimable_bytes: int
    status: str


class DuplicateMemberOut(BaseModel):
    id: int
    full_path: str
    filename: str
    size_bytes: int
    is_survivor: bool
    selection_reason: Optional[str]


class FolderCreateRequest(BaseModel):
    path: str
    label: Optional[str] = None
    enabled: bool = True


class FolderOut(BaseModel):
    id: int
    path: str
    label: Optional[str]
    enabled: bool
    added_at: Optional[str] = None
    last_scanned_at: Optional[str]
    last_scan_status: Optional[str]


class ScanRequest(BaseModel):
    scan_type: str = "full"          # full | incremental
    drive_letter: Optional[str] = None
    folder_id: Optional[int] = None  # scan a single user-added watched folder


class CleanupRequest(BaseModel):
    group_ids: Optional[list[int]] = None  # None => clean all pending groups


class RestoreRequest(BaseModel):
    cleanup_id: Optional[int] = None  # None => restore_all


class SettingsUpdateRequest(BaseModel):
    automatic_cleanup: Optional[bool] = None
    realtime_monitoring: Optional[bool] = None
    retention_days: Optional[int] = None
    minimum_duplicate_size_bytes: Optional[int] = None
    excluded_dirs: Optional[list[str]] = None
    excluded_extensions: Optional[list[str]] = None


class MonitorFolderSetRequest(BaseModel):
    path: str
    scan_interval_seconds: int = 120


class MonitorFolderSettingsRequest(BaseModel):
    scan_interval_seconds: Optional[int] = None
    notifications_enabled: Optional[bool] = None
    delete_action: Optional[str] = None


class VersionCleanupSetRequest(BaseModel):
    path: str
    scan_interval_seconds: int = 120
    automatic_cleanup: bool = True
    move_to_safe_vault: bool = True


class VersionCleanupSettingsRequest(BaseModel):
    scan_interval_seconds: Optional[int] = None
    automatic_cleanup: Optional[bool] = None
    move_to_safe_vault: Optional[bool] = None
    notifications_enabled: Optional[bool] = None


class VersionGroupConfirmRequest(BaseModel):
    kept_full_path: str


class ScanFilterSettingsUpdateRequest(BaseModel):
    enabled_categories: Optional[List[str]] = None
    ignored_folder_names: Optional[List[str]] = None
    minimum_file_size_bytes: Optional[int] = None


class StatisticsOut(BaseModel):
    total_files: int
    total_bytes: int
    duplicate_reclaimable_bytes: int
    vault_bytes: int
    drives: list[dict]
