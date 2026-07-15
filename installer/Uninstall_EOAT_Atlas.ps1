[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\EOAT_Atlas",
    [string]$DesktopPath = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Test-PathIsUnder {
    param([string]$ChildPath, [string]$ParentPath)
    $child = [IO.Path]::GetFullPath($ChildPath).TrimEnd("\")
    $parent = [IO.Path]::GetFullPath($ParentPath).TrimEnd("\")
    return ($child + "\").StartsWith($parent + "\", [StringComparison]::OrdinalIgnoreCase)
}

$root = [IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($InstallRoot))
$local = [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd("\")
if (!(Test-PathIsUnder $root $local) -or $root.Equals($local, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to uninstall outside a child of LocalAppData: $root"
}

if ([string]::IsNullOrWhiteSpace($DesktopPath)) {
    $DesktopPath = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
}
$shortcut = Join-Path ([IO.Path]::GetFullPath($DesktopPath)) "EOAT Atlas.lnk"
if (Test-Path -LiteralPath $shortcut -PathType Leaf) {
    $shell = New-Object -ComObject WScript.Shell
    $target = [string]$shell.CreateShortcut($shortcut).TargetPath
    if (Test-PathIsUnder $target $root) {
        Remove-Item -LiteralPath $shortcut -Force
    }
}

foreach ($relative in @("App", "Launcher", "current_app.json", "current_launcher.json", "install_receipt.json")) {
    $path = Join-Path $root $relative
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log = Join-Path $logs ("uninstall_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
@(
    "EOAT Atlas application and launcher binaries removed.",
    "Per-user identity, configuration, cache, pending changes, events, backups, thumbnails, and logs retained.",
    "Install root: $root"
) | Set-Content -LiteralPath $log -Encoding UTF8
Write-Host "EOAT Atlas binaries removed; user/runtime data retained at $root"
