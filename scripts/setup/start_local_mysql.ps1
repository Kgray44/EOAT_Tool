[CmdletBinding()]
param(
    [int]$Port = 3306
)
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development"
$base = Join-Path $root "mysql-8.4.9-winx64"
$server = Join-Path $base "bin\mysqld.exe"
$data = Join-Path $root "mysql-data"
$log = Join-Path $root "mysql-error.log"
$pidFile = Join-Path $root "mysql.pid"
if (-not (Test-Path $server) -or -not (Test-Path $data)) {
    throw "Portable MySQL is not initialized under $root. See docs/setup/LOCAL_MYSQL_DEVELOPMENT_SETUP.md."
}
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "MySQL-compatible listener already present on port $Port."
    exit 0
}
$arguments = "--basedir=`"$base`" --datadir=`"$data`" --bind-address=127.0.0.1 --port=$Port --mysqlx=OFF --log-error=`"$log`" --pid-file=`"$pidFile`""
Start-Process -FilePath $server -ArgumentList $arguments -WindowStyle Hidden
$admin = Join-Path $base "bin\mysqladmin.exe"
foreach ($attempt in 1..20) {
    & $admin --host=127.0.0.1 --port=$Port --user=invalid_health_probe ping 2>$null
    if ($LASTEXITCODE -ne 1) { break }
    Start-Sleep -Seconds 1
}
if (-not (Get-NetTCPConnection -LocalPort $Port -LocalAddress 127.0.0.1 -State Listen -ErrorAction SilentlyContinue)) {
    throw "MySQL did not start. Review $log."
}
Write-Output "MySQL is listening on 127.0.0.1:$Port."

