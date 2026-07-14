[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot '..\dev\stop_local_mysql.ps1')
exit $LASTEXITCODE
