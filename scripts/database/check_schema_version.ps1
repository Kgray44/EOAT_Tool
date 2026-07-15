[CmdletBinding()]
param([string]$DatabaseName = "eoat_atlas_dev")
$ErrorActionPreference = "Stop"
$secrets = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development\database.env"
Get-Content $secrets | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] } }
$env:EOAT_DB_NAME = $DatabaseName
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvPython = Join-Path $repository ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
Push-Location $repository
try {
    & $python -m alembic -c "server\alembic.ini" current --check-heads
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

