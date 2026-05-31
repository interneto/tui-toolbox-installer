# Interneto · Toolbox Installer — Windows bootstrap.
#
# Usage (one-liner):
#   irm https://raw.githubusercontent.com/interneto/tui-toolbox-installer/main/scripts/install.ps1 | iex
#
# Installs `uv` if missing, installs the app from GitHub as a uv tool, and
# launches it. Re-run any time to update to the latest version.

$ErrorActionPreference = 'Stop'
$Repo = 'git+https://github.com/interneto/tui-toolbox-installer'
$UvBin = Join-Path $env:USERPROFILE '.local\bin'

Write-Host 'Interneto · Toolbox Installer' -ForegroundColor Cyan

# 1. Ensure uv is available.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv (Python tool manager)...' -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$UvBin;$env:Path"
}

# 2. Install (or update) the app from GitHub.
Write-Host 'Installing interneto-install from GitHub...' -ForegroundColor Yellow
uv tool install --force $Repo

# 3. Make the freshly installed command available in this session and launch.
$env:Path = "$UvBin;$env:Path"
Write-Host 'Launching — press q to quit.' -ForegroundColor Green
interneto-install
