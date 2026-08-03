# Systole AI — Storage Manager

The first agent of the **Systole AI Operating System** for Windows.

## Download

**[⬇ Download Systole AI for Windows](https://github.com/YOUR-USERNAME/YOUR-REPO/releases/latest/download/Systole-AI_x64_en-US.msi)**

No Python, Node, or Rust required — just download the `.msi`, double-click it, and follow the installer. Systole AI will appear in your Start Menu.

> **Replace `YOUR-USERNAME/YOUR-REPO`** in the link above with your actual GitHub repo path once you've published a release (see "Publishing a release" below) — until then this link won't resolve.

### First-run security warning (expected, not a bug)

Since this installer isn't code-signed with a paid certificate, Windows SmartScreen will show a blue "Windows protected your PC" warning the first time someone runs it. This is normal for small/independent apps, not a sign anything is wrong. To proceed:

1. Click **"More info"**
2. Click **"Run anyway"**

This only happens once per version — it won't reappear on future launches of the same install.

## Folder Monitor — the flagship feature

Point Systole at exactly one folder — `C:\Users\alice\Downloads`,
`D:\Projects`, anywhere — and it will:

1. Run an initial scan (metadata + SHA-256 for every file)
2. Detect true duplicates (content hash only — never filename, timestamp, or folder name)
3. Automatically keep the newest version and move every older duplicate to the Safe Vault
4. Keep watching that folder in real time (via `watchdog`) plus a periodic verification scan (default every 2 minutes, configurable)
5. Narrate everything it does via notifications: *"Monitoring Downloads...", "3 duplicate files detected.", "2 files moved to Safe Vault.", "Recovered 1.8 GB.", "No duplicates found."*

It never touches anything outside that one folder, and never touches
Windows system directories even if asked. Nothing is ever permanently
deleted — every move is reversible from the Safe Vault.

```
POST /folder-monitor           { "path": "C:\\Users\\alice\\Downloads" }
GET  /folder-monitor           -> status, last/next scan, files, duplicates, recovered space
POST /folder-monitor/scan      -> manual verification scan now
POST /folder-monitor/pause     -> pause automatic monitoring
POST /folder-monitor/resume
DELETE /folder-monitor         -> stop monitoring (Safe Vault contents untouched)
GET  /notifications             -> activity timeline
```

## The one rule that matters everywhere in this app

Systole never determines duplicates by filename, timestamp, or folder
name. Two files are only ever considered duplicates if their **SHA-256
content hash matches, byte for byte**. Once — and only once — that's
confirmed, a separate decision (Version Intelligence) picks which copy to
keep, using:

1. Latest modified timestamp
2. Latest created timestamp
3. Latest access timestamp
4. Preferred folder priority (Documents › Desktop › Projects › Pictures ›
   Videos › Downloads › Temp)
5. Shortest path

Redundant copies are then **moved**, never deleted — to a Safe Vault (or
the Recycle Bin, your choice) — with full undo/restore/rollback support.

## What it does

- **Discovers** every SSD, HDD, USB, external drive, network share, and
  memory card connected to your machine.
- **Watches specific folders on request** — point it at any single folder
  (`C:\Users\alice\Projects`, `D:\Photos`, a network share, anywhere) via
  the dashboard or `POST /folders`, and it scans and deduplicates just
  that folder, plus keeps monitoring it in real time going forward. You
  don't have to hand it a whole drive.
- **Scans** incrementally — unchanged files are never re-hashed, so it
  scales to millions of files without hammering your CPU.
- **Detects** true duplicates via content hash, and explains its reasoning
  in plain English for every decision.
- **Recovers space safely**: redundant copies go to a Safe Vault first,
  with a configurable retention window before permanent purge.
- **Monitors in real time**: watches Downloads, Desktop, Documents, and
  new USB insertions, and pauses automatically on battery saver or when a
  fullscreen app (game) has focus.
- **Never touches** Windows system files, `Program Files`, `AppData`,
  the registry, `pagefile.sys`/`hiberfil.sys`/`swapfile.sys`, locked
  files, or running executables — enforced at the code level by a single
  `PathGuard` gatekeeper every agent must pass through.

## Project layout

```
systole-storage-manager/
├── backend/            FastAPI + SQLite backend — the AI agents live here
│   ├── app/
│   │   ├── agents/     Drive Discovery, File Scanner, Hash Engine,
│   │   │               Duplicate Detection, Version Intelligence,
│   │   │               Storage Optimizer, Safe Cleanup, AI Explanation,
│   │   │               Real-Time Monitor, Scheduler
│   │   ├── api/        FastAPI routes + schemas
│   │   ├── database/   SQLite schema + connection management
│   │   ├── repositories/  Data access layer
│   │   ├── services/   Orchestration (Scan, Cleanup, Statistics)
│   │   └── utils/      PathGuard, SafeVault, formatting
│   ├── tests/          52 unit/integration tests
│   ├── requirements.txt
│   └── run.py          Background service entrypoint
├── frontend/           React + TypeScript + Tauri dashboard
│   ├── src/
│   └── src-tauri/      Desktop shell (spawns the backend, wraps the UI)
├── config/settings.yaml
├── scripts/            install.ps1, build.ps1
├── ARCHITECTURE.md
└── INSTALL.md
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the layered design and how
future Systole agents (RAM Manager, CPU Manager, Battery Manager, etc.)
plug into the same foundation, and [INSTALL.md](INSTALL.md) for setup,
running as a background service, and building the desktop installer.

## Quick start

```powershell
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py            # starts API + scheduler + real-time monitor

# in another terminal
cd frontend
npm install && npm run dev
```

Full instructions, including registering the background service and
building the `.msi` desktop installer, are in [INSTALL.md](INSTALL.md).

## Tech stack

Python 3.12 · FastAPI · SQLite · React · TypeScript · Tauri · watchdog ·
psutil · pywin32 · send2trash · hashlib (SHA-256) · loguru · APScheduler ·
PyYAML

## Safety, in three layers

1. **PathGuard** blocks protected directories, files, and extensions
   before any read or write is attempted.
2. **Move, never delete** — `SafeCleanupAgent` only ever moves files to
   the Safe Vault or Recycle Bin; nothing is unlinked from your live file
   tree.
3. **Full audit trail** — every move is recorded and reversible via
   `POST /restore` until its retention period expires; permanent purge
   only ever acts on files already sitting in Systole's own vault.

## API

| Endpoint | Purpose |
|---|---|
| `GET /drives` | List discovered drives |
| `GET /folders` | List watched (user-added) folders |
| `POST /folders` | Add a folder path to watch/scan/monitor |
| `DELETE /folders/{id}` | Stop watching a folder |
| `POST /folders/{id}/scan` | Scan one watched folder now and dedupe it |
| `GET /duplicates` | List duplicate groups |
| `GET /statistics` | Dashboard summary |
| `GET /statistics/ask?question=...` | Natural-language storage Q&A |
| `POST /scan` | Trigger a full/incremental scan, or `{"folder_id": N}` for one folder |
| `POST /cleanup` | Move redundant copies to the Safe Vault |
| `POST /restore` | Restore a file (or everything) from the Vault |
| `POST /settings` | Update user-adjustable settings |

## License

Proprietary — RD Syntherge Technologies Pvt. Ltd.
