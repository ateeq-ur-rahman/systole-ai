"""
Centralized logging setup using loguru, bridged into stdlib `logging` so
every module using `logging.getLogger("systole.*")` gets consistent,
rotated, leveled output without each agent needing to know about loguru.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger as _loguru_logger


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(log_dir: str, level: str = "INFO") -> None:
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    _loguru_logger.remove()
    _loguru_logger.add(sys.stderr, level=level, colorize=True,
                        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
                               "<cyan>{name}</cyan> - <level>{message}</level>")
    _loguru_logger.add(str(Path(log_dir) / "systole.log"), level=level,
                        rotation="10 MB", retention="14 days", compression="zip",
                        enqueue=True, backtrace=False, diagnose=False)

    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for noisy in ("watchdog", "apscheduler", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
