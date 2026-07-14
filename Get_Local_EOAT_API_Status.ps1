[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot 'scripts\dev\get_local_eoat_api_status.ps1')
exit $LASTEXITCODE
