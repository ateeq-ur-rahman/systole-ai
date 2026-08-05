"""
Systole AI - Storage Manager
Central configuration management.

All tunables live here (or in config/settings.yaml, which overrides these
defaults). Nothing else in the codebase should hardcode paths, thresholds,
or feature flags -- they should be read from `get_settings()`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel, Field


class ScanFilterSettings(BaseModel):
    """Backing defaults for ScanFilter (see app/utils/scan_filter.py).
    These are the config-file-level defaults; the live, user-toggleable
    values actually used at scan time are read from settings_kv (see
    app/container.py's load_scan_filter) so changes made from the
    Settings page take effect on the next scan without a restart."""
    enabled_categories: List[str] = Field(default_factory=lambda: [
        "documents", "pdfs", "images", "videos", "office", "archives", "installers",
    ])
    ignored_folder_names: List[str] = Field(default_factory=lambda: [
        "node_modules", ".git", "build", "dist", "bin", "obj", ".cache",
        "venv", ".venv", "__pycache__", "temp", "tmp",
    ])
    minimum_file_size_bytes: int = 4096


class DuplicateSettings(BaseModel):
    minimum_size_bytes: int = 4096  # ignore trivial dupes below 4KB by default
    hash_chunk_size: int = 1024 * 1024  # 1MB chunks for SHA-256 streaming
    hash_algorithm: str = "sha256"


class MonitorSettings(BaseModel):
    enabled: bool = True
    watch_paths: List[str] = Field(default_factory=lambda: [
        str(Path.home() / "Downloads"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "Documents"),
    ])
    debounce_seconds: float = 2.0
    pause_on_battery_saver: bool = True
    pause_on_fullscreen_app: bool = True  # "pause during gaming"


class CleanupSettings(BaseModel):
    automatic_cleanup: bool = False  # AI never auto-deletes unless explicitly enabled
    retention_days: int = 1  # how long items live in the Safe Vault before purge eligibility
    warning_lead_time_minutes: int = 60  # notify this long before permanent deletion
    findings_auto_cleanup_hours: int = 24  # how long a detected duplicate sits pending before AI cleans it up on its own
    destination: str = "safe_vault"  # "safe_vault" | "recycle_bin"


class SchedulerSettings(BaseModel):
    full_scan_cron: str = "0 3 * * *"  # 3 AM daily
    incremental_scan_interval_minutes: int = 30


class PerformanceSettings(BaseModel):
    # Half the available cores, not (cpu_count - 1). This is a
    # background service, not a foreground batch job -- claiming nearly
    # every core by default (the old behavior) made full scans
    # noticeably slow down whatever else the user was doing on modest
    # laptops. Combined with low_priority_io below, this means less raw
    # parallelism claimed AND lower scheduling priority for what IS
    # claimed.
    max_worker_threads: int = max(1, (os.cpu_count() or 4) // 2)
    scan_batch_size: int = 500
    low_priority_io: bool = True


class Settings(BaseModel):
    app_name: str = "Systole AI - Storage Manager"
    version: str = "0.1.0"
    data_dir: str = str(Path.home() / ".systole")
    database_filename: str = "systole_storage.db"
    log_dir: str = str(Path.home() / ".systole" / "logs")
    vault_dir: str = str(Path.home() / ".systole" / "safe_vault")

    excluded_dirs: List[str] = Field(default_factory=list)  # merged with hardcoded NEVER_TOUCH list
    # Extra PathGuard-level extension exclusions beyond the hardcoded
    # NEVER_TOUCH_EXTENSIONS safety list (.sys/.dll/etc, always blocked
    # regardless of this setting). Left empty by default: which file
    # *types* are relevant to scan (installers, documents, images, ...)
    # is the ScanFilter's job now (see scan_filter.py and
    # /settings/scan-filter) -- this field exists for genuinely
    # exceptional per-installation overrides, not general category
    # control.
    excluded_extensions: List[str] = Field(default_factory=list)

    preferred_folder_priority: List[str] = Field(default_factory=lambda: [
        "documents", "desktop", "projects", "pictures", "videos", "downloads", "temp",
    ])

    duplicates: DuplicateSettings = Field(default_factory=DuplicateSettings)
    scan_filter: ScanFilterSettings = Field(default_factory=ScanFilterSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    cleanup: CleanupSettings = Field(default_factory=CleanupSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    performance: PerformanceSettings = Field(default_factory=PerformanceSettings)

    api_host: str = "127.0.0.1"
    api_port: int = 8731

    @property
    def database_path(self) -> str:
        return str(Path(self.data_dir) / self.database_filename)


def _load_yaml_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Load settings with the following precedence (lowest -> highest):
      1. Hardcoded defaults above
      2. config/settings.yaml (repo-relative, optional)
      3. $SYSTOLE_CONFIG (env var pointing to a YAML file, optional)
    """
    settings = Settings()

    repo_config = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
    overrides = _load_yaml_overrides(repo_config)

    env_config_path = os.environ.get("SYSTOLE_CONFIG")
    if env_config_path:
        overrides.update(_load_yaml_overrides(Path(env_config_path)))

    if overrides:
        settings = Settings(**{**settings.model_dump(), **overrides})

    # Ensure runtime directories exist.
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.vault_dir).mkdir(parents=True, exist_ok=True)

    return settings
