# Installation Guide

## Requirements

- Windows 10/11 (the app is Windows-specific; drive classification, health
  checks, and the Recycle Bin integration rely on Windows APIs)
- Python 3.12+
- Node.js 20+ and npm (only needed to build/run the UI)
- Rust + the Tauri prerequisites, if you want to build the desktop
  `.msi`/`.exe` installer (see https://v2.tauri.app/start/prerequisites/).
  Not required to run the backend + API, or the web-based dev UI.

## Quick start (development)

```powershell
git clone <this-repo>
cd systole-storage-manager

# 1. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.database.db   # or just start the app; init_db runs on startup

# 2. Run the backend + scheduler + real-time monitor together
python run.py
# API now listening on http://127.0.0.1:8731

# 3. Frontend (separate terminal)
cd ..\frontend
npm install
npm run dev
# UI now at http://localhost:1420
```

Or use the automated installer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

## Running as a background service

`run.py` is the everything-in-one-process background service: it starts
the scheduler (periodic full/incremental scans + vault purge), the
real-time filesystem monitor, and the FastAPI server together.

To have it start automatically at login, register it as a Windows
Scheduled Task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -RegisterTask
```

This creates a task named `SystoleStorageManager` that runs
`backend\.venv\Scripts\python.exe run.py` at logon. Manage it with the
standard Task Scheduler commands:

```powershell
Start-ScheduledTask -TaskName SystoleStorageManager
Stop-ScheduledTask -TaskName SystoleStorageManager
Unregister-ScheduledTask -TaskName SystoleStorageManager
```

## Building the desktop app (.msi installer)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

This freezes the Python backend into a standalone `systole-service.exe`
with PyInstaller, bundles it as a Tauri resource, and produces an
installer under:

```
frontend\src-tauri\target\release\bundle\
```

The desktop app spawns `systole-service.exe` on launch (see
`frontend/src-tauri/src/main.rs`) and talks to it over
`http://127.0.0.1:8731`, same as the dev UI.

Before building, generate app icons if you haven't already:

```powershell
cd frontend
npx @tauri-apps/cli icon path\to\your-1024x1024-icon.png
```

## Configuration

Copy/edit `config/settings.yaml` to override any default in
`backend/app/config.py` — folder exclusions, extension exclusions,
minimum duplicate size, retention period, scan schedule, monitored
folders, and so on. No restart is required for most settings changed via
the `POST /settings` API endpoint; changes to `config/settings.yaml`
itself require a restart of `run.py`.

## Running tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

The suite runs entirely against an in-memory SQLite database and a
temporary directory tree — it never touches your real drives, and is
safe to run anywhere, including CI.

## Uninstalling

1. `Unregister-ScheduledTask -TaskName SystoleStorageManager` (if
   registered)
2. Uninstall the desktop app via Windows "Add or remove programs" (if
   installed via the `.msi`)
3. Delete `%USERPROFILE%\.systole` to remove the database, logs, and
   Safe Vault contents. **Note:** anything still sitting in the Safe
   Vault will be permanently lost if you delete this folder without
   restoring it first — check `GET /cleanup/vault` or the dashboard's
   Safe Vault panel before deleting.
