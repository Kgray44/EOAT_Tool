[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot 'scripts\dev\stop_local_mysql.ps1')
exit $LASTEXITCODE
