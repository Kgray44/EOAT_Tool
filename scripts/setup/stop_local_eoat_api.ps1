[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot '..\dev\stop_local_eoat_api.ps1')
exit $LASTEXITCODE
