# EOAT Atlas Usage

Scope: minimalist/current EOAT Atlas only.

## Launch

```powershell
python run_atlas.py
```

Equivalent:

```powershell
python -m app.atlas.main
```

The app always launches EOAT Atlas in the current minimalist UI. `--ui` arguments are ignored for release scope cleanup.

## Runtime

For development, mutable state is stored under:

```text
%LOCALAPPDATA%\EOAT_Atlas_Dev
```

This includes local cache databases, manifests, settings, logs, thumbnails, pending updates, event outbox files, staging files, and temp files.

## Refresh And Offline Use

Refresh reloads EOAT Atlas from the existing local SQLite cache. It does not touch the network workbook and it preserves/reapplies pending updates.

Deep Refresh rebuilds the local SQLite cache from staged workbook copies. If Deep Refresh fails, the last known good cache remains in place.

Production workbook writes are disabled by default. Local edit actions create pending updates until an explicit sync mode is enabled and tested.

## Packaging Target

Future packaging should use only:

```text
EOAT_Atlas.spec
packaging/eoat_atlas_entry.py
```

Do not add Command Center, classic Atlas, or old dashboard launchers to release artifacts.
