[CmdletBinding()]
param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
Set-Location $RepoRoot

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Cyan
}

Write-Step "Activating virtual environment..."
$activate = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Host "No .venv found. Creating one..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -m venv .venv
    } else {
        python -m venv .venv
    }
}
. $activate

Write-Step "Installing launcher build dependencies..."
python -m pip install --upgrade pip
if (Test-Path "requirements-dev.txt") {
    python -m pip install -r requirements-dev.txt
}
python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    python -m pip install pyinstaller
}

if (-not $SkipTests) {
    Write-Step "Running launcher tests..."
    python -m pytest tests/test_atlas_launcher.py
}

Write-Step "Building EOAT Atlas Launcher executable..."
python -m PyInstaller --noconfirm --clean .\EOAT_Atlas_Launcher.spec

$exe = Join-Path $RepoRoot "dist\EOAT Atlas Launcher.exe"
if (-not (Test-Path $exe)) {
    throw "Expected launcher executable was not created: $exe"
}

Write-Host ""
Write-Host "Launcher build complete!" -ForegroundColor Green
Write-Host "Executable:"
Write-Host $exe
