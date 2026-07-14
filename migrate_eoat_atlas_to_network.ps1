<#
.SYNOPSIS
Safely copy and reorganize the EOAT Standardization project into the EOAT Atlas network-drive layout.

.DESCRIPTION
This script is designed for a company network drive migration. It never deletes or moves the
source project. It copies files into a clean destination structure, writes inventory/manifests,
handles collisions without overwriting by default, and verifies copied files after a real run.

The default dry-run behavior does not create the destination structure and does not copy files.
Dry-run reports are written next to this script under Migration_Dry_Run_Logs unless -LogRoot is
provided.

.EXAMPLE
.\migrate_eoat_atlas_to_network.ps1 -DryRun

.EXAMPLE
.\migrate_eoat_atlas_to_network.ps1

.EXAMPLE
.\migrate_eoat_atlas_to_network.ps1 -VerifyOnly
#>

[CmdletBinding()]
param(
    [string]$SourceRoot = '\\gwplastics.com\VT\Users\kgray\My Documents\KG_Nolato_Summer_2026\EOAT_Standardization_Project',
    [string]$DestinationRoot = '\\gwplastics.com\VT\Plant4\Maintenance & Manufacturing Engineering\EOAT Atlas',
    [switch]$DryRun,
    [switch]$VerifyOnly,
    [switch]$IncludeAppSource,
    [switch]$IncludeLegacyArchive,
    [switch]$Force,
    [string]$LogRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Script:StartedAt = Get-Date
$Script:RunStamp = $Script:StartedAt.ToString('yyyyMMdd_HHmmss')
$Script:ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).ProviderPath }
$Script:MigrationConfig = $null
$Script:Errors = New-Object 'System.Collections.Generic.List[object]'
$Script:Collisions = New-Object 'System.Collections.Generic.List[object]'
$Script:GeneratedFiles = New-Object 'System.Collections.Generic.List[object]'

function Join-PathMany {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Children
    )

    $path = $Root
    foreach ($child in $Children) {
        if (-not [string]::IsNullOrWhiteSpace($child)) {
            $path = Join-Path -Path $path -ChildPath $child
        }
    }
    return $path
}

function Get-DefaultMigrationConfig {
    return [pscustomobject]@{
        default_source_root = '\\gwplastics.com\VT\Users\kgray\My Documents\KG_Nolato_Summer_2026\EOAT_Standardization_Project'
        default_destination_root = '\\gwplastics.com\VT\Plant4\Maintenance & Manufacturing Engineering\EOAT Atlas'
        include_app_source_by_default = $true
        hash_large_files = $false
        max_hash_file_mb = 512
        excluded_directory_names = @(
            '__pycache__',
            '.pytest_cache',
            '.mypy_cache',
            '.ruff_cache',
            '.venv',
            'venv',
            'env',
            'node_modules',
            'dist',
            'build',
            '.cache',
            'tmp',
            'temp',
            '.git'
        )
        folder_structure = @(
            '00_Admin',
            '00_Admin\README',
            '00_Admin\Migration_Logs',
            '00_Admin\Manifests',
            '00_Admin\Config',
            '00_Admin\Change_Notes',
            '01_App',
            '01_App\Installer',
            '01_App\Launcher',
            '01_App\Releases',
            '01_App\Releases\EOAT_Atlas_0.1.0',
            '01_App\Source_Current',
            '01_App\Build_Artifacts',
            '02_Data',
            '02_Data\Workbooks',
            '02_Data\Workbooks\Master_Tracker',
            '02_Data\Workbooks\Press_Capacity',
            '02_Data\Workbooks\Robot_EOAT',
            '02_Data\Workbooks\Legacy_Imports',
            '02_Data\Database',
            '02_Data\Database\Future_SQLite',
            '02_Data\Database\Local_Cache_Notes',
            '02_Data\Event_Log',
            '02_Data\Event_Log\Global_Events',
            '02_Data\Event_Log\Pending_Updates',
            '02_Data\Event_Log\Processed_Updates',
            '02_Data\Event_Log\Failed_Updates',
            '02_Data\Locks',
            '02_Data\Snapshots',
            '02_Data\Validation_Reports',
            '03_Shared_Assets',
            '03_Shared_Assets\EOAT_Photos',
            '03_Shared_Assets\EOAT_Photos\Needs_Review',
            '03_Shared_Assets\Tool_Photos',
            '03_Shared_Assets\Machine_Photos',
            '03_Shared_Assets\Documents',
            '03_Shared_Assets\Setup_Packet_Templates',
            '03_Shared_Assets\Generated_Setup_Packets',
            '03_Shared_Assets\Icons_And_UI_Assets',
            '04_Exports',
            '04_Exports\Excel_ReadOnly',
            '04_Exports\PDF_Setup_Packets',
            '04_Exports\Reports',
            '04_Exports\Reports\Imported_Reports',
            '04_Exports\Dashboard_Exports',
            '05_Backups',
            '05_Backups\Pre_Migration_Backup_Manifest',
            '05_Backups\Workbook_Snapshots',
            '05_Backups\App_Release_Backups',
            '06_Logs',
            '06_Logs\App_Logs',
            '06_Logs\App_Logs\Imported_Logs',
            '06_Logs\Sync_Logs',
            '06_Logs\Install_Logs',
            '06_Logs\Error_Reports',
            '07_Documentation',
            '07_Documentation\Project_Plans',
            '07_Documentation\EOAT_Standards',
            '07_Documentation\PM_Checklists',
            '07_Documentation\Training_Materials',
            '07_Documentation\User_Guides',
            '07_Documentation\Developer_Notes',
            '99_Legacy_Archive',
            '99_Legacy_Archive\Original_Folder_Structure',
            '99_Legacy_Archive\Needs_Review'
        )
    }
}

function Import-MigrationConfig {
    $config = Get-DefaultMigrationConfig
    $configPath = Join-Path -Path $Script:ScriptRoot -ChildPath 'migration_config.json'

    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        try {
            $fileConfig = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
            foreach ($property in $fileConfig.PSObject.Properties) {
                $config | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value -Force
            }
            Write-Host "Loaded migration config: $configPath" -ForegroundColor DarkGray
        }
        catch {
            Write-Warning "Could not read migration_config.json. Built-in defaults will be used. $($_.Exception.Message)"
        }
    }

    return $config
}

function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$DefaultValue
    )

    if ($null -ne $Script:MigrationConfig) {
        $property = $Script:MigrationConfig.PSObject.Properties[$Name]
        if ($null -ne $property -and $null -ne $property.Value) {
            return $property.Value
        }
    }
    return $DefaultValue
}

function Add-MigrationError {
    param(
        [string]$Stage,
        [string]$Path,
        [string]$Message,
        [string]$ExceptionType = ''
    )

    $Script:Errors.Add([pscustomobject]@{
        timestamp = (Get-Date).ToString('o')
        stage = $Stage
        path = $Path
        message = $Message
        exception_type = $ExceptionType
    }) | Out-Null
}

function ConvertTo-LongPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Path.StartsWith('\\?\', [System.StringComparison]::OrdinalIgnoreCase)) {
        return $Path
    }

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath.StartsWith('\\')) {
        return '\\?\UNC\' + $fullPath.TrimStart([char[]]@('\'))
    }

    return '\\?\' + $fullPath
}

function Test-PathExistsSafe {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [ValidateSet('Any', 'Leaf', 'Container')][string]$PathType = 'Any'
    )

    try {
        if ($PathType -eq 'Leaf') {
            if (Test-Path -LiteralPath $Path -PathType Leaf) {
                return $true
            }
        }
        elseif ($PathType -eq 'Container') {
            if (Test-Path -LiteralPath $Path -PathType Container) {
                return $true
            }
        }
        elseif (Test-Path -LiteralPath $Path) {
            return $true
        }
    }
    catch {
        # Fall back to .NET long-path checks below.
    }

    $longPath = ConvertTo-LongPath -Path $Path
    if ($PathType -eq 'Leaf') {
        return [System.IO.File]::Exists($longPath)
    }
    if ($PathType -eq 'Container') {
        return [System.IO.Directory]::Exists($longPath)
    }

    return ([System.IO.File]::Exists($longPath) -or [System.IO.Directory]::Exists($longPath))
}

