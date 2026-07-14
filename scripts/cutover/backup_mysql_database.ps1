[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
Set-Location -LiteralPath $repoRoot
& python -m tools.cutover.rehearsal backup-restore
exit $LASTEXITCODE
