[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$ValidateOnly,
    [string]$SourceReleasePath = "",
    [string]$InstallRoot = "",
    [string]$RuntimeRoot = "",
    [string]$DesktopPath = "",
    [switch]$AllowElevated,
    [switch]$VerboseLog,
    [string]$ConfigPath = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$script:InstallerScriptVersion = "0.1.0"
$script:LogPath = $null
$script:BufferedLogLines = New-Object System.Collections.Generic.List[string]

function New-NowIso {
    return (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
}

function New-Timestamp {
    return (Get-Date).ToString("yyyyMMdd_HHmmss")
}

function Write-InstallLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [string]$Level = "INFO"
    )
    $line = "{0} [{1}] {2}" -f (New-NowIso), $Level.ToUpperInvariant(), $Message
    Write-Host $line
    if ($script:LogPath) {
        Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
    } else {
        [void]$script:BufferedLogLines.Add($line)
    }
}

function Start-InstallerLog {
    param([Parameter(Mandatory = $true)][string]$Path)
    $script:LogPath = $Path
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Set-Content -LiteralPath $Path -Value $script:BufferedLogLines.ToArray() -Encoding UTF8
}

function Stop-WithError {
    param([Parameter(Mandatory = $true)][string]$Message, [int]$ExitCode = 1)
    Write-InstallLog $Message "ERROR"
    throw $Message
}

function Get-ConfigValue {
    param(
        $Config,
        [Parameter(Mandatory = $true)][string]$Name,
        $Default = $null
    )
    if ($null -eq $Config) {
        return $Default
    }
    $prop = $Config.PSObject.Properties[$Name]
    if ($null -eq $prop) {
        return $Default
    }
    if ($null -eq $prop.Value) {
        return $Default
    }
    return $prop.Value
}

function Read-JsonObject {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (!(Test-Path -LiteralPath $Path)) {
        return $null
    }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return $raw | ConvertFrom-Json
}

function Write-JsonObject {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Payload
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $json = $Payload | ConvertTo-Json -Depth 12
    $tmp = Join-Path (Split-Path -Parent $Path) (".{0}.{1}.tmp" -f (Split-Path -Leaf $Path), ([guid]::NewGuid().ToString("N")))
    Set-Content -LiteralPath $tmp -Value $json -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function ConvertTo-FullPath {
    param(
        [Parameter(Mandatory = $true)][string]$PathText,
        [Parameter(Mandatory = $true)][string]$BasePath
    )
    $expanded = [Environment]::ExpandEnvironmentVariables($PathText)
    if ([string]::IsNullOrWhiteSpace($expanded)) {
        return ""
    }
    if ([System.IO.Path]::IsPathRooted($expanded)) {
        return [System.IO.Path]::GetFullPath($expanded)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $expanded))
}

