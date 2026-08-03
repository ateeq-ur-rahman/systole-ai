"""
Real-Time Monitor Agent

Watches user-facing directories (Downloads, Desktop, Documents, plus any
newly-inserted USB drive) for filesystem events using `watchdog`, and
triggers targeted incremental re-scans instead of a full-tree walk.

Events are debounced (default 2s) so a burst of writes to the same file
(e.g. a browser download in progress) doesn't trigger dozens of redundant
hash computations.

Automatically pauses:
  - when Windows Battery Saver is active (if pause_on_battery_saver=True)
  - when a fullscreen application is in focus, as a proxy for "gaming"
    (if pause_on_fullscreen_app=True)
"""
from __future__ import annotations

import logging
import platform
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("systole.realtime_monitor")

_IS_WINDOWS = platform.system() == "Windows"

RescanCallback = Callable[[str], None]


class _DebouncedHandler(FileSystemEventHandler):
    def __init__(self, on_change: RescanCallback, debounce_seconds: float, guard):
        self._on_change = on_change
        self._debounce_seconds = debounce_seconds
        self._guard = guard
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _schedule(self, path: str) -> None:
        check = self._guard.is_scannable(path)
        if not check.allowed:
            return
        with self._lock:
            existing = self._pending.get(path)
            if existing:
                existing.cancel()
            timer = threading.Timer(self._debounce_seconds, self._fire, args=(path,))
            timer.daemon = True
            self._pending[path] = timer
            timer.start()

    def _fire(self, path: str) -> None:
        with self._lock:
            self._pending.pop(path, None)
        try:
            self._on_change(path)
        except Exception:
            logger.exception("rescan callback failed for %s", path)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._schedule(event.dest_path)

    def on_deleted(self, event):
        # Deletions are handled by the next incremental scan's
        # "delete_missing_before" pass rather than here, to avoid acting on
        # a false-positive delete during e.g. atomic save-replace sequences.
        pass


class RealtimeMonitorAgent:
    def __init__(self, guard, debounce_seconds: float = 2.0,
                 pause_on_battery_saver: bool = True,
                 pause_on_fullscreen_app: bool = True):
        self._observer = Observer()
        self._guard = guard
        self._debounce_seconds = debounce_seconds
        self._pause_on_battery_saver = pause_on_battery_saver
        self._pause_on_fullscreen_app = pause_on_fullscreen_app
        self._running = False

    def start(self, watch_paths: list[str], on_change: RescanCallback) -> None:
        handler = _DebouncedHandler(on_change, self._debounce_seconds, self._guard)
        for path in watch_paths:
            if Path(path).exists():
                self._observer.schedule(handler, path, recursive=True)
                logger.info("Watching %s", path)
            else:
                logger.warning("Watch path does not exist, skipping: %s", path)
        self._observer.start()
        self._running = True

    def stop(self) -> None:
        if self._running:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._running = False

    def should_pause(self) -> bool:
        if self._pause_on_battery_saver and self._is_battery_saver_active():
            return True
        if self._pause_on_fullscreen_app and self._is_fullscreen_app_active():
            return True
        return False

    @staticmethod
    def _is_battery_saver_active() -> bool:
        try:
            import psutil
            battery = psutil.sensors_battery()
            # psutil doesn't expose "battery saver mode" directly; use low
            # charge + not plugged in as a reasonable proxy.
            return bool(battery and not battery.power_plugged and battery.percent <= 20)
        except Exception:
            return False

    @staticmethod
    def _is_fullscreen_app_active() -> bool:  # pragma: no cover - Windows-only path
        if not _IS_WINDOWS:
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            win_w = rect.right - rect.left
            win_h = rect.bottom - rect.top
            return win_w >= screen_w and win_h >= screen_h
        except Exception:
            return False


class USBInsertionWatcher:
    """Polls for newly-mounted removable drives (simplest reliable
    cross-platform approach; WM_DEVICECHANGE hooks are an optional future
    upgrade for lower latency on Windows)."""

    def __init__(self, on_new_drive: Callable[[str], None], poll_interval: float = 3.0):
        self._on_new_drive = on_new_drive
        self._poll_interval = poll_interval
        self._known: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        import psutil
        self._known = {p.mountpoint for p in psutil.disk_partitions()}
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import psutil
        while not self._stop_event.is_set():
            current = {p.mountpoint for p in psutil.disk_partitions()}
            new_drives = current - self._known
            for drive in new_drives:
                logger.info("New drive detected: %s", drive)
                try:
                    self._on_new_drive(drive)
                except Exception:
                    logger.exception("on_new_drive callback failed for %s", drive)
            self._known = current
            time.sleep(self._poll_interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
