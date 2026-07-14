[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$report = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).ProviderPath 'reports\cutover_rehearsal\backup_restore_validation.json'
if (-not (Test-Path -LiteralPath $report)) { throw 'Backup/restore validation report does not exist.' }
$result = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
if ($result.status -ne 'PASS' -or -not (Test-Path -LiteralPath $result.backup_path)) { throw 'Validated backup artifact is unavailable.' }
$actual = (Get-FileHash -LiteralPath $result.backup_path -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $result.backup_sha256) { throw 'Backup checksum mismatch.' }
Write-Output "Backup checksum and completed restore validation are PASS: $($result.backup_path)"
