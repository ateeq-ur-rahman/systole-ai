# Systole AI - Storage Manager
# Installation script for Windows.
#
# Sets up a Python virtual environment, installs backend dependencies,
# initializes the database, builds the frontend, and (optionally)
# registers the background service as a Scheduled Task that starts at
# user logon.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -RegisterTask

param(
    [switch]$RegisterTask
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"

Write-Host "== Systole AI - Storage Manager: Install ==" -ForegroundColor Cyan

# --- Python backend -------------------------------------------------------

Write-Host "`n[1/4] Setting up Python virtual environment..." -ForegroundColor Yellow
Push-Location $BackendDir

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "`n[2/4] Initializing database..." -ForegroundColor Yellow
& ".\.venv\Scripts\python.exe" -c "from app.database.db import init_db; init_db(); print('Database ready.')"

Pop-Location

# --- Frontend --------------------------------------------------------------

Write-Host "`n[3/4] Building frontend..." -ForegroundColor Yellow
Push-Location $FrontendDir

if (Get-Command npm -ErrorAction SilentlyContinue) {
    npm install
    npm run build
} else {
    Write-Warning "npm not found -- skipping frontend build. Install Node.js 20+ and re-run to build the UI."
}

Pop-Location

# --- Scheduled Task (background service) -----------------------------------

if ($RegisterTask) {
    Write-Host "`n[4/4] Registering Systole background service as a Scheduled Task..." -ForegroundColor Yellow

    $pythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
    $runScript = Join-Path $BackendDir "run.py"
    $action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$runScript`"" -WorkingDirectory $BackendDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

    Register-ScheduledTask -TaskName "SystoleStorageManager" `
        -Action $action -Trigger $trigger -Settings $settings `
        -Description "Systole AI Storage Manager background service" `
        -Force | Out-Null

    Write-Host "Scheduled Task 'SystoleStorageManager' registered. It will start at next logon." -ForegroundColor Green
    Write-Host "To start it immediately: Start-ScheduledTask -TaskName SystoleStorageManager"
} else {
    Write-Host "`n[4/4] Skipped Scheduled Task registration (pass -RegisterTask to enable)." -ForegroundColor DarkGray
}

Write-Host "`nInstall complete." -ForegroundColor Green
Write-Host "Run the backend manually with:  cd backend; .\.venv\Scripts\python.exe run.py"
Write-Host "Run the frontend in dev mode with:  cd frontend; npm run dev"
