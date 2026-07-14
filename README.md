# EOAT Atlas

Scope: minimalist/current EOAT Atlas only.

This development copy is the globalization worktree for EOAT Atlas. Command Center and the original/classic EOAT Atlas are not part of this dev copy's release, packaging, installer, or launcher target.

## Run

```powershell
python run_atlas.py
```

Equivalent module launch:

```powershell
python -m app.atlas.main
```

Both commands launch the current minimalist EOAT Atlas surface.

## Runtime State

Development runtime files belong under:

```text
%LOCALAPPDATA%\EOAT_Atlas_Dev
```

Future production runtime files should switch to:

```text
%LOCALAPPDATA%\EOAT_Atlas
```

Do not store mutable runtime state in the source checkout or future packaged app directory.

## Data Model

EOAT Atlas uses a local SQLite cache derived from the shared workbook. Normal navigation, search, profiles, Fit Check, and package-building reads use the cache/effective-record layer after initialization.

Refresh reloads the visible app from the existing local SQLite cache and reapplies pending-update overlays. Deep Refresh stages the configured workbook locally, rebuilds a new SQLite cache, validates it, then atomically replaces the active cache while preserving pending updates.

Production workbook sync is disabled by default. Representative edit actions create local pending updates; sandbox write tests use fixture workbooks only.

## Packaging

Packaging is not run in this phase. The future onedir target is:

```text
EOAT_Atlas.spec
packaging/eoat_atlas_entry.py
```

The expected packaged executable name is `EOAT Atlas`.

Before building onedir, run:

```powershell
python scripts\preflight_onedir_readiness.py
```

After onedir exists, run:

```powershell
python scripts\smoke_test_package.py "dist\EOAT Atlas\EOAT Atlas.exe"
```

## Tests

Focused checks for this work:

```powershell
python -m compileall -q run_atlas.py packaging\eoat_atlas_entry.py app\atlas core\globalization
python -m pytest tests\test_globalization_phase1.py tests\test_globalization_phase2.py -q
python -m pytest tests\test_minimalist_command_palette.py tests\test_minimalist_dropdown_lifecycle.py tests\test_minimalist_settings_page.py -q
python -m pytest tests\test_atlas_search_resolution.py tests\test_atlas_entity_search.py tests\test_fit_check_service.py -q
```
