param(
    [int]$Port = 8765,
    [switch]$EnableWrites
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
$stateDir = Join-Path $env:LOCALAPPDATA 'EOAT Atlas Development'
$envFile = Join-Path $stateDir 'database.env'
$pidFile = Join-Path $stateDir 'eoat_api.pid'
$logFile = Join-Path $stateDir 'eoat_api.log'
$runtimeRoot = Join-Path $stateDir 'api-runtime'
$runtimeServer = Join-Path $runtimeRoot 'server'

if (-not (Test-Path -LiteralPath $envFile)) { throw "Database environment file not found: $envFile" }
Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }
}
if (Test-Path -LiteralPath $pidFile) {
    $existingPid = [int](Get-Content -Raw -LiteralPath $pidFile)
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        $existingHealth = $null
        try { $existingHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2 } catch { }
        $modeMatches = $null -ne $existingHealth -and (-not $EnableWrites -or $existingHealth.writes_enabled -eq $true)
        if ($modeMatches) { Write-Output "EOAT Atlas API already running (PID $existingPid); writes=$($existingHealth.writes_enabled)."; exit 0 }
        Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
    }
}
$localPython = (Get-Command python -ErrorAction SilentlyContinue).Source
$python = if ($localPython) { $localPython } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
& $python -c 'import sqlalchemy, fastapi, uvicorn, pymysql' 2>$null
if ($LASTEXITCODE -ne 0) { $python = Join-Path $repoRoot '.venv\Scripts\python.exe' }
New-Item -ItemType Directory -Path $runtimeServer -Force | Out-Null
Copy-Item -Path (Join-Path $repoRoot 'server\*') -Destination $runtimeServer -Recurse -Force
$env:EOAT_API_PORT = [string]$Port
$env:EOAT_API_ENVIRONMENT = 'development'
$env:EOAT_API_WRITES_ENABLED = if ($EnableWrites) { 'true' } else { 'false' }
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$process = Start-Process -FilePath $python -ArgumentList '-m','server.eoat_api' -WorkingDirectory $runtimeRoot -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err') -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id
try {
    $health = $null
    for ($attempt = 0; $attempt -lt 120 -and $null -eq $health; $attempt++) {
        Start-Sleep -Milliseconds 250
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/health" -TimeoutSec 2 } catch { }
    }
    if ($null -eq $health) { throw 'API did not become ready within 30 seconds.' }
    $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    Set-Content -LiteralPath $pidFile -Value $listener.OwningProcess
    $stopwatch.Stop()
    Write-Output "EOAT Atlas API running on 127.0.0.1:$Port (PID $($process.Id)); database=$($health.database_reachable); schema=$($health.current_schema_revision); writes=$($health.writes_enabled); ready_seconds=$([Math]::Round($stopwatch.Elapsed.TotalSeconds, 2))"
} catch {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
    throw
}
