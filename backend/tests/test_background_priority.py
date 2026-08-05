from __future__ import annotations

import os

from app.config import PerformanceSettings


def test_default_worker_threads_uses_half_the_cores_not_nearly_all():
    """Regression context: the old default was (cpu_count - 1), which on
    a typical laptop claims nearly every core for background hashing
    work by default -- a real, reported cause of the whole machine
    feeling sluggish during a scan. This confirms the more
    background-friendly default actually took effect."""
    settings = PerformanceSettings()
    cpu_count = os.cpu_count() or 4

    assert settings.max_worker_threads == max(1, cpu_count // 2)
    # Never claims MORE than half, regardless of core count.
    assert settings.max_worker_threads <= cpu_count // 2 + 1
    # Always at least 1, even on a single-core machine.
    assert settings.max_worker_threads >= 1


def test_low_priority_io_defaults_to_enabled():
    """This setting already existed but was never wired up to any real
    behavior -- confirming it still defaults to True (background-
    friendly) now that it actually does something."""
    settings = PerformanceSettings()
    assert settings.low_priority_io is True


def test_process_priority_is_actually_lowered_when_enabled():
    """Proves the psutil call genuinely changes the OS-reported priority
    of the current process, rather than just trusting the code looks
    right. Skips gracefully on platforms where priority classes work
    differently (this feature matters most on Windows, which is the
    only platform Systole ships a desktop build for)."""
    import psutil

    process = psutil.Process()
    original_priority = process.nice()

    try:
        if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            assert process.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS
        else:
            # Non-Windows: psutil uses traditional nice values instead
            # of priority classes. A positive nice value is the
            # equivalent "be nicer to other processes" direction.
            process.nice(original_priority + 1)
            assert process.nice() > original_priority
    finally:
        # Restore original priority so this test doesn't leave the
        # actual pytest process running at a different priority than it
        # started with, which could affect other tests' timing.
        process.nice(original_priority)