function Get-FileInfoSafe {
    param([Parameter(Mandatory = $true)][string]$Path)

    try {
        return Get-Item -LiteralPath $Path -ErrorAction Stop
    }
    catch {
        return New-Object System.IO.FileInfo (ConvertTo-LongPath -Path $Path)
    }
}

function Ensure-Directory {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    if (-not (Test-PathExistsSafe -Path $Path -PathType Container)) {
        [System.IO.Directory]::CreateDirectory((ConvertTo-LongPath -Path $Path)) | Out-Null
    }
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$ChildPath
    )

    $trimChars = [char[]]@('\', '/')
    $baseFull = [System.IO.Path]::GetFullPath($BasePath).TrimEnd($trimChars)
    $childFull = [System.IO.Path]::GetFullPath($ChildPath)

    if ($childFull.StartsWith($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $childFull.Substring($baseFull.Length).TrimStart($trimChars)
    }

    return Split-Path -Path $ChildPath -Leaf
}

function Get-RelativeDirectory {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $relativeDirectory = Split-Path -Path $RelativePath -Parent
    if ([string]::IsNullOrWhiteSpace($relativeDirectory) -or $relativeDirectory -eq '.') {
        return ''
    }
    return $relativeDirectory
}

function Join-CategoryPath {
    param(
        [Parameter(Mandatory = $true)][string]$CategoryRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    $fileName = Split-Path -Path $RelativePath -Leaf
    $relativeDirectory = Get-RelativeDirectory -RelativePath $RelativePath
    if ([string]::IsNullOrWhiteSpace($relativeDirectory)) {
        return Join-Path -Path $CategoryRoot -ChildPath $fileName
    }

    return Join-PathMany -Root $CategoryRoot -Children @($relativeDirectory, $fileName)
}

function Test-TextAny {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string[]]$Patterns
    )

    foreach ($pattern in $Patterns) {
        if ($Text -match $pattern) {
            return $true
        }
    }
    return $false
}

function Get-ExcludedDirectoryName {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $excludedNames = @((Get-ConfigValue -Name 'excluded_directory_names' -DefaultValue @()))
    $lookup = @{}
    foreach ($name in $excludedNames) {
        if (-not [string]::IsNullOrWhiteSpace([string]$name)) {
            $lookup[([string]$name).ToLowerInvariant()] = $true
        }
    }

    $parts = $RelativePath -split '[\\/]+'
    foreach ($part in $parts) {
        $key = ([string]$part).ToLowerInvariant()
        if ($lookup.ContainsKey($key)) {
            return $part
        }
    }
    return $null
}

function Test-ShouldExcludeFile {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $fileName = Split-Path -Path $RelativePath -Leaf
    $lowerFileName = $fileName.ToLowerInvariant()
    $extension = [System.IO.Path]::GetExtension($fileName).ToLowerInvariant()

    if (@('thumbs.db', 'desktop.ini', '.ds_store') -contains $lowerFileName) {
        return [pscustomobject]@{
            should_exclude = $true
            category = 'Excluded_System_File'
            skip_status = 'skipped_system_file'
            reason = 'excluded_system_file'
        }
    }

    if ($fileName -like '~$*' -or @('.tmp', '.temp', '.lock') -contains $extension) {
        return [pscustomobject]@{
            should_exclude = $true
            category = 'Excluded_System_File'
            skip_status = 'skipped_system_file'
            reason = 'excluded_system_file'
        }
    }

    $excludedDirectory = Get-ExcludedDirectoryName -RelativePath $RelativePath
    if ($null -ne $excludedDirectory) {
        return [pscustomobject]@{
            should_exclude = $true
            category = 'Excluded_Directory'
            skip_status = 'skipped_excluded_directory'
            reason = "Excluded directory '$excludedDirectory'. Use -IncludeLegacyArchive only for reviewed legacy preservation; system/cache files remain excluded."
        }
    }

    return [pscustomobject]@{
        should_exclude = $false
        category = ''
        skip_status = ''
        reason = ''
    }
}

function Test-IsBackupOrLegacyPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $normalized = '\' + (($RelativePath -replace '/', '\').ToLowerInvariant()) + '\'
    $patterns = @(
        '\backups\',
        '\backup\',
        '_backup',
        '_backups',
        'migration_backups',
        'pre_migration',
        '\old\',
        '\archive\'
    )

    foreach ($pattern in $patterns) {
        if ($normalized -match [regex]::Escape($pattern)) {
            return $true
        }
    }

    return $false
}

function Test-AppSourceLike {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Extension
    )

    $text = $RelativePath.ToLowerInvariant()
    $fileName = (Split-Path -Path $RelativePath -Leaf).ToLowerInvariant()
    $sourceExtensions = @('.py', '.pyw', '.ui', '.qrc')
    $sourceFileNames = @(
        'requirements.txt',
        'requirements-dev.txt',
        'pyproject.toml',
        'setup.py',
        'setup.cfg',
        'pytest.ini',
        'tox.ini'
    )

    if ($sourceExtensions -contains $Extension) {
        return $true
    }
    if ($sourceFileNames -contains $fileName) {
        return $true
    }
    if ($fileName -like 'readme*' -and (Test-TextAny -Text $text -Patterns @('(^|[\\/])app([\\/]|$)', 'source', 'build', 'install', 'launcher', 'run_', 'dashboard', 'atlas'))) {
        return $true
    }
    if ($Extension -eq '.json' -and (Test-TextAny -Text $text -Patterns @('(^|[\\/])config([\\/]|$)', 'settings', 'manifest', 'release', 'launcher', 'installer', 'atlas'))) {
        return $true
    }
    if (@('.ico', '.svg', '.css', '.html', '.htm') -contains $Extension) {
        if (Test-TextAny -Text $text -Patterns @('(^|[\\/])app([\\/]|$)', '(^|[\\/])assets([\\/]|$)', 'resources', 'icons', 'ui')) {
            return $true
        }
    }

    return $false
}

function Test-SetupPacketLike {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $text = $RelativePath.ToLowerInvariant()
    return (Test-TextAny -Text $text -Patterns @('setup[-_ ]?packet', 'packet[-_ ]?builder', 'generated[-_ ]?packet', 'fit[-_ ]?check'))
}

