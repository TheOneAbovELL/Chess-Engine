<#
.SYNOPSIS
  Run ChessLab as a single local server (production build), no dev tools.

.DESCRIPTION
  Builds the frontend if needed (or always with -Build), then starts the
  backend, which also serves the built frontend, on http://127.0.0.1:8000.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -Build -Port 8080
#>
[CmdletBinding()]
param([switch]$Build, [int]$Port = 8000)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { Write-Host "Run scripts\setup.ps1 first." -ForegroundColor Red; exit 1 }

if ($Build -or -not (Test-Path (Join-Path $Root "frontend\dist\index.html"))) {
    Write-Host "Building the frontend…"
    Push-Location (Join-Path $Root "frontend")
    try { npm run build; if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." } } finally { Pop-Location }
}

Write-Host "ChessLab: http://127.0.0.1:$Port  (Ctrl+C to stop)" -ForegroundColor Green
Set-Location (Join-Path $Root "backend")
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
