[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$TargetDatabase, [Parameter(Mandatory=$true)][string]$BackupPath)
$ErrorActionPreference = 'Stop'
if ($TargetDatabase -notin @('eoat_atlas_restore_check','eoat_atlas_staging_restore_check')) {
    throw 'Restore target is not an allowlisted disposable rehearsal database.'
}
throw 'Direct restore is intentionally gated. Use backup_mysql_database.ps1 for the validated create/restore/reconcile/drop workflow.'
