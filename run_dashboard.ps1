param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalWorkDir = $env:USERPROFILE
$Candidates = @()

if ($PythonPath) {
    $Candidates += $PythonPath
}

$Candidates += Join-Path $ScriptDir ".venv\Scripts\python.exe"

foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path $Candidate)) {
        Push-Location $LocalWorkDir
        try {
            & $Candidate (Join-Path $ScriptDir "run_dashboard.py")
            exit $LASTEXITCODE
        }
        finally {
            Pop-Location
        }
    }
}

$pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
if ($pyLauncher) {
    Push-Location $LocalWorkDir
    try {
        & $pyLauncher.Source -3 (Join-Path $ScriptDir "run_dashboard.py")
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

$python = Get-Command python.exe -ErrorAction SilentlyContinue
if ($python -and ($python.Source -notlike "*WindowsApps*")) {
    Push-Location $LocalWorkDir
    try {
        & $python.Source (Join-Path $ScriptDir "run_dashboard.py")
        exit $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}

Write-Host "No usable Python interpreter was found."
Write-Host "Install Python, disable the Windows Store Python alias, or run:"
Write-Host ".\run_dashboard.ps1 -PythonPath `"C:\Path\To\python.exe`""
exit 1
