[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development"
$server = Join-Path $root "mysql-8.4.9-winx64\bin\mysqld.exe"
if (-not (Test-Path $server)) {
    Write-Error @"
MySQL 8.4 LTS was not found. This script does not silently install system software.
Use WinGet interactively (`winget install --id Oracle.MySQL --exact`) or follow the portable ZIP procedure in
docs/setup/LOCAL_MYSQL_DEVELOPMENT_SETUP.md, then rerun this script.
"@
    exit 2
}
& "$PSScriptRoot\start_local_mysql.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& "$PSScriptRoot\verify_local_mysql.ps1"
exit $LASTEXITCODE