function Get-ProposedDestination {
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Extension,
        [Parameter(Mandatory = $true)][string]$DestinationRoot,
        [Parameter(Mandatory = $true)][bool]$IncludeAppSourceForRun
    )

    $text = $RelativePath.ToLowerInvariant()
    $fileName = (Split-Path -Path $RelativePath -Leaf).ToLowerInvariant()
    $exclusion = Test-ShouldExcludeFile -RelativePath $RelativePath

    if ($exclusion.should_exclude) {
        return [pscustomobject]@{
            destination_path = ''
            category = $exclusion.category
            action = 'skip'
            reason = $exclusion.reason
            skip_status = $exclusion.skip_status
        }
    }

    $workbookExtensions = @('.xlsx', '.xlsm', '.xls')
    $imageExtensions = @('.jpg', '.jpeg', '.png', '.heic', '.bmp', '.tif', '.tiff', '.webp')
    $documentExtensions = @('.docx', '.doc', '.pdf', '.txt', '.md', '.rtf')

    if (Test-IsBackupOrLegacyPath -RelativePath $RelativePath) {
        $legacyRoot = Join-PathMany -Root $DestinationRoot -Children @('99_Legacy_Archive', 'Needs_Review')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $legacyRoot -RelativePath $RelativePath
            category = 'Backup_Or_Legacy_Needs_Review'
            action = 'copy_mapped'
            reason = 'backup_or_legacy_routed_to_needs_review'
            skip_status = ''
        }
    }

    # Setup packet rules come early because setup-packet PDFs/images should not be treated as generic docs/photos.
    if (Test-SetupPacketLike -RelativePath $RelativePath) {
        if (Test-TextAny -Text $text -Patterns @('template', 'blank', 'form')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'Setup_Packet_Templates')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Setup_Packet_Template'
            action = 'copy_mapped'
            reason = 'Setup packet template keyword match.'
            skip_status = ''
        }
        }

        if ($Extension -eq '.pdf' -or (Test-TextAny -Text $text -Patterns @('generated', 'output', 'export', 'fit[-_ ]?check'))) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('04_Exports', 'PDF_Setup_Packets')
            return [pscustomobject]@{
                destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
                category = 'PDF_Setup_Packet'
                action = 'copy_mapped'
                reason = 'Generated setup packet or fit-check output keyword match.'
                skip_status = ''
            }
        }

        $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'Generated_Setup_Packets')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Generated_Setup_Packet_Source'
            action = 'copy_mapped'
            reason = 'Setup packet material keyword match.'
            skip_status = ''
        }
    }

    # Backups and snapshots are kept separate from current working data where practical.
    if (($workbookExtensions -contains $Extension) -and (Test-TextAny -Text $text -Patterns @('backup', 'snapshot'))) {
        $root = Join-PathMany -Root $DestinationRoot -Children @('05_Backups', 'Workbook_Snapshots')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Workbook_Snapshot'
            action = 'copy_mapped'
            reason = 'Workbook backup or snapshot keyword match.'
            skip_status = ''
        }
    }

    if ($workbookExtensions -contains $Extension) {
        if (Test-TextAny -Text $text -Patterns @('master[-_ ]?tracker', 'main[-_ ]?tracker', 'eoat[-_ ]?tracker')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('02_Data', 'Workbooks', 'Master_Tracker')
            $category = 'Workbook_Master_Tracker'
            $reason = 'Master tracker keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('press[-_ ]?capacity', 'capacity')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('02_Data', 'Workbooks', 'Press_Capacity')
            $category = 'Workbook_Press_Capacity'
            $reason = 'Press capacity keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('robot', 'eoat[-_ ]?robot')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('02_Data', 'Workbooks', 'Robot_EOAT')
            $category = 'Workbook_Robot_EOAT'
            $reason = 'Robot EOAT workbook keyword match.'
        }
        else {
            $root = Join-PathMany -Root $DestinationRoot -Children @('02_Data', 'Workbooks', 'Legacy_Imports')
            $category = 'Workbook_Legacy_Import'
            $reason = 'Workbook did not match a more specific workbook category.'
        }

        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = $category
            action = 'copy_mapped'
            reason = $reason
            skip_status = ''
        }
    }

    if (Test-TextAny -Text $text -Patterns @('(^|[\\/])logs?([\\/]|$)', '\.log$', 'error[-_ ]?report')) {
        $root = Join-PathMany -Root $DestinationRoot -Children @('06_Logs', 'App_Logs', 'Imported_Logs')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Imported_App_Log'
            action = 'copy_mapped'
            reason = 'Log or error-report keyword match.'
            skip_status = ''
        }
    }

    if (Test-TextAny -Text $text -Patterns @('validation[-_ ]?report', 'validation[-_ ]?findings')) {
        $root = Join-PathMany -Root $DestinationRoot -Children @('02_Data', 'Validation_Reports')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Validation_Report'
            action = 'copy_mapped'
            reason = 'Validation report keyword match.'
            skip_status = ''
        }
    }

    if (Test-TextAny -Text $text -Patterns @('(^|[\\/])reports?([\\/]|$)', 'dashboard[-_ ]?export', 'export', 'summary')) {
        $root = Join-PathMany -Root $DestinationRoot -Children @('04_Exports', 'Reports', 'Imported_Reports')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Imported_Report'
            action = 'copy_mapped'
            reason = 'Report/export keyword match.'
            skip_status = ''
        }
    }

    if (Test-AppSourceLike -RelativePath $RelativePath -Extension $Extension) {
        if (-not $IncludeAppSourceForRun) {
            return [pscustomobject]@{
                destination_path = ''
                category = 'App_Source'
                action = 'skip'
                reason = 'App source was detected but IncludeAppSource is disabled.'
                skip_status = 'skipped_app_source_disabled'
            }
        }

        $root = Join-PathMany -Root $DestinationRoot -Children @('01_App', 'Source_Current')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'App_Source_Current'
            action = 'copy_mapped'
            reason = 'App source or app configuration file match.'
            skip_status = ''
        }
    }

    if (($imageExtensions -contains $Extension) -and (Test-TextAny -Text $text -Patterns @('icon', 'logo', 'ui[-_ ]?asset', 'sprite'))) {
        $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'Icons_And_UI_Assets')
        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = 'Icon_Or_UI_Asset'
            action = 'copy_mapped'
            reason = 'Icon or UI asset keyword match.'
            skip_status = ''
        }
    }

    if ($imageExtensions -contains $Extension) {
        if (Test-TextAny -Text $text -Patterns @('eoat', 'end[-_ ]?of[-_ ]?arm', 'gripper', 'vacuum', 'cup')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'EOAT_Photos')
            $category = 'EOAT_Photo'
            $reason = 'EOAT photo keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('tool', 'mold', 'part[-_ ]?number', 'part[-_ ]?no', 'pn[-_ ]?\d+')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'Tool_Photos')
            $category = 'Tool_Photo'
            $reason = 'Tool or mold photo keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('machine', 'press', 'robot')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'Machine_Photos')
            $category = 'Machine_Photo'
            $reason = 'Machine, press, or robot photo keyword match.'
        }
        else {
            $root = Join-PathMany -Root $DestinationRoot -Children @('03_Shared_Assets', 'EOAT_Photos', 'Needs_Review')
            $category = 'Photo_Needs_Review'
            $reason = 'Image file did not match a more specific photo category.'
        }

        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = $category
            action = 'copy_mapped'
            reason = $reason
            skip_status = ''
        }
    }

    if ($documentExtensions -contains $Extension) {
        if (Test-TextAny -Text $text -Patterns @('project[-_ ]?plan', 'charter', 'implementation', 'timeline', 'roadmap')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation', 'Project_Plans')
            $category = 'Documentation_Project_Plans'
            $reason = 'Project plan keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('standard', 'guideline', 'design[-_ ]?guideline')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation', 'EOAT_Standards')
            $category = 'Documentation_EOAT_Standards'
            $reason = 'Standard or guideline keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('preventive[-_ ]?maintenance', '(^|[\\/])pm([\\/]|[_ -])', 'checklist')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation', 'PM_Checklists')
            $category = 'Documentation_PM_Checklists'
            $reason = 'Preventive maintenance or checklist keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('training', 'work[-_ ]?instruction')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation', 'Training_Materials')
            $category = 'Documentation_Training_Materials'
            $reason = 'Training or work-instruction keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('user[-_ ]?guide', 'usage', 'manual')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation', 'User_Guides')
            $category = 'Documentation_User_Guides'
            $reason = 'User-guide keyword match.'
        }
        elseif (Test-TextAny -Text $text -Patterns @('developer', 'architecture', 'globalization', 'install', 'sync', 'sqlite', 'database', 'event[-_ ]?log')) {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation', 'Developer_Notes')
            $category = 'Documentation_Developer_Notes'
            $reason = 'Developer, architecture, install, sync, or database keyword match.'
        }
        else {
            $root = Join-PathMany -Root $DestinationRoot -Children @('07_Documentation')
            $category = 'Documentation_General'
            $reason = 'Document extension did not match a more specific documentation category.'
        }

        return [pscustomobject]@{
            destination_path = Join-CategoryPath -CategoryRoot $root -RelativePath $RelativePath
            category = $category
            action = 'copy_mapped'
            reason = $reason
            skip_status = ''
        }
    }

    $legacyRoot = Join-PathMany -Root $DestinationRoot -Children @('99_Legacy_Archive', 'Needs_Review')
    return [pscustomobject]@{
        destination_path = Join-CategoryPath -CategoryRoot $legacyRoot -RelativePath $RelativePath
        category = 'Legacy_Needs_Review'
        action = 'copy_mapped'
        reason = 'No mapping rule matched; preserving file under Needs_Review.'
        skip_status = ''
    }
}

