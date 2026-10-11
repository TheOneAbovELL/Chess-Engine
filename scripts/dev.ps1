<#
.SYNOPSIS
  Start the ChessLab backend and frontend for development.

.DESCRIPTION
  Opens two PowerShell windows:
    - backend:  uvicorn with auto-reload on http://127.0.0.1:8000
    - frontend: Vite dev server on http://127.0.0.1:5173 (proxies /api to the backend)
  then opens the app in your browser. Close the windows (or press Ctrl+C in
  them) to stop.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#>
[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { Write-Host "Run scripts\setup.ps1 first." -ForegroundColor Red; exit 1 }
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) { Write-Host "Run scripts\setup.ps1 first (frontend dependencies missing)." -ForegroundColor Red; exit 1 }

$backend = "Set-Location '$Root\backend'; `$Host.UI.RawUI.WindowTitle = 'ChessLab backend'; & '$venvPython' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
$frontend = "Set-Location '$Root\frontend'; `$Host.UI.RawUI.WindowTitle = 'ChessLab frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backend
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontend

Write-Host "Starting… backend http://127.0.0.1:8000 (API docs at /api/docs), frontend http://127.0.0.1:5173"
if (-not $NoBrowser) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        try { Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5173" -TimeoutSec 2 | Out-Null; break } catch { Start-Sleep -Milliseconds 800 }
    }
    Start-Process "http://127.0.0.1:5173"
}
