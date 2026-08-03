"""
Systole AI - Storage Manager
FastAPI application entrypoint.

Run directly for local dev:  python -m app.main
Run as a background service:  see run.py / scripts/install.ps1
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    cleanup, drives, duplicates, folder_monitor, folders, notifications, restore, scan,
    settings, statistics, version_cleanup,
)
from app.config import get_settings
from app.database.db import init_db
from app.logging_config import configure_logging

settings_obj = get_settings()
configure_logging(settings_obj.log_dir)
logger = logging.getLogger("systole.main")

app = FastAPI(
    title=settings_obj.app_name,
    version=settings_obj.version,
    description="AI-powered storage monitoring and duplicate management for Windows. "
                "The first agent of the Systole AI Operating System.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://localhost:5173", "tauri://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(drives.router)
app.include_router(duplicates.router)
app.include_router(statistics.router)
app.include_router(scan.router)
app.include_router(cleanup.router)
app.include_router(restore.router)
app.include_router(settings.router)
app.include_router(folders.router)
app.include_router(folder_monitor.router)
app.include_router(notifications.router)
app.include_router(version_cleanup.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("%s v%s started. Database: %s", settings_obj.app_name, settings_obj.version,
                settings_obj.database_path)


@app.get("/")
def root():
    return {
        "app": settings_obj.app_name,
        "version": settings_obj.version,
        "status": "running",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings_obj.api_host, port=settings_obj.api_port, reload=False)
