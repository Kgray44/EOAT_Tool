[CmdletBinding()]
param()
& (Join-Path $PSScriptRoot '..\dev\start_local_mysql.ps1')
exit $LASTEXITCODE
