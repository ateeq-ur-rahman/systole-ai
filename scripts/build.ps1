# Systole AI - Storage Manager
# Production build script: freezes the Python backend into a standalone
# .exe (via PyInstaller) and builds the Tauri desktop bundle around it.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$ResourceDir = Join-Path $FrontendDir "src-tauri"

Write-Host "== Systole AI - Storage Manager: Production Build ==" -ForegroundColor Cyan

# --- 1. Freeze backend into systole-service.exe -----------------------------

Write-Host "`n[1/3] Freezing backend with PyInstaller..." -ForegroundColor Yellow
Push-Location $BackendDir

& ".\.venv\Scripts\python.exe" -m pip install pyinstaller --quiet

& ".\.venv\Scripts\python.exe" -m PyInstaller `
    --name systole-service `
    --onefile `
    --noconsole `
    --add-data "app\database\schema.sql;app\database" `
    --collect-all watchdog `
    run.py

Copy-Item -Force "dist\systole-service.exe" (Join-Path $ResourceDir "systole-service.exe")
Pop-Location

Write-Host "Backend frozen to: $ResourceDir\systole-service.exe" -ForegroundColor Green

# --- 2. Build frontend + Tauri bundle ---------------------------------------

Write-Host "`n[2/3] Building frontend..." -ForegroundColor Yellow
Push-Location $FrontendDir
npm install
npm run build

Write-Host "`n[3/3] Building Tauri desktop bundle (.msi / .exe installer)..." -ForegroundColor Yellow
npm run tauri build
Pop-Location

Write-Host "`nBuild complete." -ForegroundColor Green
Write-Host "Installer output: frontend\src-tauri\target\release\bundle\"
