[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "EOAT Atlas Development"
$base = Join-Path $root "mysql-8.4.9-winx64"
$client = Join-Path $base "bin\mysql.exe"
$secrets = Join-Path $root "database.env"
if (-not (Test-Path $client)) { throw "MySQL client not found: $client" }
if (-not (Test-Path $secrets)) { throw "Local credential file not found: $secrets" }
Get-Content $secrets | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
$env:MYSQL_PWD = $env:EOAT_DB_MIGRATION_PASSWORD
try {
    & $client --host=$env:EOAT_DB_HOST --port=$env:EOAT_DB_PORT --user=$env:EOAT_DB_MIGRATION_USER --database=$env:EOAT_DB_NAME --batch --skip-column-names -e "SELECT VERSION(), DATABASE(), (SELECT version_num FROM alembic_version);"
    if ($LASTEXITCODE -ne 0) { throw "MySQL connectivity/schema check failed." }
} finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
}
& ".\.venv\Scripts\python.exe" -m scripts.database.verify_schema --output "reports\database_foundation\mysql_schema_verification.json"
exit $LASTEXITCODE