function Get-FileHashSafe {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$FileInfo,
        [bool]$AlwaysHash = $false
    )

    $hashLargeFiles = [bool](Get-ConfigValue -Name 'hash_large_files' -DefaultValue $false)
    $maxHashMb = [double](Get-ConfigValue -Name 'max_hash_file_mb' -DefaultValue 512)
    $maxHashBytes = [int64]($maxHashMb * 1MB)

    if (-not $AlwaysHash -and -not $hashLargeFiles -and $FileInfo.Length -gt $maxHashBytes) {
        return [pscustomobject]@{
            hash = ''
            status = "skipped_large_file_over_${maxHashMb}_mb"
        }
    }

    try {
        $hash = Get-FileHash -LiteralPath $FileInfo.FullName -Algorithm SHA256 -ErrorAction Stop
        return [pscustomobject]@{
            hash = $hash.Hash
            status = 'hashed'
        }
    }
    catch {
        try {
            $sha = [System.Security.Cryptography.SHA256]::Create()
            $stream = [System.IO.File]::OpenRead((ConvertTo-LongPath -Path $FileInfo.FullName))
            try {
                $hashText = ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '')
            }
            finally {
                $stream.Dispose()
                $sha.Dispose()
            }

            return [pscustomobject]@{
                hash = $hashText
                status = 'hashed_long_path_fallback'
            }
        }
        catch {
            Add-MigrationError -Stage 'hash_file' -Path $FileInfo.FullName -Message $_.Exception.Message -ExceptionType $_.Exception.GetType().FullName
            return [pscustomobject]@{
                hash = ''
                status = 'hash_failed'
            }
        }
    }
}

function Test-SourceAndDestination {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$IsDryRun,
        [Parameter(Mandatory = $true)][bool]$IsVerifyOnly
    )

    if ($IsVerifyOnly) {
        if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
            throw "DestinationRoot does not exist for verification: $Destination"
        }
        return
    }

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "SourceRoot does not exist: $Source"
    }

    if (Test-Path -LiteralPath $Destination -PathType Container) {
        Write-Host "Destination is reachable: $Destination" -ForegroundColor Green
        return
    }

    if ($IsDryRun) {
        $parent = Split-Path -Path $Destination -Parent
        while (-not [string]::IsNullOrWhiteSpace($parent) -and -not (Test-Path -LiteralPath $parent -PathType Container)) {
            $parent = Split-Path -Path $parent -Parent
        }

        if ([string]::IsNullOrWhiteSpace($parent)) {
            Write-Warning "Dry run cannot confirm a reachable destination parent for: $Destination"
        }
        else {
            Write-Host "Dry run found reachable destination parent: $parent" -ForegroundColor Yellow
        }
        return
    }

    Write-Host "Creating destination root: $Destination" -ForegroundColor Yellow
    Ensure-Directory -Path $Destination
}

function New-MigrationLogFolder {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$IsDryRun,
        [string]$RequestedLogRoot
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedLogRoot)) {
        $root = $RequestedLogRoot
    }
    elseif ($IsDryRun) {
        $root = Join-Path -Path $Script:ScriptRoot -ChildPath 'Migration_Dry_Run_Logs'
    }
    else {
        $root = Join-PathMany -Root $Destination -Children @('00_Admin', 'Migration_Logs')
    }

    Ensure-Directory -Path $root
    $logFolder = Join-Path -Path $root -ChildPath "Migration_$Script:RunStamp"
    Ensure-Directory -Path $logFolder
    return $logFolder
}

function New-EoatAtlasFolderStructure {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$IsDryRun
    )

    $folders = @((Get-ConfigValue -Name 'folder_structure' -DefaultValue @()))
    $planned = New-Object 'System.Collections.Generic.List[object]'
    $index = 0

    foreach ($relativeFolder in $folders) {
        $index++
        $path = Join-Path -Path $Destination -ChildPath ([string]$relativeFolder)
        $planned.Add([pscustomobject]@{
            folder_number = $index
            relative_path = [string]$relativeFolder
            full_path = $path
            action = if ($IsDryRun) { 'would_create_or_confirm' } else { 'created_or_confirmed' }
        }) | Out-Null

        if (-not $IsDryRun) {
            Ensure-Directory -Path $path
        }
    }

    return $planned.ToArray()
}

function Get-SourceInventory {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$IncludeAppSourceForRun
    )

    Write-Host "Building source inventory..." -ForegroundColor Cyan
    $enumerationErrors = @()
    $files = @(Get-ChildItem -LiteralPath $Source -File -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable +enumerationErrors)

    foreach ($enumerationError in $enumerationErrors) {
        Add-MigrationError -Stage 'enumerate_source' -Path $Source -Message $enumerationError.Exception.Message -ExceptionType $enumerationError.Exception.GetType().FullName
    }

    $inventory = New-Object 'System.Collections.Generic.List[object]'
    $total = $files.Count
    $i = 0

    foreach ($file in $files) {
        $i++
        if ($total -gt 0) {
            Write-Progress -Activity 'Inventory and hash source files' -Status "$i of $total" -PercentComplete (($i / $total) * 100)
        }

        $relativePath = Get-RelativePath -BasePath $Source -ChildPath $file.FullName
        $extension = if ($file.Extension) { $file.Extension.ToLowerInvariant() } else { '' }
        $proposal = Get-ProposedDestination -RelativePath $relativePath -Extension $extension -DestinationRoot $Destination -IncludeAppSourceForRun $IncludeAppSourceForRun
        if ($proposal.action -eq 'skip') {
            $hashInfo = [pscustomobject]@{
                hash = ''
                status = 'not_hashed_skipped_file'
            }
        }
        else {
            $hashInfo = Get-FileHashSafe -FileInfo $file
        }

        $inventory.Add([pscustomobject]@{
            full_source_path = $file.FullName
            relative_path = $relativePath
            file_name = $file.Name
            extension = $extension
            size_bytes = [int64]$file.Length
            last_modified = $file.LastWriteTime.ToString('o')
            sha256 = $hashInfo.hash
            hash_status = $hashInfo.status
            proposed_destination_path = $proposal.destination_path
            proposed_category = $proposal.category
            proposed_action = $proposal.action
            proposed_reason = $proposal.reason
            proposed_skip_status = $proposal.skip_status
        }) | Out-Null
    }

    Write-Progress -Activity 'Inventory and hash source files' -Completed
    return $inventory.ToArray()
}

function Resolve-DestinationCollision {
    param(
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$Stamp
    )

    $directory = Split-Path -Path $DestinationPath -Parent
    $leaf = Split-Path -Path $DestinationPath -Leaf
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($leaf)
    $extension = [System.IO.Path]::GetExtension($leaf)
    $candidate = Join-Path -Path $directory -ChildPath ("{0}_DUPLICATE_{1}{2}" -f $baseName, $Stamp, $extension)
    $counter = 1

    while (Test-Path -LiteralPath $candidate) {
        $candidate = Join-Path -Path $directory -ChildPath ("{0}_DUPLICATE_{1}_{2:000}{3}" -f $baseName, $Stamp, $counter, $extension)
        $counter++
    }

    return $candidate
}

