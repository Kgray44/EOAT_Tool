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

It does not modify the EOAT Master Tracker, Press Capacity workbook, Robot Info workbook, or photo folders. The one exception is standards registration: if a likely EOAT standardization document is placed in the project root, Atlas can safely copy it into `03_Standards/` without overwriting an existing file so it appears in the Standards Library and Information Library.

## Data Sources

Atlas uses the active project root from the normal Command Center config and reads:

- `01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx`
- `00_Project_Admin/reference_data/press_capacity.xlsx`
- `01_EOAT_Audit/EOAT_Audit_Database/Robot_Info.xlsx`
- `01_EOAT_Audit/Cell_Photos/`
- `03_Standards/`, `03_Standards/Work_Instructions/`, and generated standard documents when present

If an optional source is missing, Atlas shows a source-status warning and continues with partial data.

Likely root-level standardization documents are detected by names such as `EOAT Standardization`, `EOAT Standard`, `Standard Design`, `Design Guidelines`, or `EOAT Standards` with `.docx`, `.pdf`, `.md`, or `.txt` extensions. Atlas copies them into `03_Standards/` using collision-safe filenames.

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

Recommendation results include direct profile actions. The best recommendation has a prominent **Open EOAT Profile** action plus compact actions for **View Photos**, **Open Related Tool**, **Open Related Machine**, and **Export Recommendation**. Ranked candidates also include compact profile actions so users can jump to the full EOAT, machine, tool, or photo context without rerunning the search.

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
- Photo indexing records file paths only; the Photos page shows summary cards and loads images only when the in-app carousel is opened.
- Search and recommendation use normalized lookup keys.
- Manual **Refresh Data** is available on Settings / Diagnostics.
- The last refreshed timestamp is shown in the status bar and dashboard.

Diagnostics on Settings / Diagnostics include workbook load time, photo index time, cache build time, and bundle counts.

## Settings And Dark Mode

Settings / Diagnostics includes editable Atlas preferences that persist per user in the app config folder, not in source workbooks. Current settings include:

- Light, Dark, or System/default theme
- Color scheme: Atlas Blue or Nolato Logo
- Default startup page
- Default search mode
- Photo viewer behavior: in-app carousel, open folder, or external viewer
- Lazy photo preview and carousel prefetch options
- Advanced diagnostics visibility
- Compact or comfortable list/card density
- Export and external-open behavior
- Auto-refresh data on startup

Theme and color scheme changes apply immediately. Atlas defaults to light mode with Atlas Blue unless the user changes it. The Nolato Logo color scheme uses controlled red accents, charcoal anchors, and neutral surfaces; it does not replace dark mode or make the whole UI red.

## Photo Viewer

The Photos page uses summary cards with EOAT ID, photo count, folder status, missing categories, and actions. **View Photos** opens an in-app carousel that displays one image at a time with previous/next controls, filename/category, count, close, open folder, and open externally actions. Left/right arrow keys navigate and Escape closes the viewer.

The viewer supports `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, and `.heif` when the local Qt/Pillow decoders can read them. HEIC/HEIF preview uses Qt support first and falls back to Pillow plus `pillow-heif` when available. If the format cannot be decoded, Atlas shows a clear in-view message such as HEIC support unavailable, file missing, unsupported format, or decode failed, while keeping **Open Folder** and **Open Externally** available.

Fit, Fill, Actual Size, Zoom In, Zoom Out, and Reset Zoom controls keep large images readable while preserving aspect ratio.

Large photo folders are not eagerly rendered on every card, which keeps page filtering and navigation fast.

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

## Information Library

**Information Library** is a searchable, sortable reference browser with a left-side topic tree and a right-side detail page. It collects:

- App help and settings help
- EOAT standardization documents and design guidelines
- Compatibility logic explanation
- Photo and documentation rules
- PM / inspection guidance
- Standards references
- Troubleshooting and support notes
- Reports / export behavior

The library builds an in-memory index at refresh time. It searches title, summary, expanded body text, tags, source filename/path, and tree path without reparsing documents on every keystroke. Each item in the tree opens a detail page with title, category, tree path, summary, expanded explanation, source document/file, source section, tags, related references, indexed/modified dates, **Open Source Document**, **Copy Summary**, and **Copy Full Text / Reference** actions.

DOCX/PDF files are listed with metadata and an open-source button even when lightweight text extraction is unavailable. Markdown and text standards may be split into source-section entries when headings or short sections can be parsed cheaply.

## Main Pages

- **Home / Command Deck**: search, quick actions, source status, project health metrics.
- **What Do I Need?**: guided recommendation, install checklist, and direct full-profile actions.
- **EOAT Search / Profiles**: compact EOAT selector tiles plus structured profile dashboard details.
- **Machine Search / Profiles**: compact machine selector tiles plus compatibility and robot context.
- **Tool / Mold / Part Search**: tool-to-EOAT and tool-to-machine lookup.
- **Compatibility Matrix**: EOAT/machine, tool/EOAT, and tool/machine table views.
- **Overall Maps**: machine grid and documentation heatmap.
- **Photos**: EOAT photo summaries with in-app carousel viewing.
- **Standards**: standard document list and search.
- **PM / Inspection**: generated inspection guidance and missing PM data.
- **Information Library**: tree/detail standards, help, compatibility, photo, PM, settings, and troubleshooting references.
- **Reports / Export**: timestamped CSV/Markdown exports.
- **Settings / Diagnostics**: editable preferences, dark mode, color scheme, source paths, refresh button, and performance timings.

## Known Limitations

- Atlas does not edit source data.
- Standards text extraction is lightweight; DOCX/PDF documents are listed and opened externally.
- Plant-floor map views are grid/coverage views, not a floor-plan drawing.
- Photo thumbnails are session-lazy; Atlas indexes photo paths without generating persistent thumbnail files.
- Recommendation quality depends on clean EOAT IDs, Tool #s, machine fields, and Press Capacity relationships.
