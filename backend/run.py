"""
Systole AI - Storage Manager
Background service entrypoint.

This is what scripts/install.ps1 registers as a Windows service / scheduled
task. It brings up:
  - the SQLite database (init_db)
  - the SchedulerAgent (periodic full + incremental scans, vault purge)
  - the RealtimeMonitorAgent (watches Downloads/Desktop/Documents + USB)
  - the FastAPI app (Local API) via uvicorn

Design goal: minimal CPU/RAM footprint when idle. All heavy work
(scanning, hashing) only runs on the scheduler's cadence, on a real
filesystem event, or on an explicit API call -- never continuously.
"""
from __future__ import annotations

import logging
import threading

import uvicorn

from app.config import get_settings
from app.container import build_container
from app.database.db import get_connection, init_db
from app.logging_config import configure_logging
from app.agents.folder_monitor import FolderMonitorError
from app.agents.version_cleanup import VersionCleanupError
from app.agents.realtime_monitor import RealtimeMonitorAgent, USBInsertionWatcher
from app.agents.scheduler import SchedulerAgent
from app.services.cleanup_service import CleanupService
from app.services.scan_service import ScanService
from app.utils.db_time import sqlite_utc_now

# Imported directly (not referenced only as the string "app.main:app")
# specifically so PyInstaller's static import analysis can see and bundle
# it -- see the comment at the uvicorn.run() call below for why this
# matters for the frozen build specifically.
from app.main import app as fastapi_app

logger = logging.getLogger("systole.run")


class _FolderMonitorWatcher:
    """Keeps a dedicated real-time watchdog pointed at whichever folder is
    currently active for the Folder Monitor Agent. Since the active
    folder can change at runtime via the API (a new POST /folder-monitor
    call), this re-checks periodically (piggybacking on the same tick
    cadence as the verification scan) and restarts its watchdog observer
    if the target path has changed."""

    def __init__(self, container, debounce_seconds: float = 2.0):
        self._container = container
        self._debounce_seconds = debounce_seconds
        self._current_path: str | None = None
        self._observer: RealtimeMonitorAgent | None = None
        self._lock = threading.Lock()

    def sync(self) -> None:
        with self._lock:
            active = self._container.monitored_folder_repo.get_active()
            target_path = active["path"] if active else None

            if target_path == self._current_path:
                return  # nothing changed, no need to restart the watcher

            if self._observer:
                self._observer.stop()
                self._observer = None

            self._current_path = target_path
            if not target_path:
                return

            def on_change(_path: str) -> None:
                try:
                    self._container.folder_monitor.run_cycle(is_initial=False)
                except FolderMonitorError:
                    pass  # folder was removed between the event firing and now
                except Exception:
                    logger.exception("Folder Monitor real-time cycle failed")

            watcher = RealtimeMonitorAgent(self._container.guard, debounce_seconds=self._debounce_seconds)
            watcher.start([target_path], on_change)
            self._observer = watcher
            logger.info("Folder Monitor real-time watcher now targeting: %s", target_path)

    def stop(self) -> None:
        with self._lock:
            if self._observer:
                self._observer.stop()
                self._observer = None


def _folder_monitor_tick(container, folder_watcher: _FolderMonitorWatcher) -> None:
    folder_watcher.sync()

    active = container.monitored_folder_repo.get_active()
    if not active or not active["enabled"] or active["paused"]:
        return

    next_scan_at = active["next_scan_at"]
    if next_scan_at and sqlite_utc_now() < next_scan_at:
        return  # not due yet

    try:
        container.folder_monitor.run_cycle(is_initial=False)
    except FolderMonitorError:
        pass  # folder was removed between the check and now
    except Exception:
        logger.exception("Folder Monitor scheduled cycle failed")


class _VersionCleanupWatcher:
    """Same self-retargeting real-time watcher pattern as
    _FolderMonitorWatcher, for the Version Cleanup Agent's independently
    selected folder."""

    def __init__(self, container, debounce_seconds: float = 2.0):
        self._container = container
        self._debounce_seconds = debounce_seconds
        self._current_path: str | None = None
        self._observer: RealtimeMonitorAgent | None = None
        self._lock = threading.Lock()

    def sync(self) -> None:
        with self._lock:
            active = self._container.version_cleanup_folder_repo.get_active()
            target_path = active["path"] if active else None

            if target_path == self._current_path:
                return

            if self._observer:
                self._observer.stop()
                self._observer = None

            self._current_path = target_path
            if not target_path:
                return

            def on_change(_path: str) -> None:
                try:
                    self._container.version_cleanup.run_cycle(is_initial=False)
                except VersionCleanupError:
                    pass
                except Exception:
                    logger.exception("Version Cleanup real-time cycle failed")

            watcher = RealtimeMonitorAgent(self._container.guard, debounce_seconds=self._debounce_seconds)
            watcher.start([target_path], on_change)
            self._observer = watcher
            logger.info("Version Cleanup real-time watcher now targeting: %s", target_path)

    def stop(self) -> None:
        with self._lock:
            if self._observer:
                self._observer.stop()
                self._observer = None