function Copy-FileSafely {
    param(
        [Parameter(Mandatory = $true)]$InventoryItem,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [Parameter(Mandatory = $true)][string]$Category,
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][bool]$IsDryRun,
        [Parameter(Mandatory = $true)][bool]$UseForce
    )

    $sourcePath = [string]$InventoryItem.full_source_path
    $requestedDestination = $DestinationPath
    $finalDestination = $DestinationPath
    $collisionAction = 'none'
    $status = 'copied'
    $reason = 'Copied successfully.'
    $destinationSha256 = ''

    try {
        if (Test-PathExistsSafe -Path $requestedDestination -PathType Leaf) {
            if ($UseForce) {
                $collisionAction = 'force_overwrite'
                $status = 'overwritten'
                $reason = 'Destination existed and -Force was supplied.'
            }
            else {
                $sameContent = $false
                if (-not [string]::IsNullOrWhiteSpace([string]$InventoryItem.sha256)) {
                    $destinationItem = Get-FileInfoSafe -Path $requestedDestination
                    if ([int64]$destinationItem.Length -eq [int64]$InventoryItem.size_bytes) {
                        $destinationHashInfo = Get-FileHashSafe -FileInfo $destinationItem -AlwaysHash $true
                        $destinationSha256 = $destinationHashInfo.hash
                        if ($destinationSha256 -eq [string]$InventoryItem.sha256) {
                            $sameContent = $true
                        }
                    }
                }

                if ($sameContent) {
                    return [pscustomobject]@{
                        timestamp = (Get-Date).ToString('o')
                        operation = $Operation
                        source_path = $sourcePath
                        relative_path = $InventoryItem.relative_path
                        requested_destination_path = $requestedDestination
                        destination_path = $requestedDestination
                        category = $Category
                        status = 'skipped_already_exists_same'
                        reason = 'Destination file already exists with matching size and SHA256 hash.'
                        size_bytes = [int64]$InventoryItem.size_bytes
                        source_sha256 = $InventoryItem.sha256
                        destination_sha256 = $destinationSha256
                        collision_action = 'skip_same_content'
                        error_message = ''
                    }
                }

                $finalDestination = Resolve-DestinationCollision -DestinationPath $requestedDestination -Stamp $Script:RunStamp
                $collisionAction = 'duplicate_filename'
                $status = 'copied_duplicate'
                $reason = 'Destination existed with different or unverified content; copied to collision-safe duplicate filename.'
                $Script:Collisions.Add([pscustomobject]@{
                    timestamp = (Get-Date).ToString('o')
                    source_path = $sourcePath
                    requested_destination_path = $requestedDestination
                    resolved_destination_path = $finalDestination
                    category = $Category
                    operation = $Operation
                    action = $collisionAction
                }) | Out-Null
            }
        }

        if ($IsDryRun) {
            $dryStatus = switch ($status) {
                'overwritten' { 'dry_run_would_overwrite' }
                'copied_duplicate' { 'dry_run_would_copy_duplicate' }
                default { 'dry_run_would_copy' }
            }

            return [pscustomobject]@{
                timestamp = (Get-Date).ToString('o')
                operation = $Operation
                source_path = $sourcePath
                relative_path = $InventoryItem.relative_path
                requested_destination_path = $requestedDestination
                destination_path = $finalDestination
                category = $Category
                status = $dryStatus
                reason = $reason
                size_bytes = [int64]$InventoryItem.size_bytes
                source_sha256 = $InventoryItem.sha256
                destination_sha256 = $destinationSha256
                collision_action = $collisionAction
                error_message = ''
            }
        }

        $destinationParent = Split-Path -Path $finalDestination -Parent
        if (-not (Test-PathExistsSafe -Path $destinationParent -PathType Container)) {
            [System.IO.Directory]::CreateDirectory((ConvertTo-LongPath -Path $destinationParent)) | Out-Null
        }
        try {
            Copy-Item -LiteralPath $sourcePath -Destination $finalDestination -Force:$UseForce -ErrorAction Stop
        }
        catch {
            [System.IO.File]::Copy((ConvertTo-LongPath -Path $sourcePath), (ConvertTo-LongPath -Path $finalDestination), $UseForce)
            if ($reason -eq 'Copied successfully.') {
                $reason = 'Copied successfully using long-path fallback.'
            }
        }

        # Copy-Item normally preserves LastWriteTime, but this explicit set makes the intent reviewable.
        try {
            [System.IO.File]::SetLastWriteTimeUtc((ConvertTo-LongPath -Path $finalDestination), [System.IO.File]::GetLastWriteTimeUtc((ConvertTo-LongPath -Path $sourcePath)))
            [System.IO.File]::SetCreationTimeUtc((ConvertTo-LongPath -Path $finalDestination), [System.IO.File]::GetCreationTimeUtc((ConvertTo-LongPath -Path $sourcePath)))
        }
        catch {
            Add-MigrationError -Stage 'preserve_timestamps' -Path $finalDestination -Message $_.Exception.Message -ExceptionType $_.Exception.GetType().FullName
        }

        return [pscustomobject]@{
            timestamp = (Get-Date).ToString('o')
            operation = $Operation
            source_path = $sourcePath
            relative_path = $InventoryItem.relative_path
            requested_destination_path = $requestedDestination
            destination_path = $finalDestination
            category = $Category
            status = $status
            reason = $reason
            size_bytes = [int64]$InventoryItem.size_bytes
            source_sha256 = $InventoryItem.sha256
            destination_sha256 = $destinationSha256
            collision_action = $collisionAction
            error_message = ''
        }
    }
    catch {
        Add-MigrationError -Stage 'copy_file' -Path $sourcePath -Message $_.Exception.Message -ExceptionType $_.Exception.GetType().FullName
        return [pscustomobject]@{
            timestamp = (Get-Date).ToString('o')
            operation = $Operation
            source_path = $sourcePath
            relative_path = $InventoryItem.relative_path
            requested_destination_path = $requestedDestination
            destination_path = $finalDestination
            category = $Category
            status = 'failed'
            reason = 'Copy failed.'
            size_bytes = [int64]$InventoryItem.size_bytes
            source_sha256 = $InventoryItem.sha256
            destination_sha256 = $destinationSha256
            collision_action = $collisionAction
            error_message = $_.Exception.Message
        }
    }
}

function Convert-InventorySkipToReport {
    param([Parameter(Mandatory = $true)]$InventoryItem)

    $skipStatus = 'skipped_before_copy'
    $skipStatusProperty = $InventoryItem.PSObject.Properties['proposed_skip_status']
    if ($null -ne $skipStatusProperty -and -not [string]::IsNullOrWhiteSpace([string]$skipStatusProperty.Value)) {
        $skipStatus = [string]$skipStatusProperty.Value
    }

    return [pscustomobject]@{
        timestamp = (Get-Date).ToString('o')
        source_path = $InventoryItem.full_source_path
        relative_path = $InventoryItem.relative_path
        proposed_destination_path = $InventoryItem.proposed_destination_path
        category = $InventoryItem.proposed_category
        status = $skipStatus
        reason = $InventoryItem.proposed_reason
        size_bytes = [int64]$InventoryItem.size_bytes
        source_sha256 = $InventoryItem.sha256
    }
}

function Export-Report {
    param(
        [Parameter(Mandatory = $true)]$Items,
        [Parameter(Mandatory = $true)][string]$CsvPath,
        [Parameter(Mandatory = $true)][string]$JsonPath,
        [string[]]$Columns = @()
    )

    $normalItems = New-Object 'System.Collections.Generic.List[object]'
    if ($null -ne $Items) {
        if (($Items -is [System.Collections.IEnumerable]) -and -not ($Items -is [string])) {
            foreach ($item in $Items) {
                $normalItems.Add($item) | Out-Null
            }
        }
        else {
            $normalItems.Add($Items) | Out-Null
        }
    }
    $array = $normalItems.ToArray()

    if ($array.Count -gt 0) {
        $array | Export-Csv -LiteralPath $CsvPath -NoTypeInformation -Encoding UTF8
    }
    elseif ($Columns.Count -gt 0) {
        $header = ($Columns | ForEach-Object { '"' + ($_ -replace '"', '""') + '"' }) -join ','
        Set-Content -LiteralPath $CsvPath -Value $header -Encoding UTF8
    }
    else {
        Set-Content -LiteralPath $CsvPath -Value '' -Encoding UTF8
    }

    $json = ConvertTo-Json -InputObject $array -Depth 12
    if ([string]::IsNullOrWhiteSpace($json)) {
        $json = '[]'
    }
    Set-Content -LiteralPath $JsonPath -Value $json -Encoding UTF8
}

function Write-GeneratedFileSafely {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][bool]$UseForce,
        [Parameter(Mandatory = $true)][bool]$AllowUpdate,
        [Parameter(Mandatory = $true)][bool]$IsDryRun
    )

    $status = 'created'
    $actualPath = $Path
    $backupPath = ''

    if ($IsDryRun) {
        $Script:GeneratedFiles.Add([pscustomobject]@{
            timestamp = (Get-Date).ToString('o')
            description = $Description
            requested_path = $Path
            actual_path = $Path
            status = 'dry_run_would_write'
            backup_path = ''
        }) | Out-Null
        return
    }

    $parent = Split-Path -Path $Path -Parent
    Ensure-Directory -Path $parent

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $existingContent = Get-Content -LiteralPath $Path -Raw
        if ($existingContent -eq $Content) {
            $status = 'already_current'
        }
        elseif ($UseForce -or $AllowUpdate) {
            $backupPath = Resolve-DestinationCollision -DestinationPath ($Path + '.previous') -Stamp $Script:RunStamp
            Copy-Item -LiteralPath $Path -Destination $backupPath -Force -ErrorAction Stop
            Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
            $status = 'updated_existing_with_backup'
        }
        else {
            $actualPath = Resolve-DestinationCollision -DestinationPath $Path -Stamp $Script:RunStamp
            Set-Content -LiteralPath $actualPath -Value $Content -Encoding UTF8
            $status = 'wrote_duplicate_to_avoid_overwrite'
        }
    }
    else {
        Set-Content -LiteralPath $Path -Value $Content -Encoding UTF8
    }

    $Script:GeneratedFiles.Add([pscustomobject]@{
        timestamp = (Get-Date).ToString('o')
        description = $Description
        requested_path = $Path
        actual_path = $actualPath
        status = $status
        backup_path = $backupPath
    }) | Out-Null
}