function Test-PathIsUnder {
    param(
        [Parameter(Mandatory = $true)][string]$ChildPath,
        [Parameter(Mandatory = $true)][string]$ParentPath
    )
    $child = [System.IO.Path]::GetFullPath($ChildPath).TrimEnd("\")
    $parent = [System.IO.Path]::GetFullPath($ParentPath).TrimEnd("\")
    if ($child.Equals($parent, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return ($child + "\").StartsWith($parent + "\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-LocalAppDataPath {
    $path = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($path)) {
        $path = $env:LOCALAPPDATA
    }
    if ([string]::IsNullOrWhiteSpace($path)) {
        Stop-WithError "LOCALAPPDATA could not be determined for the current user."
    }
    return [System.IO.Path]::GetFullPath($path)
}

function Assert-PerUserLocalAppDataPath {
    param(
        [Parameter(Mandatory = $true)][string]$PathText,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $full = [System.IO.Path]::GetFullPath($PathText)
    $localAppData = Get-LocalAppDataPath
    $programFiles = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { ![string]::IsNullOrWhiteSpace($_) }
    foreach ($pf in $programFiles) {
        if (Test-PathIsUnder $full $pf) {
            Stop-WithError "$Label resolves under Program Files, which is not allowed: $full"
        }
    }
    if (!(Test-PathIsUnder $full $localAppData)) {
        Stop-WithError "$Label must resolve under the current user's LOCALAPPDATA. Resolved path: $full"
    }
}

function Test-IsElevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function ConvertTo-SafePathSegment {
    param([Parameter(Mandatory = $true)][string]$Value)
    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    $chars = New-Object System.Collections.Generic.List[char]
    foreach ($char in $Value.ToCharArray()) {
        if ($invalid -contains $char) {
            [void]$chars.Add("_")
        } elseif ([char]::IsWhiteSpace($char)) {
            [void]$chars.Add("_")
        } else {
            [void]$chars.Add($char)
        }
    }
    $safe = -join $chars
    $safe = $safe.Trim("._- ")
    if ([string]::IsNullOrWhiteSpace($safe)) {
        $safe = "release_" + (New-Timestamp)
    }
    return $safe
}

function Get-DirectoryStats {
    param([Parameter(Mandatory = $true)][string]$Path)
    $files = @(Get-ChildItem -LiteralPath $Path -Recurse -File -Force)
    $bytes = 0L
    foreach ($file in $files) {
        $bytes += [int64]$file.Length
    }
    return [ordered]@{
        file_count = $files.Count
        total_bytes = $bytes
    }
}

function Get-FileSha256Text {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToUpperInvariant()
}

function Find-ManifestPath {
    param(
        [string]$ConfiguredManifestPath,
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$ConfigDir
    )
    if (![string]::IsNullOrWhiteSpace($ConfiguredManifestPath)) {
        return ConvertTo-FullPath $ConfiguredManifestPath $ConfigDir
    }
    $candidates = @(
        (Join-Path $SourceRoot "manifest.json"),
        (Join-Path $SourceRoot "release_manifest.json"),
        (Join-Path $SourceRoot "file_manifest.json")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return ""
}

function Test-ReleaseManifest {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$SourceRoot
    )
    $payload = Read-JsonObject $ManifestPath
    if ($null -eq $payload) {
        Stop-WithError "Manifest exists but could not be read: $ManifestPath"
    }
    $files = @()
    $prop = $payload.PSObject.Properties["files"]
    if ($prop -and $prop.Value) {
        $files = @($prop.Value)
    } elseif ($payload -is [array]) {
        $files = @($payload)
    }
    if ($files.Count -eq 0) {
        Write-InstallLog "Manifest has no files array; recorded manifest path without hash validation: $ManifestPath" "WARN"
        return [ordered]@{
            manifest_path = $ManifestPath
            manifest_validated = $false
            manifest_file_count = 0
        }
    }
    $checked = 0
    foreach ($item in $files) {
        $relative = Get-ConfigValue $item "path" ""
        if ([string]::IsNullOrWhiteSpace($relative)) {
            $relative = Get-ConfigValue $item "relative_path" ""
        }
        $expectedHash = Get-ConfigValue $item "sha256" ""
        if ([string]::IsNullOrWhiteSpace($relative) -or [string]::IsNullOrWhiteSpace($expectedHash)) {
            continue
        }
        $target = Join-Path $SourceRoot $relative
        if (!(Test-Path -LiteralPath $target)) {
            Stop-WithError "Manifest file is missing from source release: $relative"
        }
        $actualHash = Get-FileSha256Text $target
        if (!($actualHash.Equals($expectedHash, [System.StringComparison]::OrdinalIgnoreCase))) {
            Stop-WithError "Manifest hash mismatch for $relative"
        }
        $checked += 1
    }
    return [ordered]@{
        manifest_path = $ManifestPath
        manifest_validated = $true
        manifest_file_count = $checked
    }
}

function Test-NoBlockedLaunchers {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $blockedPatterns = @(
        "command[\s_\-]*center",
        "eoat[\s_\-]*command",
        "dashboard[\s_\-]*launcher",
        "classic[\s_\-]*atlas",
        "legacy[\s_\-]*atlas",
        "atlas[\s_\-]*classic",
        "atlas[\s_\-]*legacy"
    )
    $files = @(Get-ChildItem -LiteralPath $RootPath -Recurse -File -Force -Include *.exe,*.cmd,*.bat,*.ps1,*.lnk)
    $blocked = New-Object System.Collections.Generic.List[string]
    foreach ($file in $files) {
        foreach ($pattern in $blockedPatterns) {
            if ($file.Name -match $pattern) {
                [void]$blocked.Add($file.FullName)
                break
            }
        }
    }
    if ($blocked.Count -gt 0) {
        Stop-WithError ("Blocked Command Center/classic/legacy launcher artifact found:`n" + ($blocked -join "`n"))
    }
}

function Test-NoRuntimeStateInSource {
    param([Parameter(Mandatory = $true)][string]$RootPath)
    $blockedRootDirs = @("pending", "events", "logs", "sync", "staging", "backups", "thumbnails", "temp")
    foreach ($dir in $blockedRootDirs) {
        if (Test-Path -LiteralPath (Join-Path $RootPath $dir)) {
            Stop-WithError "Source release contains runtime directory '$dir'. Runtime state must not be packaged."
        }
    }
    $blockedFiles = @(
        "data\local_cache.db",
        "data\local_cache.previous.db",
        "install_identity.json",
        "install_receipt.json",
        "current_app.json",
        "current_launcher.json",
        "settings.json",
        "config\global_config.json"
    )
    foreach ($relative in $blockedFiles) {
        if (Test-Path -LiteralPath (Join-Path $RootPath $relative)) {
            Stop-WithError "Source release contains runtime file '$relative'. Runtime state must not be packaged."
        }
    }
}

function Test-SourceRelease {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$ConfigDir
    )
    if (!(Test-Path -LiteralPath $SourceRoot -PathType Container)) {
        Stop-WithError "Source release path does not exist: $SourceRoot"
    }

    $expectedExe = [string](Get-ConfigValue $Config "expected_app_exe_name" "EOAT Atlas.exe")
    $expectedMetadata = [string](Get-ConfigValue $Config "expected_metadata_file" "release_metadata.json")
    $appExe = Join-Path $SourceRoot $expectedExe
    $metadataPath = Join-Path $SourceRoot $expectedMetadata
    if (!(Test-Path -LiteralPath $appExe -PathType Leaf)) {
        Stop-WithError "Expected app executable is missing from source release: $appExe"
    }
    if (!(Test-Path -LiteralPath $metadataPath -PathType Leaf)) {
        Stop-WithError "Expected metadata file is missing from source release: $metadataPath"
    }
    if (!(Test-Path -LiteralPath (Join-Path $SourceRoot "_internal") -PathType Container)) {
        Stop-WithError "Source release does not look like a PyInstaller onedir folder because _internal is missing."
    }

    Test-NoBlockedLaunchers $SourceRoot
    Test-NoRuntimeStateInSource $SourceRoot

    $metadata = Read-JsonObject $metadataPath
    if ($null -eq $metadata) {
        Stop-WithError "App metadata could not be parsed: $metadataPath"
    }
    $appVersion = [string](Get-ConfigValue $metadata "app_version" "")
    $releaseId = [string](Get-ConfigValue $metadata "release_id" "")
    $buildId = [string](Get-ConfigValue $metadata "build_id" "")
    if ([string]::IsNullOrWhiteSpace($appVersion)) {
        $appVersion = ""
    }
    if ([string]::IsNullOrWhiteSpace($releaseId)) {
        $releaseId = [string](Get-ConfigValue $Config "release_id" "")
    }
    if ([string]::IsNullOrWhiteSpace($appVersion) -or [string]::IsNullOrWhiteSpace($releaseId) -or [string]::IsNullOrWhiteSpace($buildId)) {
        Stop-WithError "App version, release id, and build id must be present in release metadata."
    }
    if ($appVersion -notmatch '^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$' -or $releaseId -ne "eoat-atlas-$appVersion") {
        Stop-WithError "Release metadata application version and release id are inconsistent."
    }

    $stats = Get-DirectoryStats $SourceRoot
    $appExeHash = Get-FileSha256Text $appExe
    $manifestPath = Find-ManifestPath ([string](Get-ConfigValue $Config "manifest_path" "")) $SourceRoot $ConfigDir
    $manifestSummary = [ordered]@{
        manifest_path = ""
        manifest_validated = $false
        manifest_file_count = 0
    }
    if (![string]::IsNullOrWhiteSpace($manifestPath)) {
        $manifestSummary = Test-ReleaseManifest $manifestPath $SourceRoot
    }

    return [ordered]@{
        source_release_path = $SourceRoot
        app_exe_path = $appExe
        metadata_path = $metadataPath
        app_name = [string](Get-ConfigValue $metadata "app_name" ([string](Get-ConfigValue $Config "app_name" "EOAT Atlas"))
        )
        app_version = $appVersion
        release_id = $releaseId
        build_id = $buildId
        environment = [string](Get-ConfigValue $metadata "environment" "")
        file_count = $stats.file_count
        total_bytes = $stats.total_bytes
        app_exe_sha256 = $appExeHash
        manifest = $manifestSummary
    }
}

function Ensure-RuntimeLayout {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [switch]$WhatIfOnly
    )
    $directories = @(
        $RuntimeRoot,
        (Join-Path $RuntimeRoot "App"),
        (Join-Path $RuntimeRoot "Launcher"),
        (Join-Path $RuntimeRoot "config"),
        (Join-Path $RuntimeRoot "data"),
        (Join-Path $RuntimeRoot "pending"),
        (Join-Path $RuntimeRoot "events"),
        (Join-Path $RuntimeRoot "events\outbox"),
        (Join-Path $RuntimeRoot "events\written"),
        (Join-Path $RuntimeRoot "events\failed"),
        (Join-Path $RuntimeRoot "sync"),
        (Join-Path $RuntimeRoot "staging"),
        (Join-Path $RuntimeRoot "backups"),
        (Join-Path $RuntimeRoot "logs"),
        (Join-Path $RuntimeRoot "thumbnails"),
        (Join-Path $RuntimeRoot "temp")
    )
    foreach ($dir in $directories) {
        if ($WhatIfOnly) {
            Write-InstallLog "Dry run: would ensure directory $dir"
        } else {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
        }
    }
    if (!$WhatIfOnly) {
        $cacheManifestPath = Join-Path $RuntimeRoot "data\cache_manifest.json"
        if (!(Test-Path -LiteralPath $cacheManifestPath)) {
            Write-JsonObject $cacheManifestPath ([ordered]@{
                cache_schema_version = 1
                status = "not_initialized"
                created_by = "installer"
                created_at = New-NowIso
                local_cache_path = (Join-Path $RuntimeRoot "data\local_cache.db")
            })
        }
    }
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $robocopy = Get-Command robocopy.exe -ErrorAction SilentlyContinue
    if ($robocopy) {
        & robocopy.exe $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /XJ /NFL /NDL /NP /NJH /NJS | Out-Null
        $rc = $LASTEXITCODE
        if ($rc -gt 7) {
            Stop-WithError "Robocopy failed while copying '$Source' to '$Destination' with exit code $rc."
        }
        return
    }
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Install-AppRelease {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRoot,
        [Parameter(Mandatory = $true)][string]$AppVersionsRoot,
        [Parameter(Mandatory = $true)]$SourceSummary,
        [Parameter(Mandatory = $true)]$Config
    )
    $releaseSegment = ConvertTo-SafePathSegment ([string]$SourceSummary.release_id)
    $targetPath = Join-Path $AppVersionsRoot $releaseSegment
    $stagingRoot = Join-Path $AppVersionsRoot ".staging"
    $stagingPath = Join-Path $stagingRoot ("{0}_{1}" -f $releaseSegment, (New-Timestamp))
    $previousRoot = Join-Path $AppVersionsRoot ".previous"

    try {
        Write-InstallLog "Copy start: $SourceRoot -> $stagingPath"
        New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
        Copy-DirectoryContents $SourceRoot $stagingPath

        $stagingStats = Get-DirectoryStats $stagingPath
        $expectedExe = [string](Get-ConfigValue $Config "expected_app_exe_name" "EOAT Atlas.exe")
        $expectedMetadata = [string](Get-ConfigValue $Config "expected_metadata_file" "release_metadata.json")
        if (!(Test-Path -LiteralPath (Join-Path $stagingPath $expectedExe))) {
            Stop-WithError "Staging verification failed: app exe missing."
        }
        if (!(Test-Path -LiteralPath (Join-Path $stagingPath $expectedMetadata))) {
            Stop-WithError "Staging verification failed: release metadata missing."
        }
        if ($stagingStats.file_count -ne $SourceSummary.file_count -or $stagingStats.total_bytes -ne $SourceSummary.total_bytes) {
            Stop-WithError "Staging verification failed: source/staging file counts or byte totals differ."
        }

        if (Test-Path -LiteralPath $targetPath) {
            New-Item -ItemType Directory -Force -Path $previousRoot | Out-Null
            $archivePath = Join-Path $previousRoot ("{0}_{1}" -f $releaseSegment, (New-Timestamp))
            Write-InstallLog "Existing target release found; archiving app version only to $archivePath"
            Move-Item -LiteralPath $targetPath -Destination $archivePath
        }

        Move-Item -LiteralPath $stagingPath -Destination $targetPath
        Write-InstallLog "Copy complete: app release finalized at $targetPath"
    } catch {
        Remove-SafeStaging $stagingRoot $stagingPath
        throw
    }

    return [ordered]@{
        app_install_path = $targetPath
        app_exe_path = (Join-Path $targetPath $expectedExe)
        metadata_path = (Join-Path $targetPath $expectedMetadata)
        release_segment = $releaseSegment
        staging_path = $stagingPath
    }
}

function Install-LauncherIfAvailable {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][string]$ConfigDir,
        [Parameter(Mandatory = $true)][string]$LauncherInstallRoot
    )
    $mode = [string](Get-ConfigValue $Config "install_launcher" "auto_if_available")
    $sourceText = [string](Get-ConfigValue $Config "launcher_source_path" "")
    $expectedExe = [string](Get-ConfigValue $Config "launcher_expected_exe_name" "EOAT Atlas Launcher.exe")
    $now = New-NowIso

    if ([string]::IsNullOrWhiteSpace($sourceText)) {
        if ($mode -eq "true" -or $mode -eq "required") {
            Stop-WithError "Launcher install was required, but launcher_source_path is empty."
        }
        return [ordered]@{
            status = "not_installed"
            reason = "launcher_source_path is empty"
            launcher_install_path = $LauncherInstallRoot
            launcher_exe_path = ""
            updated_at = $now
        }
    }

    $launcherSource = ConvertTo-FullPath $sourceText $ConfigDir
    if (!(Test-Path -LiteralPath $launcherSource)) {
        if ($mode -eq "true" -or $mode -eq "required") {
            Stop-WithError "Launcher install was required, but launcher source was not found: $launcherSource"
        }
        return [ordered]@{
            status = "not_installed"
            reason = "launcher source not found"
            launcher_source_path = $launcherSource
            launcher_install_path = $LauncherInstallRoot
            launcher_exe_path = ""
            updated_at = $now
        }
    }

    $stagingRoot = Join-Path $LauncherInstallRoot ".staging"
    $stagingPath = Join-Path $stagingRoot ("launcher_{0}" -f (New-Timestamp))
    $previousRoot = Join-Path $LauncherInstallRoot ".previous"
    New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
    if (Test-Path -LiteralPath $launcherSource -PathType Container) {
        Copy-DirectoryContents $launcherSource $stagingPath
    } else {
        New-Item -ItemType Directory -Force -Path $stagingPath | Out-Null
        Copy-Item -LiteralPath $launcherSource -Destination (Join-Path $stagingPath (Split-Path -Leaf $launcherSource)) -Force
    }
    $stagedExe = Join-Path $stagingPath $expectedExe
    if (!(Test-Path -LiteralPath $stagedExe)) {
        Stop-WithError "Launcher staging verification failed: expected exe is missing: $stagedExe"
    }

    $existingPayload = @(Get-ChildItem -LiteralPath $LauncherInstallRoot -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -notin @(".staging", ".previous") })
    if ($existingPayload.Count -gt 0) {
        New-Item -ItemType Directory -Force -Path $previousRoot | Out-Null
        $archivePath = Join-Path $previousRoot ("launcher_{0}" -f (New-Timestamp))
        New-Item -ItemType Directory -Force -Path $archivePath | Out-Null
        foreach ($item in $existingPayload) {
            Move-Item -LiteralPath $item.FullName -Destination $archivePath
        }
    }
    Get-ChildItem -LiteralPath $stagingPath -Force | ForEach-Object {
        Move-Item -LiteralPath $_.FullName -Destination $LauncherInstallRoot
    }
    Remove-Item -LiteralPath $stagingPath -Force -Recurse

    return [ordered]@{
        status = "installed"
        launcher_source_path = $launcherSource
        launcher_install_path = $LauncherInstallRoot
        launcher_exe_path = (Join-Path $LauncherInstallRoot $expectedExe)
        updated_at = $now
    }
}

function New-AppInstanceId {
    $machine = $env:COMPUTERNAME
    if ([string]::IsNullOrWhiteSpace($machine)) {
        $machine = "EOAT-ATLAS"
    }
    $safeMachine = ($machine.ToUpperInvariant() -replace "[^A-Z0-9\-]", "-").Trim("-")
    if ([string]::IsNullOrWhiteSpace($safeMachine)) {
        $safeMachine = "EOAT-ATLAS"
    }
    return "{0}_{1}" -f $safeMachine, ([guid]::NewGuid().ToString("N").Substring(0, 6).ToUpperInvariant())
}

function Update-InstallIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$IdentityPath,
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)]$SourceSummary,
        [Parameter(Mandatory = $true)]$InstallState,
        [Parameter(Mandatory = $true)]$LauncherState,
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot
    )
    $existing = Read-JsonObject $IdentityPath
    $now = New-NowIso
    $windowsUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    if ([string]::IsNullOrWhiteSpace($windowsUser)) {
        $windowsUser = $env:USERNAME
    }
    $installId = ""
    $appInstanceId = ""
    $installedAt = $now
    if ($existing) {
        $installId = [string](Get-ConfigValue $existing "install_id" "")
        $appInstanceId = [string](Get-ConfigValue $existing "app_instance_id" "")
        $installedAt = [string](Get-ConfigValue $existing "installed_at" $now)
    }
    if ([string]::IsNullOrWhiteSpace($installId)) {
        $installId = [guid]::NewGuid().ToString()
    }
    if ([string]::IsNullOrWhiteSpace($appInstanceId)) {
        $appInstanceId = New-AppInstanceId
    }
    $payload = [ordered]@{
        identity_schema_version = 2
        install_id = $installId
        app_instance_id = $appInstanceId
        machine_name = $env:COMPUTERNAME
        windows_user = $windowsUser
        installed_by = $windowsUser
        installed_at = $installedAt
        last_installed_at = $now
        installer_version = [string](Get-ConfigValue $Config "installer_version" $script:InstallerScriptVersion)
        app_name = [string](Get-ConfigValue $Config "app_name" "EOAT Atlas")
        app_version_at_install = [string]$SourceSummary.app_version
        release_id_at_install = [string]$SourceSummary.release_id
        build_id_at_install = [string]$SourceSummary.build_id
        install_root = $InstallRoot
        runtime_root = $RuntimeRoot
        app_install_path = [string]$InstallState.app_install_path
        launcher_install_path = [string]$LauncherState.launcher_install_path
        source_release_path = [string]$SourceSummary.source_release_path
        environment = [string](Get-ConfigValue $Config "environment" "production")
        generated_by = "installer"
        production_writes_enabled = $false
    }
    Write-JsonObject $IdentityPath $payload
    return $payload
}