def _version_cleanup_tick(container, watcher: _VersionCleanupWatcher) -> None:
    watcher.sync()

    active = container.version_cleanup_folder_repo.get_active()
    if not active or not active["enabled"] or active["paused"]:
        return

    next_scan_at = active["next_scan_at"]
    if next_scan_at and sqlite_utc_now() < next_scan_at:
        return

    try:
        container.version_cleanup.run_cycle(is_initial=False)
    except VersionCleanupError:
        pass
    except Exception:
        logger.exception("Version Cleanup scheduled cycle failed")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_dir)
    init_db()

    conn = get_connection()
    container = build_container(conn, settings)

    scan_service = ScanService(container)
    cleanup_service = CleanupService(container)

    scheduler = SchedulerAgent()
    scheduler.schedule_full_scan(settings.scheduler.full_scan_cron, scan_service.run_full_scan)
    scheduler.schedule_incremental_scan(
        settings.scheduler.incremental_scan_interval_minutes, scan_service.run_incremental_scan
    )
    def _vault_maintenance_tick() -> None:
        try:
            result = cleanup_service.auto_clean_stale_findings()
            if result["groups_cleaned"]:
                logger.info(
                    "AI Findings: auto-cleaned %d stale group(s), %s reclaimed",
                    result["groups_cleaned"], result["bytes_reclaimed"],
                )
        except Exception:
            logger.exception("AI Findings auto-cleanup failed")
        try:
            cleanup_service.send_expiry_warnings()
        except Exception:
            logger.exception("Safe Vault expiry-warning check failed")
        try:
            purged = cleanup_service.purge_expired()
            if purged:
                logger.info("Safe Vault: permanently purged %d expired item(s)", purged)
        except Exception:
            logger.exception("Safe Vault purge failed")

    scheduler.schedule_vault_maintenance(15, _vault_maintenance_tick)

    folder_watcher = _FolderMonitorWatcher(container, debounce_seconds=settings.monitor.debounce_seconds)
    scheduler.schedule_folder_monitor_tick(30, lambda: _folder_monitor_tick(container, folder_watcher))
    folder_watcher.sync()  # pick up an already-configured monitored folder immediately on startup

    version_cleanup_watcher = _VersionCleanupWatcher(container, debounce_seconds=settings.monitor.debounce_seconds)
    scheduler.schedule_version_cleanup_tick(30, lambda: _version_cleanup_tick(container, version_cleanup_watcher))
    version_cleanup_watcher.sync()

    scheduler.start()
    logger.info("Scheduler started.")

    monitor = None
    usb_watcher = None
    if settings.monitor.enabled:
        monitor = RealtimeMonitorAgent(
            container.guard,
            debounce_seconds=settings.monitor.debounce_seconds,
            pause_on_battery_saver=settings.monitor.pause_on_battery_saver,
            pause_on_fullscreen_app=settings.monitor.pause_on_fullscreen_app,
        )

        def on_change(path: str) -> None:
            if monitor.should_pause():
                logger.debug("Monitor paused (battery saver / fullscreen app); skipping %s", path)
                return
            logger.info("Real-time change detected: %s", path)
            scan_service.run_incremental_scan()

        watched_folder_rows = container.folder_repo.list_all(enabled_only=True)
        watch_paths = list(settings.monitor.watch_paths) + [row["path"] for row in watched_folder_rows]
        if watched_folder_rows:
            logger.info("Also watching %d user-added folder(s): %s",
                        len(watched_folder_rows), ", ".join(r["path"] for r in watched_folder_rows))

        monitor.start(watch_paths, on_change)

        def on_new_drive(mountpoint: str) -> None:
            logger.info("New drive inserted: %s -- triggering scan", mountpoint)
            scan_service.scan_single_drive(mountpoint)

        usb_watcher = USBInsertionWatcher(on_new_drive)
        usb_watcher.start()
        logger.info("Real-time monitor and USB watcher started.")

    try:
        # Passing the app object directly (not the string "app.main:app")
        # is required for the frozen/PyInstaller build to work at all --
        # see the import comment near the top of this file. Both forms
        # behave identically under a normal `python run.py`.
        uvicorn.run(fastapi_app, host=settings.api_host, port=settings.api_port,
                    reload=False, log_config=None)
    finally:
        scheduler.shutdown()
        if monitor:
            monitor.stop()
        if usb_watcher:
            usb_watcher.stop()
        folder_watcher.stop()
        version_cleanup_watcher.stop()


if __name__ == "__main__":
    main()