function New-LatestReleaseManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$UseForce,
        [Parameter(Mandatory = $true)][bool]$IsDryRun
    )

    $releaseFolder = Join-PathMany -Root $Destination -Children @('01_App', 'Releases', 'EOAT_Atlas_0.1.0')
    $latestPath = Join-PathMany -Root $Destination -Children @('01_App', 'Releases', 'latest.json')
    $manifest = [ordered]@{
        latest_version = '0.1.0'
        minimum_supported_version = '0.1.0'
        release_path = $releaseFolder
        published_at = (Get-Date).ToString('o')
        release_notes = @(
            'Initial organized network-drive structure created',
            'Prepared folder layout for installer, local cache, event log, and future SQLite support'
        )
    }
    $content = $manifest | ConvertTo-Json -Depth 6

    Write-GeneratedFileSafely -Path $latestPath -Content $content -Description 'Latest release manifest' -UseForce $UseForce -AllowUpdate $true -IsDryRun $IsDryRun

    $releaseReadme = @"
# EOAT Atlas 0.1.0 Release Placeholder

This folder is reserved for the packaged EOAT Atlas 0.1.0 desktop release.

The migration tool creates the release folder and release manifest, but it does not build or package
an executable installer. Until a packaged release is built, review `01_App\Source_Current` for copied
source files and use `01_App\Installer` / `01_App\Launcher` for future deployment artifacts.
"@
    $releaseReadmePath = Join-Path -Path $releaseFolder -ChildPath 'README_RELEASE_PLACEHOLDER.md'
    Write-GeneratedFileSafely -Path $releaseReadmePath -Content $releaseReadme -Description 'Release placeholder README' -UseForce $UseForce -AllowUpdate $true -IsDryRun $IsDryRun
}

function New-NetworkConfig {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$UseForce,
        [Parameter(Mandatory = $true)][bool]$IsDryRun
    )

    $configPath = Join-PathMany -Root $Destination -Children @('00_Admin', 'Config', 'eoat_atlas_network_config.json')
    $config = [ordered]@{
        network_root = $Destination
        workbooks_root = Join-PathMany -Root $Destination -Children @('02_Data', 'Workbooks')
        shared_assets_root = Join-PathMany -Root $Destination -Children @('03_Shared_Assets')
        exports_root = Join-PathMany -Root $Destination -Children @('04_Exports')
        event_log_root = Join-PathMany -Root $Destination -Children @('02_Data', 'Event_Log')
        locks_root = Join-PathMany -Root $Destination -Children @('02_Data', 'Locks')
        releases_root = Join-PathMany -Root $Destination -Children @('01_App', 'Releases')
        latest_release_manifest = Join-PathMany -Root $Destination -Children @('01_App', 'Releases', 'latest.json')
    }
    $content = $config | ConvertTo-Json -Depth 6
    Write-GeneratedFileSafely -Path $configPath -Content $content -Description 'EOAT Atlas network config' -UseForce $UseForce -AllowUpdate $true -IsDryRun $IsDryRun
}

function New-NetworkReadme {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$UseForce,
        [Parameter(Mandatory = $true)][bool]$IsDryRun
    )

    $readme = @"
# EOAT Atlas Network Folder

This folder is the central EOAT Atlas network location for Nolato Plant 4.

The EOAT Atlas desktop app should eventually be installed locally on each PC using the installer in
`01_App\Installer`. The network folder holds shared data, EOAT photos, tool photos, machine photos,
documents, logs, exports, release manifests, and migration records.

The Excel tracker is the shared human-readable tracker/export. Future EOAT Atlas app instances should
use a local SQLite cache for speed and resilience, then synchronize approved updates back to the
shared network data.

Global events should be written under `02_Data\Event_Log`. Workbook writes should be protected with
locks under `02_Data\Locks` so multiple users do not write the same shared workbook at the same time.

Users should not manually reorganize this folder without approval from the EOAT Atlas project owner
or Plant 4 maintenance/manufacturing engineering leadership.
"@

    $readmePath = Join-Path -Path $Destination -ChildPath 'README_EOAT_ATLAS_NETWORK_FOLDER.md'
    Write-GeneratedFileSafely -Path $readmePath -Content $readme -Description 'Network folder README' -UseForce $UseForce -AllowUpdate $true -IsDryRun $IsDryRun

    $adminReadme = @"
# 00_Admin

This area stores migration logs, manifests, configuration, change notes, and administrative README
material for the EOAT Atlas network folder.
"@
    $adminReadmePath = Join-PathMany -Root $Destination -Children @('00_Admin', 'README', 'README_ADMIN.md')
    Write-GeneratedFileSafely -Path $adminReadmePath -Content $adminReadme -Description 'Admin README' -UseForce $UseForce -AllowUpdate $true -IsDryRun $IsDryRun
}

function Test-CopiedFiles {
    param(
        [Parameter(Mandatory = $true)]$CopyResults
    )

    $eligibleStatuses = @('copied', 'copied_duplicate', 'overwritten', 'skipped_already_exists_same')
    $eligible = @($CopyResults | Where-Object { $eligibleStatuses -contains $_.status })
    $reports = New-Object 'System.Collections.Generic.List[object]'
    $total = $eligible.Count
    $i = 0

    foreach ($item in $eligible) {
        $i++
        if ($total -gt 0) {
            Write-Progress -Activity 'Verify copied files' -Status "$i of $total" -PercentComplete (($i / $total) * 100)
        }

        $destinationPath = [string]$item.destination_path
        $exists = Test-PathExistsSafe -Path $destinationPath -PathType Leaf
        $destinationSize = $null
        $destinationHash = ''
        $sizeMatches = $false
        $hashMatches = $false
        $verificationStatus = 'failed_missing'
        $message = 'Destination file is missing.'

        if ($exists) {
            try {
                $destinationItem = Get-FileInfoSafe -Path $destinationPath
                $destinationSize = [int64]$destinationItem.Length
                $sizeMatches = ($destinationSize -eq [int64]$item.size_bytes)

                if (-not $sizeMatches) {
                    $verificationStatus = 'failed_size_mismatch'
                    $message = 'Destination file exists but size does not match source manifest.'
                }
                elseif (-not [string]::IsNullOrWhiteSpace([string]$item.source_sha256)) {
                    $hashInfo = Get-FileHashSafe -FileInfo $destinationItem -AlwaysHash $true
                    $destinationHash = $hashInfo.hash
                    $hashMatches = ($destinationHash -eq [string]$item.source_sha256)
                    if ($hashMatches) {
                        $verificationStatus = 'verified_hash_and_size'
                        $message = 'Destination file exists with matching size and SHA256 hash.'
                    }
                    else {
                        $verificationStatus = 'failed_hash_mismatch'
                        $message = 'Destination file exists and size matches, but SHA256 hash differs.'
                    }
                }
                else {
                    $verificationStatus = 'verified_size_only'
                    $message = 'Destination file exists with matching size; source hash was unavailable or skipped.'
                }
            }
            catch {
                Add-MigrationError -Stage 'verify_file' -Path $destinationPath -Message $_.Exception.Message -ExceptionType $_.Exception.GetType().FullName
                $verificationStatus = 'failed_verify_error'
                $message = $_.Exception.Message
            }
        }

        $reports.Add([pscustomobject]@{
            timestamp = (Get-Date).ToString('o')
            source_path = $item.source_path
            relative_path = $item.relative_path
            destination_path = $destinationPath
            category = $item.category
            copy_status = $item.status
            exists = $exists
            source_size_bytes = [int64]$item.size_bytes
            destination_size_bytes = $destinationSize
            size_matches = $sizeMatches
            source_sha256 = $item.source_sha256
            destination_sha256 = $destinationHash
            hash_matches = $hashMatches
            verification_status = $verificationStatus
            message = $message
        }) | Out-Null
    }

    Write-Progress -Activity 'Verify copied files' -Completed
    return $reports.ToArray()
}

