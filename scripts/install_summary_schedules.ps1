[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$DailyTaskName = "EOAT Daily Summary"
$WeeklyTaskName = "EOAT Weekly Summary"

function Get-AppRoot {
    return (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}

function Get-ConfiguredProjectRoot {
    param([string]$AppRoot, [string]$RequestedProjectRoot)

    if ($RequestedProjectRoot) {
        return (Resolve-Path -LiteralPath $RequestedProjectRoot).Path
    }

    $localConfig = Join-Path $AppRoot "config\local_config.json"
    if (Test-Path -LiteralPath $localConfig) {
        try {
            $config = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
            if ($config.project_root) {
                return (Resolve-Path -LiteralPath ([string]$config.project_root)).Path
            }
        } catch {
            throw "Could not use local config project_root. Fix config/local_config.json or pass -ProjectRoot. $($_.Exception.Message)"
        }
    }

    return (Resolve-Path -LiteralPath (Join-Path $AppRoot "examples\demo_project")).Path
}

function Register-EoatTask {
    param(
        [string]$TaskName,
        [string]$ScriptPath,
        [string[]]$DaysOfWeek,
        [string]$AppRoot,
        [string]$ProjectRoot
    )

    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`" -ProjectRoot `"$ProjectRoot`""
    if ($DryRun) {
        Write-Host "[DRY RUN] Would register '$TaskName'"
        Write-Host "          powershell.exe $argument"
        Write-Host "          Weekly on $($DaysOfWeek -join ', ') at 7:00 PM"
        return
    }

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $AppRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DaysOfWeek -At 7:00PM
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "EOAT Command Center scheduled summary automation." -Force | Out-Null
    Write-Host "Installed/updated scheduled task: $TaskName"
}

$appRoot = Get-AppRoot
$projectRootResolved = Get-ConfiguredProjectRoot -AppRoot $appRoot -RequestedProjectRoot $ProjectRoot
$dailyScript = Join-Path $appRoot "scripts\run_daily_summary.ps1"
$weeklyScript = Join-Path $appRoot "scripts\run_weekly_summary.ps1"

Write-Host "EOAT Command Center app root: $appRoot"
Write-Host "EOAT project root: $projectRootResolved"
Write-Host "Daily schedule: Monday-Thursday at 7:00 PM"
Write-Host "Weekly schedule: Friday at 7:00 PM"

Register-EoatTask -TaskName $DailyTaskName -ScriptPath $dailyScript -DaysOfWeek @("Monday", "Tuesday", "Wednesday", "Thursday") -AppRoot $appRoot -ProjectRoot $projectRootResolved
Register-EoatTask -TaskName $WeeklyTaskName -ScriptPath $weeklyScript -DaysOfWeek @("Friday") -AppRoot $appRoot -ProjectRoot $projectRootResolved

if ($DryRun) {
    Write-Host "Dry run completed. No scheduled tasks were changed."
} else {
    Write-Host "Scheduled summaries are installed."
}
