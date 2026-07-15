# EOAT Atlas Network Migration Tool

This folder contains a safe, reviewable migration tool for copying the current EOAT Standardization project into the final shared EOAT Atlas network-drive structure.

The tool is intentionally copy-only. It does not delete, move, rename, or modify the original source folder.

## Files

- `migrate_eoat_atlas_to_network.ps1` - main PowerShell migration script.
- `migration_config.json` - optional defaults and folder/category configuration read by the script if present.
- `README_MIGRATION.md` - this review guide.

## Default paths

Source:

```powershell
C:\Sanitized\LegacySource
```

Destination:

```powershell
C:\Sanitized\EOATAtlasDestination
```

The script uses quoted/literal-safe PowerShell operations so the ampersand in `Maintenance & Manufacturing Engineering` is handled correctly.

## Dry run

Run this first:

```powershell
.\migrate_eoat_atlas_to_network.ps1 -DryRun
```

If PowerShell blocks script execution on this PC, use the one-time process bypass form:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\migrate_eoat_atlas_to_network.ps1" -DryRun
```

Dry-run mode does not create the destination folder structure and does not copy files. It builds the same inventory and proposed copy manifest, then writes review logs under:

```text
.\Migration_Dry_Run_Logs\Migration_YYYYMMDD_HHMMSS
```

Use `-LogRoot` to place dry-run logs somewhere else.

## Patched rerun after previous copy errors

If the first migration produced `Thumbs.db` errors or `System.IO.DirectoryNotFoundException` errors for nested photo paths, run the patched script again. Run dry-run first and review the new reports before running the real migration:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\migrate_eoat_atlas_to_network.ps1" -DryRun
```

It is safe to rerun because the script checks existing files and avoids overwriting unless `-Force` is used.

## Real migration

After reviewing the dry-run reports:

```powershell
.\migrate_eoat_atlas_to_network.ps1
```

A real run creates the destination folder structure, copies mapped files, writes generated network config/readme/release manifest files, and runs verification after copying.

## Verify only

To rerun verification against the latest real migration log:

```powershell
.\migrate_eoat_atlas_to_network.ps1 -VerifyOnly
```

To verify a specific log folder:

```powershell
.\migrate_eoat_atlas_to_network.ps1 -VerifyOnly -LogRoot "C:\Sanitized\Migration_Logs\Migration_YYYYMMDD_HHMMSS"
```

## Optional switches

- `-SourceRoot "path"` changes the source folder.
- `-DestinationRoot "path"` changes the final EOAT Atlas network folder.
- `-DryRun` reports what would happen without copying.
- `-VerifyOnly` verifies files from an existing `copied_files.json` manifest.
- `-IncludeAppSource` explicitly includes app/source categories. The included config enables this by default; use `-IncludeAppSource:$false` to skip app source.
- `-IncludeLegacyArchive` also copies the full original source folder structure under `99_Legacy_Archive\Original_Folder_Structure`.
- `-Force` allows copy operations to overwrite destination files. Without `-Force`, collisions are handled with duplicate-safe filenames.
- `-LogRoot "path"` changes where migration logs are written.

## What gets copied

The script inventories all source files first, then maps files into the clean EOAT Atlas structure:

- App/source files go to `01_App\Source_Current`.
- Excel workbooks go to `02_Data\Workbooks` subfolders such as `Master_Tracker`, `Press_Capacity`, `Robot_EOAT`, or `Legacy_Imports`.
- EOAT/tool/machine photos go to `03_Shared_Assets`.
- Setup packet templates and generated packets go to setup-packet asset/export folders.
- Documents go to `07_Documentation`.
- Logs go to `06_Logs\App_Logs\Imported_Logs`.
- Reports go to `04_Exports\Reports\Imported_Reports`.
- Unknown files are preserved under `99_Legacy_Archive\Needs_Review`.
- Files from backup or legacy paths are routed to `99_Legacy_Archive\Needs_Review` instead of active photo/document/workbook folders.

## Exclusions

By default, clean mapped copies skip cache/build/environment folders such as:

```text
__pycache__, .pytest_cache, .mypy_cache, .ruff_cache, .venv, venv, env,
node_modules, dist, build, .cache, tmp, temp, .git
```

The script also skips harmless system/temp files such as `Thumbs.db`, `desktop.ini`, `.DS_Store`, Office `~$*` temp files, `.tmp`, `.temp`, and `.lock` files.

If `-IncludeLegacyArchive` is supplied, reviewed non-excluded files from the original folder structure are also copied to the legacy archive area for preservation. System/cache/build/temp files remain excluded.

## Collision handling

The script does not overwrite destination files by default.

- Existing same-size/same-hash files are marked `skipped_already_exists_same`.
- Existing files with different or unverified content are copied to a duplicate-safe filename:

```text
OriginalName_DUPLICATE_YYYYMMDD_HHMMSS.ext
```

- `-Force` allows overwriting copied files.

Generated metadata files such as `latest.json` and the network config may be updated by the script. When an existing generated file is changed, the previous version is copied to a timestamped `.previous` backup first.

## Logs and manifests

Real-run logs are saved under:

```text
DestinationRoot\00_Admin\Migration_Logs\Migration_YYYYMMDD_HHMMSS
```

Each run writes:

- `folder_creation_plan.csv/json`
- `inventory_before.csv/json`
- `copied_files.csv/json`
- `skipped_files.csv/json`
- `collisions.csv/json`
- `generated_files.csv/json`
- `migration_errors.csv/json`
- `verification_report.csv/json`

The inventory includes source path, relative path, file name, extension, size, last modified time, SHA256 hash when practical, proposed destination, and proposed category.

## Rollback concept

The original source folder is not modified, so rollback is conceptual and low risk:

1. Stop using the new network folder.
2. Review the run's `copied_files.csv/json` and `generated_files.csv/json`.
3. If needed, manually remove the newly created destination folder or selected copied files after approval.
4. Continue using the original source folder until the migration mapping is corrected and rerun.

Do not manually reorganize the final EOAT Atlas network folder after migration without project-owner approval.
