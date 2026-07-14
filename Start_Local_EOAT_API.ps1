[CmdletBinding()]
param([switch]$ReadOnly)
& (Join-Path $PSScriptRoot 'scripts\dev\start_local_eoat_api.ps1') -ReadOnly:$ReadOnly
exit $LASTEXITCODE
