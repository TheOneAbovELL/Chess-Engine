<#
.SYNOPSIS
  One-time local setup for ChessLab on Windows.

.DESCRIPTION
  - Checks Python (3.11+) and Node.js (20+).
  - Creates backend\.venv and installs the backend (with dev tools) and the
    ChessLab engine package in editable mode.
  - Installs frontend dependencies (npm ci).
  - Creates .env from .env.example if it does not exist.
  - Reports whether Stockfish can be found.

  Safe to re-run. It never deletes your data (which lives in %LOCALAPPDATA%\ChessLab).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

Step "Checking that ChessLab is not running"
# Running servers lock native modules and the database; reinstalling under them
# fails half-way on Windows (files in use), so stop early instead.
$busy = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8000, 5173 }
if ($busy) {
    Fail "Something is listening on port $(($busy.LocalPort | Sort-Object -Unique) -join ' and '). Stop the ChessLab backend/frontend windows, then re-run setup."
}

Step "Checking Python"
$python = $null
foreach ($candidate in @("py -3.13", "py -3.12", "py -3.11", "python")) {
    $exe, $arg = $candidate.Split(" ", 2)
    try {
        $version = & $exe $arg -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$version -ge [version]"3.11") { $python = $candidate; break }
    } catch { }
}
if (-not $python) { Fail "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and re-run." }
Write-Host "Using $python ($version)"

Step "Checking Node.js"
try { $nodeVersion = (node --version).TrimStart("v") } catch { Fail "Node.js 20+ is required. Install the LTS release from https://nodejs.org/ and re-run." }
if ([version]$nodeVersion -lt [version]"20.0") { Fail "Node.js $nodeVersion is too old; install Node.js 22 LTS or newer." }
Write-Host "Node.js $nodeVersion"
if ([version]$nodeVersion -lt [version]"22.22") {
    Write-Host "Note: the frontend test runner (jsdom) prefers Node 22.22+ or 24 LTS; the app itself works on $nodeVersion." -ForegroundColor Yellow
}

Step "Creating backend virtual environment"
$venvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    $exe, $arg = $python.Split(" ", 2)
    & $exe $arg -m venv backend\.venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
}
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -e "backend[dev]" -e engine-lab --quiet
if ($LASTEXITCODE -ne 0) { Fail "Installing Python packages failed." }
Write-Host "Backend and engine packages installed."

Step "Installing frontend dependencies"
Push-Location frontend
try {
    # npm ci deletes node_modules first, so use it only for a fresh install;
    # otherwise npm install updates in place and never leaves a half-empty folder.
    if ((Test-Path package-lock.json) -and -not (Test-Path node_modules)) { npm ci --no-fund --no-audit } else { npm install --no-fund --no-audit }
    if ($LASTEXITCODE -ne 0) { Fail "npm install failed." }
} finally { Pop-Location }

Step "Configuration"
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example (edit it to change ports, limits or the Stockfish path)."
} else {
    Write-Host ".env already exists; left unchanged."
}

Step "Checking for Stockfish"
$found = & $venvPython -c "from app.core.config import Settings; from app.services.engine.stockfish import discover_stockfish; p = discover_stockfish(Settings()); print(p or '')" 2>$null
if ($found) {
    Write-Host "Stockfish found." -ForegroundColor Green
} else {
    Write-Host "Stockfish was not found. Install it with:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\install_stockfish.ps1"
    Write-Host "or download it from https://stockfishchess.org/download/ and set CHESSLAB_STOCKFISH_PATH in .env."
    Write-Host "ChessLab still runs without it (using its own, much weaker engine)."
}

Write-Host "`nSetup complete. Start ChessLab with:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1" -ForegroundColor Green