function Get-DefaultSourcePaths {
    $networkRoot = "\\example.invalid\VT\Plant4\Maintenance & Manufacturing Engineering\EOAT Atlas"
    return [ordered]@{
        eoat_master_tracker = (Join-Path $networkRoot "02_Data\Workbooks\Master_Tracker\01_EOAT_Audit\EOAT_Audit_Database\EOAT_Master_Tracker.xlsx")
        press_capacity_workbook = (Join-Path $networkRoot "02_Data\Workbooks\Press_Capacity\00_Project_Admin\reference_data\press_capacity.xlsx")
        robot_workbook = (Join-Path $networkRoot "02_Data\Workbooks\Robot_EOAT\01_EOAT_Audit\EOAT_Audit_Database\Robot_Info.xlsx")
        photos_root = (Join-Path $networkRoot "03_Shared_Assets\EOAT_Photos\01_EOAT_Audit\Cell_Photos")
        output_folder = (Join-Path $networkRoot "04_Exports\PDF_Setup_Packets\06_Final_Handoff\Atlas_Exports")
        reference_docs_folder = (Join-Path $networkRoot "03_Shared_Assets\Documents")
    }
}

function Update-GlobalConfig {
    param(
        [Parameter(Mandatory = $true)][string]$GlobalConfigPath,
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)]$SourceSummary,
        [Parameter(Mandatory = $true)]$InstallState,
        [Parameter(Mandatory = $true)]$LauncherState,
        [Parameter(Mandatory = $true)]$Identity,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot
    )
    $existing = Read-JsonObject $GlobalConfigPath
    $payload = [ordered]@{}
    if ($existing) {
        foreach ($prop in $existing.PSObject.Properties) {
            $payload[$prop.Name] = $prop.Value
        }
    }
    $now = New-NowIso
    if (!$payload.Contains("created_at")) {
        $payload["created_at"] = $now
    }

    $networkRoot = "\\example.invalid\VT\Plant4\Maintenance & Manufacturing Engineering\EOAT Atlas"
    $sourcePaths = Get-DefaultSourcePaths
    $existingSourcePaths = Get-ConfigValue $existing "source_path_values" $null
    if ($null -eq $existingSourcePaths) {
        $existingSourcePaths = Get-ConfigValue $existing "source_paths" $null
    }
    if ($existingSourcePaths) {
        foreach ($prop in $existingSourcePaths.PSObject.Properties) {
            $text = [string]$prop.Value
            if (![string]::IsNullOrWhiteSpace($text)) {
                $sourcePaths[$prop.Name] = $text
            }
        }
    }

    $payload["config_schema_version"] = 1
    $payload["app_name"] = [string](Get-ConfigValue $Config "app_name" "EOAT Atlas")
    $payload["product_name"] = [string](Get-ConfigValue $Config "app_name" "EOAT Atlas")
    $payload["environment"] = [string](Get-ConfigValue $Config "environment" "production")
    $payload["network_project_root"] = $networkRoot
    $payload["network_root"] = $networkRoot
    $payload["source_paths"] = $sourcePaths
    $payload["source_path_values"] = $sourcePaths
    $payload["release_paths"] = [ordered]@{
        network_project_root = $networkRoot
        source_release_path = [string]$SourceSummary.source_release_path
        update_root = (Join-Path $networkRoot "06_Releases")
    }
    $payload["production_writes_enabled"] = $false
    $payload["write_mode"] = "disabled"
    $payload["deep_refresh_enabled"] = $true
    $payload["local_refresh_enabled"] = $true
    $payload["launcher_required"] = $false
    $payload["installed_app_path"] = [string]$InstallState.app_exe_path
    $payload["installed_launcher_path"] = [string]$LauncherState.launcher_exe_path
    $payload["runtime_root"] = $RuntimeRoot
    $payload["install_id"] = [string]$Identity.install_id
    $payload["app_instance_id"] = [string]$Identity.app_instance_id
    $payload["app_version"] = [string]$SourceSummary.app_version
    $payload["release_id"] = [string]$SourceSummary.release_id
    $payload["build_id"] = [string]$SourceSummary.build_id
    $payload["installer_version"] = [string](Get-ConfigValue $Config "installer_version" $script:InstallerScriptVersion)
    $payload["updated_at"] = $now

    Write-JsonObject $GlobalConfigPath $payload
    return $payload
}

