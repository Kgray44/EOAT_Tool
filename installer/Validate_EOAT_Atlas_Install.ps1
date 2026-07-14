[CmdletBinding()]
param(
    [string]$ConfigPath = "",
    [string]$InstallRoot = "",
    [string]$RuntimeRoot = "",
    [string]$DesktopPath = "",
    [switch]$LaunchSmoke
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Get-ConfigValue {
    param($Config, [string]$Name, $Default = $null)
    if ($null -eq $Config) { return $Default }
    $prop = $Config.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) { return $Default }
    return $prop.Value
}

function Read-JsonObject {
    param([string]$Path)
    if (!(Test-Path -LiteralPath $Path)) { return $null }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    return $raw | ConvertFrom-Json
}

function ConvertTo-FullPath {
    param([string]$PathText, [string]$BasePath)
    $expanded = [Environment]::ExpandEnvironmentVariables($PathText)
    if ([string]::IsNullOrWhiteSpace($expanded)) { return "" }
    if ([System.IO.Path]::IsPathRooted($expanded)) { return [System.IO.Path]::GetFullPath($expanded) }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $expanded))
}

function Test-PathIsUnder {
    param([string]$ChildPath, [string]$ParentPath)
    $child = [System.IO.Path]::GetFullPath($ChildPath).TrimEnd("\")
    $parent = [System.IO.Path]::GetFullPath($ParentPath).TrimEnd("\")
    if ($child.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    return ($child + "\").StartsWith($parent + "\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Add-Result {
    param(
        [System.Collections.Generic.List[object]]$Results,
        [string]$Name,
        [bool]$Passed,
        [string]$Detail
    )
    $status = "PASS"
    if (!$Passed) { $status = "FAIL" }
    Write-Host ("{0} {1}: {2}" -f $status, $Name, $Detail)
    [void]$Results.Add([pscustomobject]@{
        name = $Name
        passed = $Passed
        detail = $Detail
    })
}

function Get-ShortcutTargetPath {
    param([string]$ShortcutPath)
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    return [string]$shortcut.TargetPath
}

function Test-NoBlockedLaunchers {
    param([string]$RootPath)
    $patterns = @(
        "command[\s_\-]*center",
        "eoat[\s_\-]*command",
        "dashboard[\s_\-]*launcher",
        "classic[\s_\-]*atlas",
        "legacy[\s_\-]*atlas",
        "atlas[\s_\-]*classic",
        "atlas[\s_\-]*legacy"
    )
    $files = @(Get-ChildItem -LiteralPath $RootPath -Recurse -File -Force -Include *.exe,*.cmd,*.bat,*.ps1,*.lnk -ErrorAction SilentlyContinue)
    foreach ($file in $files) {
        foreach ($pattern in $patterns) {
            if ($file.Name -match $pattern) {
                return $false
            }
        }
    }
    return $true
}

$results = New-Object System.Collections.Generic.List[object]
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $scriptDir "installer_config.json"
} else {
    $ConfigPath = ConvertTo-FullPath $ConfigPath $scriptDir
}
$config = Read-JsonObject $ConfigPath
if ($null -eq $config) {
    Write-Host "FAIL config: installer config not found or unreadable: $ConfigPath"
    exit 1
}
$configDir = Split-Path -Parent $ConfigPath

if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
    $InstallRoot = [string](Get-ConfigValue $config "install_root" "%LOCALAPPDATA%\EOAT_Atlas")
}
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = [string](Get-ConfigValue $config "runtime_root" "%LOCALAPPDATA%\EOAT_Atlas")
}
$installRootResolved = ConvertTo-FullPath $InstallRoot $configDir
$runtimeRootResolved = ConvertTo-FullPath $RuntimeRoot $configDir

if ([string]::IsNullOrWhiteSpace($DesktopPath)) {
    $DesktopPath = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
}
$desktopResolved = [System.IO.Path]::GetFullPath($DesktopPath)
$shortcutName = [string](Get-ConfigValue $config "desktop_shortcut_name" "EOAT Atlas.lnk")
$shortcutPath = Join-Path $desktopResolved $shortcutName

$currentAppPath = Join-Path $runtimeRootResolved "current_app.json"
$currentLauncherPath = Join-Path $runtimeRootResolved "current_launcher.json"
$identityPath = Join-Path $runtimeRootResolved "install_identity.json"
$globalConfigPath = Join-Path $runtimeRootResolved "config\global_config.json"
$logsDir = Join-Path $runtimeRootResolved "logs"

Add-Result $results "install root exists" (Test-Path -LiteralPath $installRootResolved -PathType Container) $installRootResolved
Add-Result $results "runtime root exists" (Test-Path -LiteralPath $runtimeRootResolved -PathType Container) $runtimeRootResolved
Add-Result $results "current_app.json exists" (Test-Path -LiteralPath $currentAppPath -PathType Leaf) $currentAppPath

$currentApp = Read-JsonObject $currentAppPath
$appExePath = ""
$metadataPath = ""
$appInstallPath = ""
if ($currentApp) {
    $appExePath = [string](Get-ConfigValue $currentApp "app_exe_path" "")
    $metadataPath = [string](Get-ConfigValue $currentApp "metadata_path" "")
    $appInstallPath = [string](Get-ConfigValue $currentApp "app_install_path" "")
}

Add-Result $results "installed app exe exists" (![string]::IsNullOrWhiteSpace($appExePath) -and (Test-Path -LiteralPath $appExePath -PathType Leaf)) $appExePath
Add-Result $results "installed release metadata exists" (![string]::IsNullOrWhiteSpace($metadataPath) -and (Test-Path -LiteralPath $metadataPath -PathType Leaf)) $metadataPath
Add-Result $results "install_identity.json exists" (Test-Path -LiteralPath $identityPath -PathType Leaf) $identityPath
Add-Result $results "global_config.json exists" (Test-Path -LiteralPath $globalConfigPath -PathType Leaf) $globalConfigPath
Add-Result $results "desktop shortcut exists" (Test-Path -LiteralPath $shortcutPath -PathType Leaf) $shortcutPath

$launcher = Read-JsonObject $currentLauncherPath
$launcherStatus = "not_installed"
$launcherExePath = ""
if ($launcher) {
    $launcherStatus = [string](Get-ConfigValue $launcher "status" "not_installed")
    $launcherExePath = [string](Get-ConfigValue $launcher "launcher_exe_path" "")
}
$expectedShortcutTarget = $appExePath
if ($launcherStatus -eq "installed") {
    $expectedShortcutTarget = $launcherExePath
}
$actualShortcutTarget = ""
if (Test-Path -LiteralPath $shortcutPath) {
    try {
        $actualShortcutTarget = Get-ShortcutTargetPath $shortcutPath
    } catch {
        $actualShortcutTarget = ""
    }
}
Add-Result $results "shortcut target is correct" ($actualShortcutTarget.Equals($expectedShortcutTarget, [System.StringComparison]::OrdinalIgnoreCase)) "actual=$actualShortcutTarget expected=$expectedShortcutTarget"

$runtimeDirs = @(
    "pending",
    "events",
    "events\outbox",
    "events\written",
    "events\failed",
    "logs"
)
foreach ($relative in $runtimeDirs) {
    $dir = Join-Path $runtimeRootResolved $relative
    Add-Result $results "runtime folder $relative exists" (Test-Path -LiteralPath $dir -PathType Container) $dir
}

$runtimeRootDirsInsideApp = $false
if (![string]::IsNullOrWhiteSpace($appInstallPath) -and (Test-Path -LiteralPath $appInstallPath)) {
    foreach ($name in @("pending", "events", "logs", "data", "sync", "staging", "backups", "thumbnails", "temp", "config")) {
        if (Test-Path -LiteralPath (Join-Path $appInstallPath $name)) {
            $runtimeRootDirsInsideApp = $true
        }
    }
}
Add-Result $results "runtime data not placed inside app version folder" (!$runtimeRootDirsInsideApp) $appInstallPath
Add-Result $results "app folder does not contain local_cache.db" (!(Test-Path -LiteralPath (Join-Path $appInstallPath "data\local_cache.db"))) $appInstallPath
Add-Result $results "Command Center launchers absent" ((![string]::IsNullOrWhiteSpace($appInstallPath)) -and (Test-NoBlockedLaunchers $appInstallPath)) $appInstallPath
Add-Result $results "classic/legacy Atlas launchers absent" ((![string]::IsNullOrWhiteSpace($appInstallPath)) -and (Test-NoBlockedLaunchers $appInstallPath)) $appInstallPath

$latestLog = @(Get-ChildItem -LiteralPath $logsDir -Filter "installer_*.log" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
Add-Result $results "installer log exists" ($latestLog.Count -gt 0) $logsDir

$globalConfig = Read-JsonObject $globalConfigPath
$prodWrites = $true
$writeMode = "enabled"
if ($globalConfig) {
    $prodWrites = [bool](Get-ConfigValue $globalConfig "production_writes_enabled" $false)
    $writeMode = [string](Get-ConfigValue $globalConfig "write_mode" "disabled")
}
Add-Result $results "production writes are disabled" ((!$prodWrites) -and ($writeMode -ne "enabled")) "production_writes_enabled=$prodWrites write_mode=$writeMode"
if ($launcherStatus -eq "installed") {
    Add-Result $results "launcher installed and shortcut points to launcher" ($actualShortcutTarget.Equals($launcherExePath, [System.StringComparison]::OrdinalIgnoreCase)) $launcherExePath
} else {
    Add-Result $results "launcher not installed and shortcut points to app" ($actualShortcutTarget.Equals($appExePath, [System.StringComparison]::OrdinalIgnoreCase)) $appExePath
}

if ($LaunchSmoke) {
    if ([string]::IsNullOrWhiteSpace($expectedShortcutTarget) -or !(Test-Path -LiteralPath $expectedShortcutTarget)) {
        Add-Result $results "LaunchSmoke target exists" $false $expectedShortcutTarget
    } else {
        try {
            $process = Start-Process -FilePath $expectedShortcutTarget -WorkingDirectory (Split-Path -Parent $expectedShortcutTarget) -PassThru -ErrorAction Stop
            Start-Sleep -Seconds 3
            if (!$process.HasExited) {
                $process.CloseMainWindow() | Out-Null
            }
            Add-Result $results "LaunchSmoke" $true "Process started. Endpoint security did not block process creation."
        } catch {
            Add-Result $results "LaunchSmoke endpoint security" $false "Launch failed or was blocked by endpoint security: $($_.Exception.Message)"
        }
    }
}

$failed = @($results | Where-Object { !$_.passed })
if ($failed.Count -gt 0) {
    Write-Host ("EOAT Atlas install validation failed: {0} check(s) failed." -f $failed.Count)
    exit 1
}

Write-Host "EOAT Atlas install validation passed."
exit 0
