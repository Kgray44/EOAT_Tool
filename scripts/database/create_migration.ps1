[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Message)
$ErrorActionPreference = "Stop"
$secrets = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development\database.env"
Get-Content $secrets | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] } }
& ".\.venv\Scripts\python.exe" -m alembic -c "server\alembic.ini" revision --autogenerate -m $Message
exit $LASTEXITCODE

