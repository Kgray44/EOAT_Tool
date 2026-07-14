[CmdletBinding()]
param([switch]$ReadOnly)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
Set-Location -LiteralPath $repoRoot
$arguments = @('-m', 'core.development_bootstrap.cli', 'api', 'start')
if ($ReadOnly) { $arguments += '--read-only' }
& python @arguments
exit $LASTEXITCODE
