[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
Set-Location -LiteralPath $repoRoot
& python run_atlas.py --backend mysql_api --environment development
exit $LASTEXITCODE
