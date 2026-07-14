[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot 'scripts\dev\get_local_mysql_status.ps1')
exit $LASTEXITCODE
