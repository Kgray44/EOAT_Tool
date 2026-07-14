[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot 'scripts\dev\start_local_mysql.ps1')
exit $LASTEXITCODE
