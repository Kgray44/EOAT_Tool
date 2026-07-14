[CmdletBinding()]
param([switch]$Reset)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath
Set-Location -LiteralPath $repoRoot
if ($Reset -and $env:EOAT_CONFIRM_STAGING_RESET -ne 'EOAT_STAGING_REHEARSAL_ONLY') {
    throw 'Set EOAT_CONFIRM_STAGING_RESET=EOAT_STAGING_REHEARSAL_ONLY to reset the allowlisted local staging database.'
}
$arguments = @('-m','tools.cutover.rehearsal','environment')
if ($Reset) { $arguments += '--reset' }
& python @arguments
exit $LASTEXITCODE
