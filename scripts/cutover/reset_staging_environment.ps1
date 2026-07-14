[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Confirmation)
$ErrorActionPreference = 'Stop'
if ($Confirmation -ne 'EOAT_STAGING_REHEARSAL_ONLY') { throw 'Incorrect reset confirmation marker.' }
$env:EOAT_CONFIRM_STAGING_RESET = $Confirmation
& (Join-Path $PSScriptRoot 'create_local_staging_environment.ps1') -Reset
exit $LASTEXITCODE