function Get-ShortcutTarget {
    param(
        [Parameter(Mandatory = $true)]$InstallState,
        [Parameter(Mandatory = $true)]$LauncherState,
        [Parameter(Mandatory = $true)]$Config
    )
    $mode = [string](Get-ConfigValue $Config "shortcut_target_mode" "launcher_if_available_else_app")
    if ($mode -eq "launcher" -and [string]$LauncherState.status -ne "installed") {
        Stop-WithError "Shortcut mode requires launcher, but launcher is not installed."
    }
    if (($mode -eq "launcher" -or $mode -eq "launcher_if_available_else_app") -and [string]$LauncherState.status -eq "installed") {
        return [ordered]@{
            target = [string]$LauncherState.launcher_exe_path
            working_directory = [string]$LauncherState.launcher_install_path
            icon = [string]$LauncherState.launcher_exe_path
            target_kind = "launcher"
        }
    }
    return [ordered]@{
        target = [string]$InstallState.app_exe_path
        working_directory = [string]$InstallState.app_install_path
        icon = [string]$InstallState.app_exe_path
        target_kind = "app"
    }
}

function Get-DesktopDirectory {
    param([string]$Override = "")
    if (![string]::IsNullOrWhiteSpace($Override)) {
        return [System.IO.Path]::GetFullPath($Override)
    }
    $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    if ([string]::IsNullOrWhiteSpace($desktop)) {
        Stop-WithError "Current user Desktop folder could not be determined."
    }
    return [System.IO.Path]::GetFullPath($desktop)
}

