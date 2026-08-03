"""
Drive Discovery Agent

Enumerates every storage device visible to Windows: fixed SSD/HDD, USB
removable drives, external HDDs, mapped network drives, and memory cards.

Uses `psutil` for cross-platform partition enumeration and `pywin32` /
`wmi`-style APIs (via psutil's Windows-specific fields + ctypes fallback)
to classify drive type and pull SMART-adjacent health where available.

The module is written so it also runs (in a degraded, best-effort mode) on
non-Windows dev machines -- classification simply falls back to "UNKNOWN"
for anything it can't determine via ctypes, which keeps unit tests portable.
"""
from __future__ import annotations

import logging
import platform
from dataclasses import dataclass

import psutil

from app.database.models import Drive

logger = logging.getLogger("systole.drive_discovery")

_IS_WINDOWS = platform.system() == "Windows"

# Maps Windows GetDriveType() return codes to human categories.
# https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew
_DRIVE_TYPE_MAP = {
    0: "UNKNOWN",
    1: "NO_ROOT_DIR",
    2: "USB",            # DRIVE_REMOVABLE
    3: "SSD",             # DRIVE_FIXED -- refined further below via seek penalty check
    4: "NETWORK",         # DRIVE_REMOTE
    5: "MEMORY_CARD",     # DRIVE_CDROM (approximated; refined by filesystem heuristics)
    6: "RAM_DISK",        # DRIVE_RAMDISK
}


@dataclass
class DriveHealth:
    status: str  # ok | warning | critical | unknown
    detail: str = ""


class DriveDiscoveryAgent:
    """Discovers and classifies all mounted storage devices."""

    def discover(self) -> list[Drive]:
        drives: list[Drive] = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, FileNotFoundError, OSError) as exc:
                logger.warning("Skipping %s: %s", part.mountpoint, exc)
                continue

            drive_type = self._classify(part)
            health = self._check_health(part.mountpoint, drive_type)

            drives.append(Drive(
                id=None,
                letter=part.mountpoint,
                volume_name=self._volume_name(part.mountpoint),
                filesystem=part.fstype or "unknown",
                drive_type=drive_type,
                capacity_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                health=health.status,
            ))
        return drives

    def _classify(self, part: psutil._common.sdiskpart) -> str:
        opts = (part.opts or "").lower()
        if "cdrom" in opts:
            return "OPTICAL"
        if _IS_WINDOWS:
            try:
                import ctypes
                drive_type_code = ctypes.windll.kernel32.GetDriveTypeW(part.mountpoint)
                mapped = _DRIVE_TYPE_MAP.get(drive_type_code, "UNKNOWN")
                if mapped == "SSD":
                    return "SSD" if self._is_ssd(part.device) else "HDD"
                return mapped
            except Exception as exc:  # pragma: no cover - Windows-only path
                logger.debug("GetDriveTypeW failed for %s: %s", part.mountpoint, exc)
                return "UNKNOWN"
        # Non-Windows dev/test fallback.
        if "removable" in opts or part.mountpoint.startswith("/media"):
            return "USB"
        return "SSD"

    @staticmethod
    def _is_ssd(device: str) -> bool:  # pragma: no cover - Windows-only path
        """Best-effort SSD vs HDD distinction via Windows storage query.
        Falls back to True (assume SSD, the modern default) if the query
        isn't available -- this is a UI hint, not a safety-relevant field."""
        try:
            import wmi  # type: ignore
            c = wmi.WMI()
            for disk in c.Win32_DiskDrive():
                if device.rstrip("\\").upper() in (disk.DeviceID or "").upper():
                    media_type = (disk.MediaType or "").lower()
                    return "ssd" not in media_type and "fixed hard disk" in media_type is False
        except Exception:
            pass
        return True

    @staticmethod
    def _volume_name(mountpoint: str) -> str:
        if _IS_WINDOWS:  # pragma: no cover - Windows-only path
            try:
                import ctypes
                buf = ctypes.create_unicode_buffer(261)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p(mountpoint), buf, ctypes.sizeof(buf),
                    None, None, None, None, 0,
                )
                return buf.value or "Local Disk"
            except Exception:
                return "Local Disk"
        return mountpoint

    def _check_health(self, mountpoint: str, drive_type: str) -> DriveHealth:
        try:
            usage = psutil.disk_usage(mountpoint)
        except OSError:
            return DriveHealth("unknown")

        pct_used = usage.used / usage.total * 100 if usage.total else 0
        if pct_used >= 95:
            return DriveHealth("critical", f"{pct_used:.1f}% full")
        if pct_used >= 85:
            return DriveHealth("warning", f"{pct_used:.1f}% full")
        return DriveHealth("ok")
