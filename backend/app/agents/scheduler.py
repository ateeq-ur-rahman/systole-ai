"""
Scheduler Agent

Runs periodic full scans (cron-style, default 3 AM daily) and lighter
incremental scans (every N minutes) via APScheduler's BackgroundScheduler.
Delegates actual work to ScanService -- this module only owns timing.
"""
from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("systole.scheduler")


class SchedulerAgent:
    def __init__(self):
        self._scheduler = BackgroundScheduler()

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def schedule_full_scan(self, cron_expression: str, job: Callable[[], None]) -> None:
        minute, hour, day, month, day_of_week = cron_expression.split()
        trigger = CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)
        self._scheduler.add_job(job, trigger, id="full_scan", replace_existing=True)
        logger.info("Scheduled full scan with cron '%s'", cron_expression)

    def schedule_incremental_scan(self, minutes: int, job: Callable[[], None]) -> None:
        trigger = IntervalTrigger(minutes=minutes)
        self._scheduler.add_job(job, trigger, id="incremental_scan", replace_existing=True)
        logger.info("Scheduled incremental scan every %d minute(s)", minutes)

    def schedule_folder_monitor_tick(self, seconds: int, job: Callable[[], None]) -> None:
        """A frequent, cheap 'is it time yet?' check (default every 30s)
        that the Folder Monitor Agent uses to honor its own
        per-folder-configurable scan_interval_seconds (default 2 minutes)
        without needing to reconfigure this trigger every time the user
        changes that setting -- the job itself checks `next_scan_at`
        against the current time and no-ops if not due."""
        trigger = IntervalTrigger(seconds=seconds)
        self._scheduler.add_job(job, trigger, id="folder_monitor_tick", replace_existing=True)
        logger.info("Scheduled Folder Monitor tick every %d second(s)", seconds)

    def schedule_version_cleanup_tick(self, seconds: int, job: Callable[[], None]) -> None:
        """Same pattern as schedule_folder_monitor_tick, for the
        independently-configured Version Cleanup Agent folder."""
        trigger = IntervalTrigger(seconds=seconds)
        self._scheduler.add_job(job, trigger, id="version_cleanup_tick", replace_existing=True)
        logger.info("Scheduled Version Cleanup tick every %d second(s)", seconds)

    def schedule_vault_purge(self, job: Callable[[], None], hour: int = 4) -> None:
        trigger = CronTrigger(hour=hour, minute=0)
        self._scheduler.add_job(job, trigger, id="vault_purge", replace_existing=True)
        logger.info("Scheduled vault purge daily at %02d:00", hour)

    def schedule_vault_maintenance(self, minutes: int, job: Callable[[], None]) -> None:
        """Runs the expiry-warning check + purge together, frequently
        (default every 15 minutes). With a 1-day default retention, a
        once-a-day purge is too coarse -- a file could sit expired for
        nearly a full extra day, and a 1-hour-ahead warning needs to be
        checked far more often than once daily to actually land within
        that window."""
        trigger = IntervalTrigger(minutes=minutes)
        self._scheduler.add_job(job, trigger, id="vault_maintenance_tick", replace_existing=True)
        logger.info("Scheduled Safe Vault maintenance (warnings + purge) every %d minute(s)", minutes)
