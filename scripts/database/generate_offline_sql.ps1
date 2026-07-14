[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = "Stop"
$secrets = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development\database.env"
Get-Content $secrets | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] } }
$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$sql = & ".\.venv\Scripts\python.exe" -m alembic -c "server\alembic.ini" upgrade head --sql
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
[System.IO.File]::WriteAllLines([System.IO.Path]::GetFullPath($OutputPath), $sql)
