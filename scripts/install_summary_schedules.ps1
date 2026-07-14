[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$DailyTaskName = "EOAT Daily Summary"
$WeeklyTaskName = "EOAT Weekly Summary"

function ConvertTo-NormalFileSystemPath {
    param([AllowEmptyString()][string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }

    $text = [string]$PathValue
    $providerPrefix = "Microsoft.PowerShell.Core\FileSystem::"
    if ($text.StartsWith($providerPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $text = $text.Substring($providerPrefix.Length)
    }
    if ($text.StartsWith("//")) {
        $text = "\\" + $text.Substring(2)
    }
    if ($text.StartsWith("\\")) {
        $text = $text.Replace("/", "\")
    }
    return $text
}

function Resolve-NormalPath {
    param(
        [string]$PathValue,
        [switch]$RequireExists
    )

    $normalized = ConvertTo-NormalFileSystemPath -PathValue $PathValue
    try {
        $resolved = Resolve-Path -LiteralPath $normalized -ErrorAction Stop | Select-Object -First 1
        if ($resolved.ProviderPath) {
            return (ConvertTo-NormalFileSystemPath -PathValue $resolved.ProviderPath)
        }
        return (ConvertTo-NormalFileSystemPath -PathValue $resolved.Path)
    } catch {
        if ($RequireExists) {
            throw
        }
        return $normalized
    }
}

function Get-AppRoot {
    $scriptPath = Resolve-NormalPath -PathValue $PSCommandPath -RequireExists
    return (Split-Path -Parent (Split-Path -Parent $scriptPath))
}

function Get-ConfiguredProjectRoot {
    param([string]$AppRoot, [string]$RequestedProjectRoot)

    if ($RequestedProjectRoot) {
        return (Resolve-NormalPath -PathValue $RequestedProjectRoot -RequireExists)
    }

    $localConfig = Join-Path $AppRoot "config\local_config.json"
    if (Test-Path -LiteralPath $localConfig) {
        try {
            $config = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
            if ($config.project_root) {
                return (Resolve-NormalPath -PathValue ([string]$config.project_root) -RequireExists)
            }
        } catch {
            throw "Could not use local config project_root. Fix config/local_config.json or pass -ProjectRoot. $($_.Exception.Message)"
        }
    }

    return (Resolve-NormalPath -PathValue (Join-Path $AppRoot "examples\demo_project") -RequireExists)
}

function Register-EoatTask {
    param(
        [string]$TaskName,
        [string]$ScriptPath,
        [string[]]$DaysOfWeek,
        [string]$AppRoot,
        [string]$ProjectRoot
    )

    $scriptPath = Resolve-NormalPath -PathValue $ScriptPath -RequireExists
    $appRoot = Resolve-NormalPath -PathValue $AppRoot -RequireExists
    $projectRoot = Resolve-NormalPath -PathValue $ProjectRoot -RequireExists

    $argument = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$projectRoot`""
    if ($DryRun) {
        Write-Host "[DRY RUN] Would register '$TaskName'"
        Write-Host "          powershell.exe $argument"
        Write-Host "          Weekly on $($DaysOfWeek -join ', ') at 7:00 PM"
        return
    }

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $appRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DaysOfWeek -At 7:00PM
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "EOAT Command Center scheduled summary automation." -Force | Out-Null
    Write-Host "Installed/updated scheduled task: $TaskName"
}

$appRoot = Get-AppRoot
$projectRootResolved = Get-ConfiguredProjectRoot -AppRoot $appRoot -RequestedProjectRoot $ProjectRoot
$dailyScript = Resolve-NormalPath -PathValue (Join-Path $appRoot "scripts\run_daily_summary.ps1") -RequireExists
$weeklyScript = Resolve-NormalPath -PathValue (Join-Path $appRoot "scripts\run_weekly_summary.ps1") -RequireExists

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
