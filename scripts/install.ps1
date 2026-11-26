# Interneto · Toolbox Installer — Windows bootstrap.
#
# Usage (one-liner):
#   irm https://raw.githubusercontent.com/interneto/tui-toolbox-installer/main/scripts/install.ps1 | iex
#
# Installs `uv` if missing, installs the app from GitHub as a uv tool, and
# launches it. It installs the release tagged v$Version, never a moving
# branch; $env:INTERNETO_REF = '<tag|branch|sha>' overrides it (e.g. 'main').
# Bump $Version with pyproject.toml on every release (a test checks they match).

$ErrorActionPreference = 'Stop'
$Version = '0.1.0'
$Ref = if ($env:INTERNETO_REF) { $env:INTERNETO_REF } else { "v$Version" }
$Repo = "git+https://github.com/interneto/tui-toolbox-installer@$Ref"
$UvBin = Join-Path $env:USERPROFILE '.local\bin'

Write-Host 'Interneto · Toolbox Installer' -ForegroundColor Cyan

# 1. Ensure uv is available.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv (Python tool manager)...' -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$UvBin;$env:Path"
}

# 2. Install (or update) the app from GitHub.
Write-Host "Installing interneto-install $Ref from GitHub..." -ForegroundColor Yellow
uv tool install --force $Repo

# 3. Make the freshly installed command available in this session and launch.
$env:Path = "$UvBin;$env:Path"
Write-Host 'Launching — press q to quit.' -ForegroundColor Green
interneto-install
