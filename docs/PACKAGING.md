# Packaging EOAT Atlas

Scope: minimalist/current EOAT Atlas only.

Packaging is intentionally not run in this phase. The future PyInstaller onedir build should produce one app:

```text
dist/EOAT Atlas/EOAT Atlas.exe
```

Use:

```text
EOAT_Atlas.spec
packaging/eoat_atlas_entry.py
```

The package must not include Command Center, classic EOAT Atlas, old dashboard launchers, or legacy Atlas entry points.

## Source Smoke

```powershell
$env:EOAT_ATLAS_SMOKE_TEST = "1"
python run_atlas.py
Remove-Item Env:\EOAT_ATLAS_SMOKE_TEST
```

## Runtime State

Packaged app files are read-only. Mutable user/runtime files must live under local app data:

```text
%LOCALAPPDATA%\EOAT_Atlas
```

Development uses:

```text
%LOCALAPPDATA%\EOAT_Atlas_Dev
```

SQLite cache databases, settings, logs, thumbnails, pending updates, event outbox files, lock metadata, staging files, backups, and temp files must remain outside the source and packaged app directories.

Refresh must stay local-cache only. Deep Refresh is the only user-facing workbook-backed cache rebuild action. Production workbook writes must remain disabled by default in packaged output unless a future release intentionally enables and tests that config gate.

## Build Notes

Before PyInstaller, run:

```powershell
python scripts\preflight_onedir_readiness.py
```

After onedir is built, run:

```powershell
python scripts\smoke_test_package.py "dist\EOAT Atlas\EOAT Atlas.exe"
```

Do not create an installer or launcher until the onedir output has passed smoke testing.
