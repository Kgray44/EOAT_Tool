param(
    [string]$Identity = 'dev.engineer',
    [int]$Port = 8765,
    [string]$Python = 'python'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
$stateDir = Join-Path $env:LOCALAPPDATA 'EOAT Atlas Development'
$instanceFile = Join-Path $stateDir 'application-instance-id.txt'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $instanceFile)) {
    Set-Content -LiteralPath $instanceFile -Value ([guid]::NewGuid().ToString())
}

& (Join-Path $PSScriptRoot 'start_local_eoat_api.ps1') -Port $Port -EnableWrites
$env:EOAT_ATLAS_DATA_BACKEND = 'mysql_api'
$env:EOAT_ATLAS_ENVIRONMENT = 'development'
$env:EOAT_ATLAS_WRITES_ENABLED = 'true'
$env:EOAT_ATLAS_DEV_IDENTITY = $Identity
$env:EOAT_ATLAS_INSTANCE_ID = (Get-Content -Raw -LiteralPath $instanceFile).Trim()
$env:EOAT_ATLAS_API_URL = "http://127.0.0.1:$Port"

Push-Location $repoRoot
try {
    & $Python -m app.atlas.main
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