function Assert-UserDesktopPath {
    param([Parameter(Mandatory = $true)][string]$DesktopDirectory)
    $commonDesktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::CommonDesktopDirectory)
    if (![string]::IsNullOrWhiteSpace($commonDesktop) -and (Test-PathIsUnder $DesktopDirectory $commonDesktop)) {
        Stop-WithError "All-users/Public Desktop shortcuts are not allowed: $DesktopDirectory"
    }
}

function Set-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)][string]$ShortcutPath,
        [Parameter(Mandatory = $true)]$ShortcutTarget
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ShortcutPath) | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = [string]$ShortcutTarget.target
    $shortcut.WorkingDirectory = [string]$ShortcutTarget.working_directory
    $shortcut.IconLocation = [string]$ShortcutTarget.icon
    $shortcut.Description = "EOAT Atlas"
    $shortcut.Save()
}

function Remove-SafeStaging {
    param(
        [string]$StagingRoot,
        [string]$StagingPath
    )
    if ([string]::IsNullOrWhiteSpace($StagingRoot) -or [string]::IsNullOrWhiteSpace($StagingPath)) {
        return
    }
    if ((Test-Path -LiteralPath $StagingPath) -and (Test-PathIsUnder $StagingPath $StagingRoot)) {
        Remove-Item -LiteralPath $StagingPath -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
        $ConfigPath = Join-Path $scriptDir "installer_config.json"
    } else {
        $ConfigPath = ConvertTo-FullPath $ConfigPath $scriptDir
    }
    if (!(Test-Path -LiteralPath $ConfigPath)) {
        Stop-WithError "Installer config was not found: $ConfigPath"
    }
    $configDir = Split-Path -Parent $ConfigPath
    $config = Read-JsonObject $ConfigPath
    if ($null -eq $config) {
        Stop-WithError "Installer config could not be parsed: $ConfigPath"
    }

    $requireAdmin = [bool](Get-ConfigValue $config "require_admin" $false)
    if ($requireAdmin) {
        Stop-WithError "Installer config requires admin, which is not allowed for EOAT Atlas."
    }
    if ((Test-IsElevated) -and !$AllowElevated) {
        Stop-WithError "Installer is running elevated. Stop and run as the shop-floor/current user, or pass -AllowElevated only for an explicit test."
    }

    $sourceConfigured = [string](Get-ConfigValue $config "source_release_path" "..\dist\EOAT Atlas")
    if (![string]::IsNullOrWhiteSpace($SourceReleasePath)) {
        $sourceConfigured = $SourceReleasePath
    }
    $resolvedSource = ConvertTo-FullPath $sourceConfigured $configDir

    $installConfigured = [string](Get-ConfigValue $config "install_root" "%LOCALAPPDATA%\EOAT_Atlas")
    if (![string]::IsNullOrWhiteSpace($InstallRoot)) {
        $installConfigured = $InstallRoot
    }
    $resolvedInstallRoot = ConvertTo-FullPath $installConfigured $configDir

    $runtimeConfigured = [string](Get-ConfigValue $config "runtime_root" "%LOCALAPPDATA%\EOAT_Atlas")
    if (![string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        $runtimeConfigured = $RuntimeRoot
    }
    $resolvedRuntimeRoot = ConvertTo-FullPath $runtimeConfigured $configDir

    $appVersionsConfigured = [string](Get-ConfigValue $config "app_versions_root" "")
    if ([string]::IsNullOrWhiteSpace($appVersionsConfigured) -or (![string]::IsNullOrWhiteSpace($InstallRoot))) {
        $resolvedAppVersionsRoot = Join-Path $resolvedInstallRoot "App"
    } else {
        $resolvedAppVersionsRoot = ConvertTo-FullPath $appVersionsConfigured $configDir
    }

    $launcherRootConfigured = [string](Get-ConfigValue $config "launcher_install_root" "")
    if ([string]::IsNullOrWhiteSpace($launcherRootConfigured) -or (![string]::IsNullOrWhiteSpace($InstallRoot))) {
        $resolvedLauncherRoot = Join-Path $resolvedInstallRoot "Launcher"
    } else {
        $resolvedLauncherRoot = ConvertTo-FullPath $launcherRootConfigured $configDir
    }

    Assert-PerUserLocalAppDataPath $resolvedInstallRoot "Install root"
    Assert-PerUserLocalAppDataPath $resolvedRuntimeRoot "Runtime root"
    Assert-PerUserLocalAppDataPath $resolvedAppVersionsRoot "App versions root"
    Assert-PerUserLocalAppDataPath $resolvedLauncherRoot "Launcher install root"

    $desktopDir = Get-DesktopDirectory $DesktopPath
    Assert-UserDesktopPath $desktopDir
    $shortcutName = [string](Get-ConfigValue $config "desktop_shortcut_name" "EOAT Atlas.lnk")
    $shortcutPath = Join-Path $desktopDir $shortcutName

    Write-InstallLog "EOAT Atlas installer version $([string](Get-ConfigValue $config "installer_version" $script:InstallerScriptVersion))"
    Write-InstallLog "Current user: $([Security.Principal.WindowsIdentity]::GetCurrent().Name)"
    Write-InstallLog "Machine name: $env:COMPUTERNAME"
    Write-InstallLog "Config path: $ConfigPath"
    Write-InstallLog "Source release path: $resolvedSource"
    Write-InstallLog "Install root: $resolvedInstallRoot"
    Write-InstallLog "Runtime root: $resolvedRuntimeRoot"
    Write-InstallLog "Desktop shortcut path: $shortcutPath"
    Write-InstallLog "No admin install: Program Files/HKLM/services/PATH/all-users shortcuts are not used."

    $sourceSummary = Test-SourceRelease $resolvedSource $config $configDir
    Write-InstallLog "Source validation passed: release_id=$($sourceSummary.release_id), app_version=$($sourceSummary.app_version), files=$($sourceSummary.file_count), bytes=$($sourceSummary.total_bytes), app_exe_sha256=$($sourceSummary.app_exe_sha256)"
    if (![string]::IsNullOrWhiteSpace([string]$sourceSummary.manifest.manifest_path)) {
        Write-InstallLog "Manifest status: path=$($sourceSummary.manifest.manifest_path), validated=$($sourceSummary.manifest.manifest_validated), files=$($sourceSummary.manifest.manifest_file_count)"
    } else {
        Write-InstallLog "No manifest file found. Simple source summary recorded with file count, total bytes, and app exe SHA-256."
    }

    if ($ValidateOnly) {
        Write-InstallLog "ValidateOnly requested. Source validation completed; no install state changed."
        exit 0
    }

    if ($DryRun) {
        $releaseSegment = ConvertTo-SafePathSegment ([string]$sourceSummary.release_id)
        $dryTarget = Join-Path $resolvedAppVersionsRoot $releaseSegment
        $dryInstallState = [ordered]@{
            app_install_path = $dryTarget
            app_exe_path = (Join-Path $dryTarget ([string](Get-ConfigValue $config "expected_app_exe_name" "EOAT Atlas.exe"))
            )
        }
        $dryLauncherState = [ordered]@{
            status = "not_installed"
            launcher_install_path = $resolvedLauncherRoot
            launcher_exe_path = ""
        }
        $dryShortcut = Get-ShortcutTarget $dryInstallState $dryLauncherState $config
        Ensure-RuntimeLayout $resolvedRuntimeRoot -WhatIfOnly
        Write-InstallLog "Dry run: would copy complete onedir release to $dryTarget using staging under $(Join-Path $resolvedAppVersionsRoot ".staging")"
        Write-InstallLog "Dry run: would create/update install identity at $(Join-Path $resolvedRuntimeRoot "install_identity.json")"
        Write-InstallLog "Dry run: would create/merge global config at $(Join-Path $resolvedRuntimeRoot "config\global_config.json")"
        Write-InstallLog "Dry run: would create/update desktop shortcut $shortcutPath -> $($dryShortcut.target)"
        Write-InstallLog "Dry run completed; no files were copied and no runtime state was changed."
        exit 0
    }

    Ensure-RuntimeLayout $resolvedRuntimeRoot
    $logPath = Join-Path (Join-Path $resolvedRuntimeRoot "logs") ("installer_{0}.log" -f (New-Timestamp))
    Start-InstallerLog $logPath
    Write-InstallLog "Installer log path: $logPath"

    $stagingPathForCleanup = ""
    $stagingRootForCleanup = Join-Path $resolvedAppVersionsRoot ".staging"
    try {
        $installState = Install-AppRelease $resolvedSource $resolvedAppVersionsRoot $sourceSummary $config
        $stagingPathForCleanup = [string]$installState.staging_path
        $launcherState = Install-LauncherIfAvailable $config $configDir $resolvedLauncherRoot

        $currentAppPath = Join-Path $resolvedRuntimeRoot "current_app.json"
        $currentLauncherPath = Join-Path $resolvedRuntimeRoot "current_launcher.json"
        $identityPath = Join-Path $resolvedRuntimeRoot "install_identity.json"
        $globalConfigPath = Join-Path $resolvedRuntimeRoot "config\global_config.json"

        $currentApp = [ordered]@{
            app_name = [string](Get-ConfigValue $config "app_name" "EOAT Atlas")
            app_version = [string]$sourceSummary.app_version
            release_id = [string]$sourceSummary.release_id
            build_id = [string]$sourceSummary.build_id
            app_install_path = [string]$installState.app_install_path
            app_exe_path = [string]$installState.app_exe_path
            metadata_path = [string]$installState.metadata_path
            source_release_path = [string]$sourceSummary.source_release_path
            installer_version = [string](Get-ConfigValue $config "installer_version" $script:InstallerScriptVersion)
            installed_at = New-NowIso
            manifest_summary = $sourceSummary.manifest
            file_count = $sourceSummary.file_count
            total_bytes = $sourceSummary.total_bytes
            app_exe_sha256 = $sourceSummary.app_exe_sha256
        }
        Write-JsonObject $currentAppPath $currentApp
        Write-JsonObject $currentLauncherPath $launcherState

        $identity = Update-InstallIdentity $identityPath $config $sourceSummary $installState $launcherState $resolvedInstallRoot $resolvedRuntimeRoot
        $globalConfig = Update-GlobalConfig $globalConfigPath $config $sourceSummary $installState $launcherState $identity $resolvedRuntimeRoot

        $shortcutConfigValue = [bool](Get-ConfigValue $config "create_desktop_shortcut" $true)
        if (!$shortcutConfigValue) {
            Write-InstallLog "Config create_desktop_shortcut is false, but EOAT Atlas installer policy requires the current-user Desktop shortcut. Creating it anyway." "WARN"
        }
        $shortcutTarget = Get-ShortcutTarget $installState $launcherState $config
        Set-DesktopShortcut $shortcutPath $shortcutTarget
        Write-InstallLog "Desktop shortcut updated: $shortcutPath -> $($shortcutTarget.target) [$($shortcutTarget.target_kind)]"

        $receiptPath = Join-Path $resolvedRuntimeRoot "install_receipt.json"
        $receipt = [ordered]@{
            receipt_schema_version = 1
            result = "success"
            installed_at = New-NowIso
            installer_version = [string](Get-ConfigValue $config "installer_version" $script:InstallerScriptVersion)
            installer_config_path = $ConfigPath
            source_release_path = [string]$sourceSummary.source_release_path
            install_root = $resolvedInstallRoot
            runtime_root = $resolvedRuntimeRoot
            app = $currentApp
            launcher = $launcherState
            shortcut = [ordered]@{
                shortcut_path = $shortcutPath
                target = [string]$shortcutTarget.target
                working_directory = [string]$shortcutTarget.working_directory
                target_kind = [string]$shortcutTarget.target_kind
            }
            identity_path = $identityPath
            config_path = $globalConfigPath
            production_writes_enabled = $false
            sentinelone_note = "Application launch was not attempted by the installer. Endpoint-security launch blocks should be reported separately for IT allowlisting."
            log_path = $logPath
        }
        Write-JsonObject $receiptPath $receipt
        Write-InstallLog "Install identity updated: $identityPath"
        Write-InstallLog "Global config merged: $globalConfigPath"
        Write-InstallLog "Install receipt written: $receiptPath"
        Write-InstallLog "Launcher status: $($launcherState.status)"
        Write-InstallLog "Production workbook writes remain disabled."
        Write-InstallLog "EOAT Atlas per-user install completed successfully."
        exit 0
    } catch {
        Remove-SafeStaging $stagingRootForCleanup $stagingPathForCleanup
        Write-InstallLog "Install failed. Existing runtime data was not deleted. Error: $($_.Exception.Message)" "ERROR"
        exit 1
    }
} catch {
    Write-InstallLog "Installer failed: $($_.Exception.Message)" "ERROR"
    exit 1
}
