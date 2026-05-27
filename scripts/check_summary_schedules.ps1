[CmdletBinding()]
param(
    [switch]$Json
)

$ErrorActionPreference = "Stop"

$taskNames = @("EOAT Daily Summary", "EOAT Weekly Summary")
$rows = @()

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        $rows += [pscustomobject]@{
            TaskName = $taskName
            Installed = $false
            State = ""
            LastRunTime = ""
            LastResult = ""
            NextRunTime = ""
            Triggers = ""
        }
        continue
    }
    $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -ErrorAction SilentlyContinue
    $triggerText = ($task.Triggers | ForEach-Object { "$($_.DaysOfWeek) at $($_.StartBoundary)" }) -join "; "
    $rows += [pscustomobject]@{
        TaskName = $taskName
        Installed = $true
        State = [string]$task.State
        LastRunTime = [string]$info.LastRunTime
        LastResult = [string]$info.LastTaskResult
        NextRunTime = [string]$info.NextRunTime
        Triggers = $triggerText
    }
}

if ($Json) {
    $rows | ConvertTo-Json -Depth 4
} else {
    $rows | Format-Table -AutoSize
}
