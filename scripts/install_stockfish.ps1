<#
.SYNOPSIS
  Download the official Stockfish release for Windows into engines\stockfish.

.DESCRIPTION
  Fetches the release list from the official repository
  (github.com/official-stockfish/Stockfish), picks the Windows x86-64 build
  (the "universal" build selects the fastest code path for your CPU at
  runtime; on older releases the AVX2 build is preferred), downloads the ZIP
  and extracts it into engines\stockfish (ignored by Git).

  ChessLab discovers the executable there automatically. Stockfish is GPLv3
  software; the ZIP includes its licence (Copying.txt) and source code.

.PARAMETER Tag
  Release tag to install (default: the latest release, e.g. sf_19).

.PARAMETER DryRun
  Show which file would be downloaded, without downloading anything.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_stockfish.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install_stockfish.ps1 -Tag sf_17.1
#>
[CmdletBinding()]
param([string]$Tag = "latest", [switch]$DryRun)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $Root "engines\stockfish"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$api = if ($Tag -eq "latest") { "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest" } else { "https://api.github.com/repos/official-stockfish/Stockfish/releases/tags/$Tag" }
Write-Host "Reading release information from $api"
$release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "ChessLab-installer" }
$assets = $release.assets | Where-Object { $_.name -like "stockfish-windows-x86-64*.zip" }
$asset = ($assets | Where-Object { $_.name -like "*universal*" } | Select-Object -First 1)
if (-not $asset) { $asset = ($assets | Where-Object { $_.name -like "*avx2*" } | Select-Object -First 1) }
if (-not $asset) { $asset = ($assets | Where-Object { $_.name -eq "stockfish-windows-x86-64.zip" } | Select-Object -First 1) }
if (-not $asset) { throw "No Windows x86-64 build found in release $($release.tag_name)." }

$sizeMb = [math]::Round($asset.size / 1MB, 1)
Write-Host "Release $($release.tag_name): $($asset.name) ($sizeMb MB)"
if ($DryRun) { Write-Host "Dry run: would download $($asset.browser_download_url) into $Target"; exit 0 }
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$zip = Join-Path $Target $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -Headers @{ "User-Agent" = "ChessLab-installer" }
Expand-Archive -Path $zip -DestinationPath $Target -Force
Remove-Item $zip

$exe = Get-ChildItem -Path $Target -Recurse -Filter "stockfish*.exe" | Select-Object -First 1
if (-not $exe) { throw "Download succeeded but no stockfish*.exe was found in $Target." }
$id = ("uci`nquit`n" | & $exe.FullName | Select-String "^id name").ToString()
Write-Host "Installed: $id" -ForegroundColor Green
Write-Host "Location:  $($exe.FullName)"
Write-Host "Restart the ChessLab backend to use it."
