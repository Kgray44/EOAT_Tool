[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$pidFile = Join-Path $env:LOCALAPPDATA 'EOAT Atlas Staging\eoat_api.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'Staging API is not running.'; exit 0 }
$processId = [int](Get-Content -Raw -LiteralPath $pidFile)
Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFile -Force
Write-Output "Stopped staging API PID $processId."
