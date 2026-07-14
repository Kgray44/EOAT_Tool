[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot 'scripts\dev\stop_local_eoat_api.ps1')
exit $LASTEXITCODE
