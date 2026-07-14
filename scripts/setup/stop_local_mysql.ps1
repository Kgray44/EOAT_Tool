[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development"
$base = Join-Path $root "mysql-8.4.9-winx64"
$secrets = Join-Path $root "database.env"
if (-not (Test-Path $secrets)) { throw "Credential file not found: $secrets" }
Get-Content $secrets | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
$env:MYSQL_PWD = $env:EOAT_DB_ROOT_PASSWORD
try {
    & (Join-Path $base "bin\mysqladmin.exe") --host=127.0.0.1 --port=$env:EOAT_DB_PORT --user=root shutdown
    if ($LASTEXITCODE -ne 0) { throw "mysqladmin shutdown failed." }
} finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
}

