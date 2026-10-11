<#
.SYNOPSIS
  Run every automated check: lint, types, tests and builds.

.PARAMETER E2E
  Also run the Playwright browser tests (needs Microsoft Edge or Chrome).

.PARAMETER Live
  Also run the opt-in tests that call the real Chess.com and Lichess APIs.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\check.ps1
  powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -E2E -Live
#>
[CmdletBinding()]
param([switch]$E2E, [switch]$Live)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $Root "backend\.venv\Scripts\python.exe"
$failures = @()

function Run($name, [scriptblock]$block) {
    Write-Host "`n==> $name" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { $script:failures += $name; Write-Host "FAILED: $name" -ForegroundColor Red }
}

Push-Location (Join-Path $Root "backend")
Run "backend: ruff" { & $py -m ruff check app tests; if ($LASTEXITCODE -eq 0) { & $py -m ruff format --check app tests } }
Run "backend: mypy (strict)" { & $py -m mypy app }
Run "backend: pytest" { & $py -m pytest -q -p no:warnings --timeout 300 }
if ($Live) { Run "backend: live provider tests" { & $py -m pytest -q -m live -p no:warnings --timeout 300 } }
Pop-Location

Push-Location (Join-Path $Root "engine-lab")
Run "engine: ruff" { & $py -m ruff check . }
Run "engine: pytest" { & $py -m pytest -q -p no:warnings }
Pop-Location

Push-Location (Join-Path $Root "frontend")
Run "frontend: typecheck" { npx tsc -b }
Run "frontend: eslint" { npx eslint . }
Run "frontend: vitest" { npx vitest run }
Run "frontend: build" { npx vite build }
if ($E2E) { Run "frontend: playwright e2e" { npx playwright test } }
Pop-Location

if ($failures.Count) {
    Write-Host "`n$($failures.Count) check(s) failed: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "`nAll checks passed." -ForegroundColor Green