function Resolve-VerifyLogFolder {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$RequestedLogRoot
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedLogRoot)) {
        if (Test-Path -LiteralPath (Join-Path -Path $RequestedLogRoot -ChildPath 'copied_files.json') -PathType Leaf) {
            return $RequestedLogRoot
        }

        $candidateRoot = $RequestedLogRoot
    }
    else {
        $candidateRoot = Join-PathMany -Root $Destination -Children @('00_Admin', 'Migration_Logs')
    }

    if (-not (Test-Path -LiteralPath $candidateRoot -PathType Container)) {
        throw "Could not find migration log root for verification: $candidateRoot"
    }

    $latest = Get-ChildItem -LiteralPath $candidateRoot -Directory -Filter 'Migration_*' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $latest) {
        throw "No Migration_* folders found under: $candidateRoot"
    }

    return $latest.FullName
}

function Get-ReportColumns {
    param([Parameter(Mandatory = $true)][string]$ReportName)

    switch ($ReportName) {
        'inventory' {
            return @('full_source_path', 'relative_path', 'file_name', 'extension', 'size_bytes', 'last_modified', 'sha256', 'hash_status', 'proposed_destination_path', 'proposed_category', 'proposed_action', 'proposed_reason', 'proposed_skip_status')
        }
        'copied' {
            return @('timestamp', 'operation', 'source_path', 'relative_path', 'requested_destination_path', 'destination_path', 'category', 'status', 'reason', 'size_bytes', 'source_sha256', 'destination_sha256', 'collision_action', 'error_message')
        }
        'skipped' {
            return @('timestamp', 'source_path', 'relative_path', 'proposed_destination_path', 'category', 'status', 'reason', 'size_bytes', 'source_sha256')
        }
        'errors' {
            return @('timestamp', 'stage', 'path', 'message', 'exception_type')
        }
        'verification' {
            return @('timestamp', 'source_path', 'relative_path', 'destination_path', 'category', 'copy_status', 'exists', 'source_size_bytes', 'destination_size_bytes', 'size_matches', 'source_sha256', 'destination_sha256', 'hash_matches', 'verification_status', 'message')
        }
        'folders' {
            return @('folder_number', 'relative_path', 'full_path', 'action')
        }
        'collisions' {
            return @('timestamp', 'source_path', 'requested_destination_path', 'resolved_destination_path', 'category', 'operation', 'action')
        }
        'generated' {
            return @('timestamp', 'description', 'requested_path', 'actual_path', 'status', 'backup_path')
        }
        default {
            return @()
        }
    }
}

function Write-FinalSummary {
    param(
        [object[]]$Inventory,
        [object[]]$CopyResults,
        [object[]]$SkippedFiles,
        [object[]]$VerificationReports,
        [string]$Destination,
        [string]$LogFolder,
        [bool]$IsDryRun,
        [bool]$IsVerifyOnly
    )

    $copiedStatuses = @('copied', 'copied_duplicate', 'overwritten')
    $wouldCopyStatuses = @('dry_run_would_copy', 'dry_run_would_copy_duplicate', 'dry_run_would_overwrite')
    $copied = @($CopyResults | Where-Object { $copiedStatuses -contains $_.status })
    $wouldCopy = @($CopyResults | Where-Object { $wouldCopyStatuses -contains $_.status })
    $skippedExistingSame = @($CopyResults | Where-Object { $_.status -eq 'skipped_already_exists_same' })
    $skippedSystemFiles = @($SkippedFiles | Where-Object { $_.status -eq 'skipped_system_file' })
    $skippedBackupOrLegacy = @($SkippedFiles | Where-Object { $_.status -eq 'skipped_backup_or_legacy' })
    $backupOrLegacyRouted = @($CopyResults | Where-Object { $_.category -eq 'Backup_Or_Legacy_Needs_Review' })
    $collisionRenamed = @($CopyResults | Where-Object { $_.collision_action -eq 'duplicate_filename' })
    $copyFailures = @($CopyResults | Where-Object { $_.status -eq 'failed' })
    $verified = @($VerificationReports | Where-Object { ([string]$_.verification_status).StartsWith('verified') })
    [int64]$totalCopiedSize = 0
    foreach ($copiedItem in $copied) {
        if ($null -ne $copiedItem.size_bytes) {
            $totalCopiedSize += [int64]$copiedItem.size_bytes
        }
    }

    Write-Host ''
    Write-Host 'EOAT Atlas migration summary' -ForegroundColor Cyan
    Write-Host '----------------------------' -ForegroundColor Cyan
    if ($IsVerifyOnly) {
        Write-Host 'Mode: VerifyOnly'
    }
    elseif ($IsDryRun) {
        Write-Host 'Mode: DryRun (no destination folders created, no files copied)'
    }
    else {
        Write-Host 'Mode: Real run'
    }
    Write-Host "Files discovered: $(@($Inventory).Count)"
    Write-Host "Files copied: $($copied.Count)"
    Write-Host "Files that would copy: $($wouldCopy.Count)"
    Write-Host "Files skipped: $(@($SkippedFiles).Count)"
    Write-Host "  copied: $($copied.Count)"
    Write-Host "  skipped_existing_same: $($skippedExistingSame.Count)"
    Write-Host "  skipped_system_file: $($skippedSystemFiles.Count)"
    Write-Host "  skipped_backup_or_legacy: $($skippedBackupOrLegacy.Count)"
    Write-Host "  backup_or_legacy_routed_to_needs_review: $($backupOrLegacyRouted.Count)"
    Write-Host "  collision_renamed: $($collisionRenamed.Count)"
    Write-Host "  failed: $($copyFailures.Count)"
    Write-Host "Files failed: $($copyFailures.Count)"
    Write-Host "Files verified: $($verified.Count)"
    Write-Host "Total copied size bytes: $totalCopiedSize"
    Write-Host "Migration errors logged: $($Script:Errors.Count)"
    Write-Host "Destination: $Destination"
    Write-Host "Log folder: $LogFolder"
    Write-Host ''
}

function Invoke-VerifyOnly {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$RequestedLogRoot
    )

    $logFolder = Resolve-VerifyLogFolder -Destination $Destination -RequestedLogRoot $RequestedLogRoot
    $manifestPath = Join-Path -Path $logFolder -ChildPath 'copied_files.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Could not find copied_files.json in verification log folder: $logFolder"
    }

    Write-Host "Using copy manifest: $manifestPath" -ForegroundColor Cyan
    $copyResults = @(Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json)
    $verification = Test-CopiedFiles -CopyResults $copyResults

    Export-Report -Items $verification `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'verification_report.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'verification_report.json') `
        -Columns (Get-ReportColumns -ReportName 'verification')

    Export-Report -Items $Script:Errors.ToArray() `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'migration_errors.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'migration_errors.json') `
        -Columns (Get-ReportColumns -ReportName 'errors')

    Write-FinalSummary -Inventory @() -CopyResults $copyResults -SkippedFiles @() -VerificationReports $verification -Destination $Destination -LogFolder $logFolder -IsDryRun $false -IsVerifyOnly $true
}

