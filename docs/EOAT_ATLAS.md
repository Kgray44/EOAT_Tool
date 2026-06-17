# EOAT Atlas

EOAT Atlas is a companion app for EOAT Command Center. It is designed for fast search, compatibility lookup, visual review, install support, standards navigation, and read-only data exploration.

Launch it separately:

```powershell
python -m app.atlas.main
```

EOAT Command Center remains the place for audit entry, editing, workbook repair, photo intake, report generation, and data maintenance.

EOAT Atlas is read-only by default. It may create timestamped exports under:

```text
06_Final_Handoff/Atlas_Exports/
```

It does not modify the EOAT Master Tracker, Press Capacity workbook, Robot Info workbook, standards files, or photo folders.

## Data Sources

Atlas uses the active project root from the normal Command Center config and reads:

- `01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx`
- `00_Project_Admin/reference_data/press_capacity.xlsx`
- `01_EOAT_Audit/EOAT_Audit_Database/Robot_Info.xlsx`
- `01_EOAT_Audit/Cell_Photos/`
- `03_Standards/`, `03_Standards/Work_Instructions/`, and generated standard documents when present

If an optional source is missing, Atlas shows a source-status warning and continues with partial data.

## What Do I Need?

Use **What Do I Need?** for flexible install recommendations. The input can be a Tool #, Mold #, Part #, machine number, EOAT ID, robot type, part name, or keyword.

Atlas interprets the input, searches the cached indexes, ranks EOAT candidates, and returns:

- Best EOAT recommendation
- Backup EOATs when applicable
- Compatible machines
- Ranking reasons
- Documentation score
- Photo count
- Warnings and data gaps
- Install checklist
- Standards references

Ranking favors exact compatibility matches, active/audited status, stronger documentation, linked photos, useful connection data, and fewer warnings.

## Compatibility Calculation

Atlas builds compatibility from:

- EOAT Inventory rows in the master tracker
- Press Capacity tool-to-machine relationships
- Robot Info rows by machine
- Photo Index and EOAT photo folders

The backend builds these lookup dictionaries at refresh time:

```text
eoat_by_id
eoats_by_tool
eoats_by_machine
machines_by_tool
machines_by_eoat
tools_by_machine
photos_by_eoat
photos_by_tool
robot_info_by_machine
warnings_by_eoat
warnings_by_machine
documentation_status_by_eoat
```

Pages use these indexes instead of repeatedly scanning workbook rows.

## Performance Model

Atlas is designed to feel fast after data is loaded:

- The window opens immediately.
- Data refresh runs in a background thread.
- Workbooks are loaded once into cached in-memory records.
- Photo indexing records file paths only; thumbnails are loaded lazily when the Photos page is used.
- Search and recommendation use normalized lookup keys.
- Manual **Refresh Data** is available on Settings / Diagnostics.
- The last refreshed timestamp is shown in the status bar and dashboard.

Diagnostics on Settings / Diagnostics include workbook load time, photo index time, cache build time, and bundle counts.

## Page Screenshots

The repository keeps one current Atlas page screenshot set in:

```text
EOAT_Atlas_pages/
```

Refresh the set after Atlas UI updates:

```powershell
python scripts/capture_atlas_pages.py
```

The script removes old PNGs in that folder before writing the new set. It uses the bundled synthetic demo project by default so committed screenshots do not expose private project data.

## Warning Statuses

Atlas flags human-readable warnings such as:

- Missing EOAT Assembly ID
- Missing tool/machine compatibility
- Missing photos
- Missing Robot Info row
- Documentation below target
- Press Capacity tool with no linked EOAT
- Source workbook/folder missing

Each warning includes what is missing, why it matters when available, the source, and a suggested fix. Fixes should be made in EOAT Command Center or the source-of-truth workbook process, not directly in Atlas.

## Main Pages

- **Home / Command Deck**: search, quick actions, source status, project health metrics.
- **What Do I Need?**: guided recommendation and install checklist.
- **EOAT Search / Profiles**: EOAT table plus profile details.
- **Machine Search / Profiles**: machine compatibility and robot context.
- **Tool / Mold / Part Search**: tool-to-EOAT and tool-to-machine lookup.
- **Compatibility Matrix**: EOAT/machine, tool/EOAT, and tool/machine table views.
- **Overall Maps**: machine grid and documentation heatmap.
- **Photos**: EOAT photo folder and indexed-photo browser.
- **Standards**: standard document list and search.
- **PM / Inspection**: generated inspection guidance and missing PM data.
- **Documentation Gaps**: action-oriented warning table.
- **Reports / Export**: timestamped CSV/Markdown exports.
- **Settings / Diagnostics**: source paths, refresh button, and performance timings.

## Known Limitations

- Atlas does not edit source data.
- Standards text extraction is lightweight; DOCX/PDF documents are listed and opened externally.
- Plant-floor map views are grid/coverage views, not a floor-plan drawing.
- Photo thumbnails are session-lazy; Atlas indexes photo paths without generating persistent thumbnail files.
- Recommendation quality depends on clean EOAT IDs, Tool #s, machine fields, and Press Capacity relationships.
