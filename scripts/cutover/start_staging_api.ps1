[CmdletBinding()]
param([int]$Port = 8766, [switch]$EnableWrites)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
$stateDir = Join-Path $env:LOCALAPPDATA 'EOAT Atlas Staging'
$envFile = Join-Path $stateDir 'staging.env'
$pidFile = Join-Path $stateDir 'eoat_api.pid'
$logFile = Join-Path $stateDir 'eoat_api.log'
$runtimeRoot = Join-Path $stateDir 'api-runtime'
$runtimeServer = Join-Path $runtimeRoot 'server'
if (-not (Test-Path -LiteralPath $envFile)) { throw "Staging environment is not initialized: $envFile" }
Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { Set-Item -Path "Env:$($matches[1])" -Value $matches[2] }
}
if (Test-Path -LiteralPath $pidFile) {
    $existing = [int](Get-Content -Raw -LiteralPath $pidFile)
    if (Get-Process -Id $existing -ErrorAction SilentlyContinue) { throw "Staging API already running (PID $existing)." }
    Remove-Item -LiteralPath $pidFile -Force
}
New-Item -ItemType Directory -Path $runtimeServer -Force | Out-Null
Copy-Item -Path (Join-Path $repoRoot 'server\*') -Destination $runtimeServer -Recurse -Force
$env:EOAT_API_PORT = [string]$Port
$env:EOAT_API_ENVIRONMENT = 'staging_local'
$env:EOAT_API_WRITES_ENABLED = if ($EnableWrites) { 'true' } else { 'false' }
$process = Start-Process -FilePath 'python' -ArgumentList '-m','server.eoat_api' -WorkingDirectory $runtimeRoot `
    -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err') -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2
        $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
        Set-Content -LiteralPath $pidFile -Value $listener.OwningProcess
        Write-Output "Staging API ready on loopback; schema=$($health.current_schema_revision); writes=$($health.writes_enabled)."
        exit 0
    } catch { }
}
Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
throw 'Staging API failed to become healthy within 30 seconds.'
