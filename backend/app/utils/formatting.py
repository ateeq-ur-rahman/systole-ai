from __future__ import annotations


def human_bytes(num: int) -> str:
    """Format a byte count as a human-readable string, e.g. 1536 -> '1.5 KB'."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024.0
    return f"{value:.1f} EB"
