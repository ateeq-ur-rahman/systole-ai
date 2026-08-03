"""
Lightweight dependency-injection container.

Rather than a DI framework, this is a plain factory module: every agent and
repository is constructed here from a single sqlite3 connection + Settings,
so tests can build the same graph against an in-memory DB, and FastAPI
routes can build it per-request against the thread-local connection.

This is also the extension point future agents (RAM Manager, CPU Manager,
etc.) plug into: they'd get their own `build_x_agent()` factory here,
sharing the same Settings/PathGuard/database primitives.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.agents.ai_explanation import AIExplanationAgent
from app.agents.drive_discovery import DriveDiscoveryAgent
from app.agents.duplicate_detection import DuplicateDetectionAgent
from app.agents.file_scanner import FileScannerAgent
from app.agents.folder_monitor import FolderMonitorAgent
from app.agents.hash_engine import HashEngine
from app.agents.safe_cleanup import SafeCleanupAgent
from app.agents.storage_optimizer import StorageOptimizerAgent
from app.agents.version_cleanup import VersionCleanupAgent
from app.agents.version_decision import VersionDecisionEngine
from app.agents.version_intelligence import VersionIntelligenceAgent
from app.config import Settings, get_settings
from app.repositories.drive_repository import DriveRepository
from app.repositories.duplicate_repository import DuplicateRepository
from app.repositories.file_repository import FileRepository
from app.repositories.folder_repository import FolderRepository
from app.repositories.monitored_folder_repository import MonitoredFolderRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.vault_repository import VaultRepository
from app.repositories.version_cleanup_folder_repository import VersionCleanupFolderRepository
from app.repositories.version_group_repository import VersionGroupRepository
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault
from app.utils.scan_filter import load_scan_filter
from app.utils.version_naming import VersionNameParser


@dataclass
class Container:
    settings: Settings
    conn: sqlite3.Connection

    drive_repo: DriveRepository
    file_repo: FileRepository
    dup_repo: DuplicateRepository
    vault_repo: VaultRepository
    folder_repo: FolderRepository
    monitored_folder_repo: MonitoredFolderRepository
    notification_repo: NotificationRepository
    version_cleanup_folder_repo: VersionCleanupFolderRepository
    version_group_repo: VersionGroupRepository

    guard: PathGuard
    vault: SafeVault

    drive_discovery: DriveDiscoveryAgent
    hash_engine: HashEngine
    file_scanner: FileScannerAgent
    version_intelligence: VersionIntelligenceAgent
    duplicate_detection: DuplicateDetectionAgent
    safe_cleanup: SafeCleanupAgent
    storage_optimizer: StorageOptimizerAgent
    ai_explanation: AIExplanationAgent
    folder_monitor: FolderMonitorAgent
    version_cleanup: VersionCleanupAgent


def build_container(conn: sqlite3.Connection, settings: Settings | None = None) -> Container:
    settings = settings or get_settings()

    drive_repo = DriveRepository(conn)
    file_repo = FileRepository(conn)
    dup_repo = DuplicateRepository(conn)
    vault_repo = VaultRepository(conn)
    folder_repo = FolderRepository(conn)
    monitored_folder_repo = MonitoredFolderRepository(conn)
    notification_repo = NotificationRepository(conn)
    version_cleanup_folder_repo = VersionCleanupFolderRepository(conn)
    version_group_repo = VersionGroupRepository(conn)

    guard = PathGuard(
        extra_excluded_dirs=settings.excluded_dirs,
        extra_excluded_extensions=settings.excluded_extensions,
    )
    vault = SafeVault(settings.vault_dir)

    drive_discovery = DriveDiscoveryAgent()
    hash_engine = HashEngine(
        file_repo, guard,
        chunk_size=settings.duplicates.hash_chunk_size,
        algorithm=settings.duplicates.hash_algorithm,
    )
    scan_filter = load_scan_filter(
        conn,
        default_enabled_categories=settings.scan_filter.enabled_categories,
        default_ignored_folder_names=settings.scan_filter.ignored_folder_names,
        default_minimum_file_size_bytes=settings.scan_filter.minimum_file_size_bytes,
    )
    file_scanner = FileScannerAgent(
        file_repo, hash_engine, guard,
        max_workers=settings.performance.max_worker_threads,
        batch_size=settings.performance.scan_batch_size,
        scan_filter=scan_filter,
    )
    version_intelligence = VersionIntelligenceAgent(settings.preferred_folder_priority)
    duplicate_detection = DuplicateDetectionAgent(
        file_repo, dup_repo, version_intelligence,
        min_size_bytes=settings.duplicates.minimum_size_bytes,
    )
    safe_cleanup = SafeCleanupAgent(
        file_repo, dup_repo, vault_repo, vault, guard,
        retention_days=settings.cleanup.retention_days,
        destination=settings.cleanup.destination,
    )
    storage_optimizer = StorageOptimizerAgent(file_repo, dup_repo)
    ai_explanation = AIExplanationAgent(file_repo, dup_repo, vault_repo)
    folder_monitor = FolderMonitorAgent(
        conn, monitored_folder_repo, file_repo, dup_repo, vault_repo, notification_repo, guard,
        file_scanner, duplicate_detection, safe_cleanup,
    )
    version_cleanup = VersionCleanupAgent(
        conn, version_cleanup_folder_repo, version_group_repo, vault_repo, notification_repo,
        guard, vault, VersionNameParser(), VersionDecisionEngine(settings.preferred_folder_priority),
        retention_days=settings.cleanup.retention_days,
    )

    return Container(
        settings=settings, conn=conn,
        drive_repo=drive_repo, file_repo=file_repo, dup_repo=dup_repo, vault_repo=vault_repo,
        folder_repo=folder_repo, monitored_folder_repo=monitored_folder_repo,
        notification_repo=notification_repo,
        version_cleanup_folder_repo=version_cleanup_folder_repo,
        version_group_repo=version_group_repo,
        guard=guard, vault=vault,
        drive_discovery=drive_discovery, hash_engine=hash_engine, file_scanner=file_scanner,
        version_intelligence=version_intelligence, duplicate_detection=duplicate_detection,
        safe_cleanup=safe_cleanup, storage_optimizer=storage_optimizer,
        ai_explanation=ai_explanation, folder_monitor=folder_monitor,
        version_cleanup=version_cleanup,
    )
