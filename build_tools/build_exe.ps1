[CmdletBinding()]
param(
    [switch]$SkipRuff,
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

function Remove-RepoChildFolder {
    param([string]$Name)
    $target = Join-Path $RepoRoot $Name
    if (-not (Test-Path $target)) {
        return
    }
    $resolved = Resolve-Path $target
    if (-not $resolved.Path.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repository root: $($resolved.Path)"
    }
    Remove-Item -LiteralPath $resolved.Path -Recurse -Force
}

Write-Step "Cleaning old build folders..."
Remove-RepoChildFolder "build"
Remove-RepoChildFolder "dist"

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

Write-Step "Installing/updating packaging dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (Test-Path "requirements-dev.txt") {
    python -m pip install -r requirements-dev.txt
}
python -m pip install --upgrade pyinstaller

if (-not $SkipRuff) {
    Write-Step "Running Ruff..."
    python -m ruff check .
}

if (-not $SkipTests) {
    Write-Step "Running tests..."
    python -m pytest
}

Write-Step "Building EOAT Command Center executable..."
python -m PyInstaller --noconfirm --clean .\EOAT_Command_Center.spec

$exe = Join-Path $RepoRoot "dist\EOAT Command Center\EOAT Command Center.exe"
if (-not (Test-Path $exe)) {
    throw "Expected executable was not created: $exe"
}

Write-Host ""
Write-Host "Build complete!" -ForegroundColor Green
Write-Host "Executable folder:"
Write-Host (Split-Path $exe -Parent)
Write-Host "Executable:"
Write-Host $exe
