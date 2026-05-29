[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [switch]$VerboseLog
)

$ErrorActionPreference = "Stop"
$EmergencyLogPath = Join-Path ([System.IO.Path]::GetTempPath()) "eoat_scheduled_task_emergency.log"

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

function Get-CurrentDirectoryText {
    try {
        $location = Get-Location
        if ($location.ProviderPath) {
            return (ConvertTo-NormalFileSystemPath -PathValue $location.ProviderPath)
        }
        return (ConvertTo-NormalFileSystemPath -PathValue $location.Path)
    } catch {
        return ""
    }
}

function Get-AppRoot {
    $scriptPath = Resolve-NormalPath -PathValue $PSCommandPath -RequireExists
    return (Split-Path -Parent (Split-Path -Parent $scriptPath))
}

function Get-ProjectRootCandidate {
    param([string]$AppRoot, [string]$RequestedProjectRoot)

    if ($RequestedProjectRoot) {
        return (Resolve-NormalPath -PathValue $RequestedProjectRoot)
    }

    $localConfig = Join-Path $AppRoot "config\local_config.json"
    if (Test-Path -LiteralPath $localConfig) {
        try {
            $config = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
            if ($config.project_root) {
                return (Resolve-NormalPath -PathValue ([string]$config.project_root))
            }
        } catch {
            return ""
        }
    }

    return (Resolve-NormalPath -PathValue (Join-Path $AppRoot "examples\demo_project"))
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

function Resolve-PythonExecutable {
    param([string]$RequestedPython)

    $python = if ($RequestedPython) { $RequestedPython } elseif ($env:PYTHON) { $env:PYTHON } else { "python" }
    try {
        $command = Get-Command $python -ErrorAction Stop
        if ($command.Source) {
            return (ConvertTo-NormalFileSystemPath -PathValue $command.Source)
        }
    } catch {
        return (ConvertTo-NormalFileSystemPath -PathValue $python)
    }
    return (ConvertTo-NormalFileSystemPath -PathValue $python)
}

function Quote-CommandPart {
    param([AllowEmptyString()][string]$Value)

    $text = [string]$Value
    if ($text -match '[\s"]') {
        return '"' + ($text -replace '"', '\"') + '"'
    }
    return $text
}

function Join-CommandLine {
    param([string[]]$Parts)

    return (($Parts | ForEach-Object { Quote-CommandPart -Value $_ }) -join " ")
}

function Write-EmergencyLog {
    param([string]$Line)

    try {
        Add-Content -LiteralPath $EmergencyLogPath -Value $Line
    } catch {
    }
}

function Write-ScheduledToolLog {
    param([string]$Root, [string]$Line)

    try {
        if ([string]::IsNullOrWhiteSpace($Root)) {
            throw "Project root is empty."
        }
        $normalRoot = Resolve-NormalPath -PathValue $Root
        $logDir = Join-Path $normalRoot "00_Project_Admin\logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $logPath = Join-Path $logDir "scheduled_tools.log"
        Add-Content -LiteralPath $logPath -Value $Line
        return $true
    } catch {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-EmergencyLog -Line "[$timestamp] NORMAL_LOG_WRITE_FAILED daily_summary root=`"$Root`" error=`"$($_.Exception.Message -replace '"', "'")`" line=$Line"
        return $false
    }
}

function New-LaunchDiagnosticLine {
    param(
        [string]$ScriptPath,
        [string]$ReceivedProjectRoot,
        [string]$ResolvedProjectRoot,
        [bool]$ProjectRootExists,
        [string]$PythonPath,
        [string]$CommandLine
    )

    $entry = [ordered]@{
        timestamp = (Get-Date).ToString("o")
        event = "launch_diagnostic"
        automation = "daily_summary"
        script_path = $ScriptPath
        current_user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        current_directory = Get-CurrentDirectoryText
        received_project_root = $ReceivedProjectRoot
        resolved_project_root = $ResolvedProjectRoot
        project_root_exists = $ProjectRootExists
        python_executable = $PythonPath
        command = $CommandLine
    }
    return ($entry | ConvertTo-Json -Compress -Depth 4)
}

function Get-DailyCreatedReportPath {
    param($Output)

    foreach ($line in $Output) {
        if ([string]$line -match "Created daily status report:\s*(.+)$") {
            return (ConvertTo-NormalFileSystemPath -PathValue $Matches[1].Trim().Trim('"'))
        }
    }
    return ""
}

function Get-DailyExistingReportPath {
    param($Output)

    foreach ($line in $Output) {
        if ([string]$line -match "Daily status report already exists; no duplicate was created:\s*(.+)$") {
            return (ConvertTo-NormalFileSystemPath -PathValue $Matches[1].Trim().Trim('"'))
        }
    }
    return ""
}

$started = Get-Date
$appRoot = ""
$projectRootForLogging = ""

try {
    $appRoot = Get-AppRoot
    $scriptPath = Resolve-NormalPath -PathValue $PSCommandPath -RequireExists
    $projectRootForLogging = Get-ProjectRootCandidate -AppRoot $appRoot -RequestedProjectRoot $ProjectRoot
    $python = Resolve-PythonExecutable -RequestedPython $PythonExe
    $script = Resolve-NormalPath -PathValue (Join-Path $appRoot "daily_status_summary.py") -RequireExists
    $launchArgs = @(
        $script,
        "--project-root", $projectRootForLogging,
        "--scheduled",
        "--completed", "Reviewed EOAT Command Center dashboard status",
        "--need", "Confirm next EOAT project priority with mentor or supervisor",
        "--plan", "Continue EOAT project execution from the current schedule",
        "--note", "Generated by EOAT scheduled summary automation."
    )
    if ($VerboseLog) {
        $launchArgs += "--verbose"
    }
    $launchCommand = Join-CommandLine -Parts (@($python) + $launchArgs)
    $projectRootExists = if ($projectRootForLogging) { Test-Path -LiteralPath $projectRootForLogging } else { $false }
    $launchLine = New-LaunchDiagnosticLine -ScriptPath $scriptPath -ReceivedProjectRoot $ProjectRoot -ResolvedProjectRoot $projectRootForLogging -ProjectRootExists $projectRootExists -PythonPath $python -CommandLine $launchCommand
    Write-EmergencyLog -Line $launchLine
    Write-ScheduledToolLog -Root $projectRootForLogging -Line $launchLine | Out-Null

    $projectRootResolved = Get-ConfiguredProjectRoot -AppRoot $appRoot -RequestedProjectRoot $ProjectRoot
    $projectRootForLogging = $projectRootResolved
    $toolArgs = @(
        $script,
        "--project-root", $projectRootResolved,
        "--scheduled",
        "--completed", "Reviewed EOAT Command Center dashboard status",
        "--need", "Confirm next EOAT project priority with mentor or supervisor",
        "--plan", "Continue EOAT project execution from the current schedule",
        "--note", "Generated by EOAT scheduled summary automation."
    )
    if ($VerboseLog) {
        $toolArgs += "--verbose"
    }
    $commandLine = Join-CommandLine -Parts (@($python) + $toolArgs)

    Set-Location -LiteralPath $appRoot
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Write-ScheduledToolLog -Root $projectRootResolved -Line "[$timestamp] START daily_summary scheduled=true command=`"$($commandLine -replace '"', "'")`"" | Out-Null

    $output = & $python @toolArgs 2>&1
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    $outputText = ($output | Out-String).Trim()
    if ($outputText) {
        Write-Output $outputText
    }

    $elapsed = [Math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    if ($exitCode -ne 0) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $safeOutput = $outputText -replace '"', "'"
        $line = "[$timestamp] FAILURE daily_summary exit_code=$exitCode elapsed=${elapsed}s error=`"$safeOutput`""
        Write-ScheduledToolLog -Root $projectRootResolved -Line $line | Out-Null
        Write-EmergencyLog -Line $line
        exit $exitCode
    }

    $createdReport = Get-DailyCreatedReportPath -Output $output
    $existingReport = Get-DailyExistingReportPath -Output $output
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    if ($createdReport -and (Test-Path -LiteralPath $createdReport)) {
        $line = "[$timestamp] SUCCESS daily_summary report_created=true output=`"$createdReport`" elapsed=${elapsed}s"
        Write-ScheduledToolLog -Root $projectRootResolved -Line $line | Out-Null
        exit 0
    }
    if ($existingReport -and (Test-Path -LiteralPath $existingReport)) {
        $line = "[$timestamp] SKIPPED daily_summary report_created=false reason=`"report already exists`" output=`"$existingReport`" elapsed=${elapsed}s"
        Write-ScheduledToolLog -Root $projectRootResolved -Line $line | Out-Null
        exit 0
    }

    $safeOutput = $outputText -replace '"', "'"
    $line = "[$timestamp] FAILURE daily_summary report_created=false elapsed=${elapsed}s error=`"python exited 0 but no report file was confirmed. Output: $safeOutput`""
    Write-ScheduledToolLog -Root $projectRootResolved -Line $line | Out-Null
    Write-EmergencyLog -Line $line
    exit 1
} catch {
    $elapsed = [Math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $message = $_.Exception.Message -replace '"', "'"
    $line = "[$timestamp] FAILURE daily_summary elapsed=${elapsed}s error=`"$message`""
    Write-EmergencyLog -Line $line
    if ($projectRootForLogging) {
        Write-ScheduledToolLog -Root $projectRootForLogging -Line $line | Out-Null
    }
    Write-Error $_
    exit 1
}
