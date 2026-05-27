[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$TaskNames = @("EOAT Daily Summary", "EOAT Weekly Summary")

foreach ($taskName in $TaskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Host "Scheduled task not found: $taskName"
        continue
    }
    if ($DryRun) {
        Write-Host "[DRY RUN] Would remove scheduled task: $taskName"
        continue
    }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed scheduled task: $taskName"
}

if ($DryRun) {
    Write-Host "Dry run completed. No scheduled tasks were removed."
} else {
    Write-Host "EOAT scheduled summary tasks removed. Reports and logs were not deleted."
}
