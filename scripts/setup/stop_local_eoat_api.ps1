$stateDir = Join-Path $env:LOCALAPPDATA 'EOAT Atlas Development'
$pidFile = Join-Path $stateDir 'eoat_api.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'EOAT Atlas API is not running.'; exit 0 }
$apiPid = [int](Get-Content -Raw -LiteralPath $pidFile)
Stop-Process -Id $apiPid -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $apiPid } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
Write-Output "Stopped EOAT Atlas API PID $apiPid."
