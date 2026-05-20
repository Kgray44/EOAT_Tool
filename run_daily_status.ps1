param(
    [int]$Week = 1,
    [int]$Day,
    [string]$ProjectRoot,
    [switch]$IncludeGit,
    [switch]$IncludeSnapshot,
    [switch]$Interactive
)

$ErrorActionPreference = "Stop"

# Runs the EOAT daily status summary tool from this toolkit folder.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "daily_status_summary.py"
$pythonCommand = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { "python" }

if (-not (Test-Path $pythonScript)) {
    throw "Could not find daily_status_summary.py in $scriptDir"
}

if (-not $ProjectRoot) {
    $ProjectRoot = Join-Path $scriptDir "EOAT_Standardization_Project"
}

$arguments = @(
    $pythonScript,
    "--project-root", $ProjectRoot,
    "--week", $Week
)

if ($PSBoundParameters.ContainsKey("Day")) {
    $arguments += @("--day", $Day)
}

if ($IncludeGit) {
    $arguments += "--include-git"
}

if ($IncludeSnapshot) {
    $arguments += "--include-snapshot"
}

if ($Interactive) {
    $arguments += "--interactive"
}

Set-Location $scriptDir
& $pythonCommand @arguments