function Invoke-Migration {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$IsDryRun,
        [Parameter(Mandatory = $true)][bool]$IncludeAppSourceForRun,
        [Parameter(Mandatory = $true)][bool]$IncludeLegacyArchiveForRun,
        [Parameter(Mandatory = $true)][bool]$UseForce,
        [string]$RequestedLogRoot
    )

    $logFolder = New-MigrationLogFolder -Destination $Destination -IsDryRun $IsDryRun -RequestedLogRoot $RequestedLogRoot
    Write-Host "Writing migration logs/manifests to: $logFolder" -ForegroundColor Cyan

    $folderPlan = New-EoatAtlasFolderStructure -Destination $Destination -IsDryRun $IsDryRun
    Export-Report -Items $folderPlan `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'folder_creation_plan.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'folder_creation_plan.json') `
        -Columns (Get-ReportColumns -ReportName 'folders')

    if ($IsDryRun) {
        Write-Host 'Dry run: folder structure was planned but not created at the destination.' -ForegroundColor Yellow
    }
    else {
        New-LatestReleaseManifest -Destination $Destination -UseForce $UseForce -IsDryRun $false
        New-NetworkConfig -Destination $Destination -UseForce $UseForce -IsDryRun $false
        New-NetworkReadme -Destination $Destination -UseForce $UseForce -IsDryRun $false
    }

    $inventory = Get-SourceInventory -Source $Source -Destination $Destination -IncludeAppSourceForRun $IncludeAppSourceForRun

    Export-Report -Items $inventory `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'inventory_before.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'inventory_before.json') `
        -Columns (Get-ReportColumns -ReportName 'inventory')

    $copyResults = New-Object 'System.Collections.Generic.List[object]'
    $skippedFiles = New-Object 'System.Collections.Generic.List[object]'

    foreach ($item in @($inventory | Where-Object { $_.proposed_action -eq 'skip' })) {
        $skippedFiles.Add((Convert-InventorySkipToReport -InventoryItem $item)) | Out-Null
    }

    $mappedItems = @($inventory | Where-Object { $_.proposed_action -eq 'copy_mapped' })
    $mappedTotal = $mappedItems.Count
    $i = 0

    foreach ($item in $mappedItems) {
        $i++
        if ($mappedTotal -gt 0) {
            Write-Progress -Activity 'Copy mapped files' -Status "$i of $mappedTotal" -PercentComplete (($i / $mappedTotal) * 100)
        }

        $result = Copy-FileSafely -InventoryItem $item `
            -DestinationPath $item.proposed_destination_path `
            -Category $item.proposed_category `
            -Operation 'mapped_copy' `
            -IsDryRun $IsDryRun `
            -UseForce $UseForce
        $copyResults.Add($result) | Out-Null
    }
    Write-Progress -Activity 'Copy mapped files' -Completed

    if ($IncludeLegacyArchiveForRun) {
        Write-Host 'IncludeLegacyArchive enabled: preserving full original folder structure under 99_Legacy_Archive\Original_Folder_Structure.' -ForegroundColor Yellow
        $archiveItems = @($inventory | Where-Object { $_.proposed_category -notin @('Excluded_System_File', 'Excluded_Directory') })
        $archiveTotal = $archiveItems.Count
        $archiveIndex = 0

        foreach ($item in $archiveItems) {
            $archiveIndex++
            if ($archiveTotal -gt 0) {
                Write-Progress -Activity 'Copy legacy archive' -Status "$archiveIndex of $archiveTotal" -PercentComplete (($archiveIndex / $archiveTotal) * 100)
            }

            $archiveDestination = Join-PathMany -Root $Destination -Children @('99_Legacy_Archive', 'Original_Folder_Structure', $item.relative_path)
            $archiveResult = Copy-FileSafely -InventoryItem $item `
                -DestinationPath $archiveDestination `
                -Category 'Legacy_Archive_Original_Folder_Structure' `
                -Operation 'legacy_archive_copy' `
                -IsDryRun $IsDryRun `
                -UseForce $UseForce
            $copyResults.Add($archiveResult) | Out-Null
        }
        Write-Progress -Activity 'Copy legacy archive' -Completed
    }
    else {
        Write-Host 'Full original-structure archive is disabled. Pass -IncludeLegacyArchive to add it.' -ForegroundColor DarkGray
    }

    foreach ($copyResult in @($copyResults | Where-Object { $_.status -like 'skipped_*' })) {
        $skippedFiles.Add([pscustomobject]@{
            timestamp = $copyResult.timestamp
            source_path = $copyResult.source_path
            relative_path = $copyResult.relative_path
            proposed_destination_path = $copyResult.requested_destination_path
            category = $copyResult.category
            status = $copyResult.status
            reason = $copyResult.reason
            size_bytes = [int64]$copyResult.size_bytes
            source_sha256 = $copyResult.source_sha256
        }) | Out-Null
    }

    Export-Report -Items $copyResults.ToArray() `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'copied_files.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'copied_files.json') `
        -Columns (Get-ReportColumns -ReportName 'copied')

    Export-Report -Items $skippedFiles.ToArray() `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'skipped_files.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'skipped_files.json') `
        -Columns (Get-ReportColumns -ReportName 'skipped')

    Export-Report -Items $Script:Collisions.ToArray() `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'collisions.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'collisions.json') `
        -Columns (Get-ReportColumns -ReportName 'collisions')

    if ($IsDryRun) {
        New-LatestReleaseManifest -Destination $Destination -UseForce $UseForce -IsDryRun $true
        New-NetworkConfig -Destination $Destination -UseForce $UseForce -IsDryRun $true
        New-NetworkReadme -Destination $Destination -UseForce $UseForce -IsDryRun $true
        Set-Content -LiteralPath (Join-Path -Path $logFolder -ChildPath 'verification_report.txt') -Value 'Dry run only. No destination files were copied, so verification was not performed.' -Encoding UTF8
        $verification = @()
    }
    else {
            $verification = Test-CopiedFiles -CopyResults $copyResults.ToArray()
    }

    Export-Report -Items $verification `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'verification_report.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'verification_report.json') `
        -Columns (Get-ReportColumns -ReportName 'verification')

    Export-Report -Items $Script:GeneratedFiles.ToArray() `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'generated_files.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'generated_files.json') `
        -Columns (Get-ReportColumns -ReportName 'generated')

    Export-Report -Items $Script:Errors.ToArray() `
        -CsvPath (Join-Path -Path $logFolder -ChildPath 'migration_errors.csv') `
        -JsonPath (Join-Path -Path $logFolder -ChildPath 'migration_errors.json') `
        -Columns (Get-ReportColumns -ReportName 'errors')

    Write-FinalSummary -Inventory $inventory -CopyResults $copyResults.ToArray() -SkippedFiles $skippedFiles.ToArray() -VerificationReports $verification -Destination $Destination -LogFolder $logFolder -IsDryRun $IsDryRun -IsVerifyOnly $false
}

try {
    $Script:MigrationConfig = Import-MigrationConfig

    if (-not $PSBoundParameters.ContainsKey('SourceRoot')) {
        $SourceRoot = [string](Get-ConfigValue -Name 'default_source_root' -DefaultValue $SourceRoot)
    }
    if (-not $PSBoundParameters.ContainsKey('DestinationRoot')) {
        $DestinationRoot = [string](Get-ConfigValue -Name 'default_destination_root' -DefaultValue $DestinationRoot)
    }

    $includeAppSourceEffective = $IncludeAppSource.IsPresent
    if (-not $PSBoundParameters.ContainsKey('IncludeAppSource')) {
        $includeAppSourceEffective = [bool](Get-ConfigValue -Name 'include_app_source_by_default' -DefaultValue $true)
    }

    Write-Host ''
    Write-Host 'EOAT Atlas Network Migration Tool' -ForegroundColor Cyan
    Write-Host '---------------------------------' -ForegroundColor Cyan
    Write-Host "SourceRoot:      $SourceRoot"
    Write-Host "DestinationRoot: $DestinationRoot"
    Write-Host "DryRun:          $($DryRun.IsPresent)"
    Write-Host "VerifyOnly:      $($VerifyOnly.IsPresent)"
    Write-Host "IncludeAppSource:$includeAppSourceEffective"
    Write-Host "Legacy archive:  $($IncludeLegacyArchive.IsPresent)"
    Write-Host "Force:           $($Force.IsPresent)"
    Write-Host ''

    Test-SourceAndDestination -Source $SourceRoot -Destination $DestinationRoot -IsDryRun $DryRun.IsPresent -IsVerifyOnly $VerifyOnly.IsPresent

    if ($VerifyOnly.IsPresent) {
        Invoke-VerifyOnly -Destination $DestinationRoot -RequestedLogRoot $LogRoot
    }
    else {
        Invoke-Migration -Source $SourceRoot `
            -Destination $DestinationRoot `
            -IsDryRun $DryRun.IsPresent `
            -IncludeAppSourceForRun $includeAppSourceEffective `
            -IncludeLegacyArchiveForRun $IncludeLegacyArchive.IsPresent `
            -UseForce $Force.IsPresent `
            -RequestedLogRoot $LogRoot
    }
}
catch {
    Add-MigrationError -Stage 'fatal' -Path '' -Message $_.Exception.Message -ExceptionType $_.Exception.GetType().FullName
    Write-Error $_.Exception.Message
    exit 1
}
