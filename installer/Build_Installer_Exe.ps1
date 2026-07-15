[CmdletBinding()]
param(
    [string]$PythonExe = "python",
    [switch]$Clean
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workDir = Join-Path (Split-Path -Parent $scriptDir) "build\installer"
$distDir = Join-Path $scriptDir "dist"
$wrapperPath = Join-Path $workDir "install_eoat_atlas_entry.py"
$manifestPath = Join-Path $workDir "installer_asInvoker.manifest"

if ($Clean) {
    foreach ($path in @($workDir, $distDir)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

New-Item -ItemType Directory -Force -Path $workDir | Out-Null
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

$pyInstallerCheck = & $PythonExe -m PyInstaller --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller is not available in the selected Python environment."
    Write-Host "No installer exe was built. The script installer remains the supported installer path."
    Write-Host "Install PyInstaller through the approved internal Python environment, then rerun this script."
    exit 2
}

$wrapper = @'
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def installer_root() -> Path:
    exe_path = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    candidates = [
        exe_path.parent,
        exe_path.parent.parent,
    ]
    for candidate in candidates:
        if (candidate / "Install_EOAT_Atlas.ps1").exists():
            return candidate
    return exe_path.parent


def main() -> int:
    root = installer_root()
    script = root / "Install_EOAT_Atlas.ps1"
    config = root / "installer_config.json"
    if not script.exists():
        print(f"Installer script was not found: {script}", file=sys.stderr)
        return 2
    if not config.exists():
        print(f"Installer config was not found: {config}", file=sys.stderr)
        return 2
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "RemoteSigned",
        "-File",
        str(script),
        "-ConfigPath",
        str(config),
        *sys.argv[1:],
    ]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
'@
Set-Content -LiteralPath $wrapperPath -Value $wrapper -Encoding UTF8

$manifest = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false" />
      </requestedPrivileges>
    </security>
  </trustInfo>
</assembly>
'@
Set-Content -LiteralPath $manifestPath -Value $manifest -Encoding UTF8

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "Install EOAT Atlas" `
    --manifest $manifestPath `
    --distpath $distDir `
    --workpath (Join-Path $workDir "pyinstaller") `
    --specpath $workDir `
    $wrapperPath

if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller build failed. The script installer remains the supported installer path."
    exit $LASTEXITCODE
}

$exePath = Join-Path $distDir "Install EOAT Atlas.exe"
if (!(Test-Path -LiteralPath $exePath)) {
    Write-Host "PyInstaller completed but the expected exe was not found: $exePath"
    exit 1
}

# The no-elevation exe is intentionally a thin launcher. Keep its two audited
# runtime inputs beside it so the public installer folder is self-contained.
Copy-Item -LiteralPath (Join-Path $scriptDir "Install_EOAT_Atlas.ps1") -Destination $distDir -Force
Copy-Item -LiteralPath (Join-Path $scriptDir "Uninstall_EOAT_Atlas.ps1") -Destination $distDir -Force
Copy-Item -LiteralPath (Join-Path $scriptDir "installer_config.json") -Destination $distDir -Force
$repositoryRoot = Split-Path -Parent $scriptDir
$appSource = Join-Path $repositoryRoot "dist\EOAT Atlas"
$launcherSource = Join-Path $repositoryRoot "dist\launcher"
if (!(Test-Path -LiteralPath (Join-Path $appSource "EOAT Atlas.exe"))) {
    throw "Build the EOAT Atlas onedir package before building the distributable installer."
}
if (!(Test-Path -LiteralPath (Join-Path $launcherSource "EOAT Atlas Launcher.exe"))) {
    throw "Build the EOAT Atlas launcher before building the distributable installer."
}
Copy-Item -LiteralPath $appSource -Destination $distDir -Recurse -Force
Copy-Item -LiteralPath $launcherSource -Destination $distDir -Recurse -Force

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exePath).Hash
Write-Host "Built installer exe: $exePath"
Write-Host "SHA-256: $hash"
Write-Host "This exe does not request elevation. If endpoint security blocks it, use Install_EOAT_Atlas.cmd and provide this hash to IT."
exit 0
