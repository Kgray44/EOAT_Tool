[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
Set-Location -LiteralPath $repoRoot
& python -m core.development_bootstrap.cli mysql start
exit $LASTEXITCODE
