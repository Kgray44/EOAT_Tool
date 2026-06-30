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
- Score breakdown with points and evidence
- Documentation score
- Photo count
- Warnings and data gaps
- Install checklist
- Standards references

Recommendation results include direct profile actions. The best recommendation has a prominent **Open EOAT Profile** action plus compact actions for **View Photos**, **Open Related Tool**, **Open Related Machine**, and **Export Recommendation**. Ranked candidates also include compact profile actions so users can jump to the full EOAT, machine, tool, or photo context without rerunning the search.

Ranking favors exact compatibility matches, active/audited status, stronger documentation, linked photos, useful connection data, and fewer warnings.

Use **Why this recommendation?** to expand a point-by-point score breakdown. The panel is collapsed by default and shows **Total Score**, then groups factors into positive bonuses, neutral/middle factors, and penalties/warnings. Each factor shows points added or subtracted, a short explanation, and related evidence. The same breakdown is used for the best recommendation, ranked candidates, copy text, and exported recommendation summaries.

Use **Setup Packet** from the sidebar to build a packet directly. Recommendation, EOAT profile, machine profile, and selected tool actions are shortcuts into the same page with context prefilled.

## Setup Packet Generator

Atlas includes a main sidebar **Setup Packet** page for generating a guided **Setup Packet / Changeover Packet** PDF. The page starts directly with the required setup selection:

- Machine
- Tool / Mold / Part
- EOAT

When opened from another page, Atlas preselects the relevant context without showing a separate starting-context step:

- Machine profile: preselects Machine.
- Tool / Mold / Part page: preselects Tool.
- EOAT profile: preselects EOAT.
- What Do I Need?: preselects the best Machine + Tool + EOAT context when available.

The selector uses the cached Atlas bundle and compatibility indexes. It does not rescan workbooks while the user types. Machine, Tool / Mold / Part, and EOAT lists stay compatibility-filtered by the current selection.

The **Reset Selection** action clears selected Machine, Tool, EOAT, manual override state, and the current compatibility review while preserving packet options and the Packet Library. Smaller clear actions are available for individual Machine, Tool, or EOAT selections.

Incompatible or unconfirmed choices are blocked by normal input. The page includes an explicit **Allow incompatible / unconfirmed selection** action. It shows a warning that the combination is not confirmed by Atlas data and requires confirmation before all records become selectable. When used, the page and PDF are clearly marked **Manual Override Used** / **Compatibility Not Confirmed**.

The compatibility review shows selected Machine, Tool / Mold / Part, EOAT, compatibility status, manual override status, robot info availability, EOAT documentation score, photo count, warning count, missing key data, packet type, and photo inclusion.

Compatibility statuses are:

- **Confirmed**: Machine + Tool + EOAT links are all supported by available compatibility/index data.
- **Partially Confirmed**: some links are confirmed, but a supporting source is missing or incomplete.
- **Not Confirmed**: Atlas does not find compatibility for the selected combination.
- **Missing Data**: Atlas cannot fully validate because one or more required records or fields are missing.
- **Manual Override Used**: the user explicitly allowed an incompatible or unconfirmed selection.

Packet types:

- **Standard Changeover Packet**: default and most complete. Includes setup summary, compatibility, machine, robot, tool, EOAT, pneumatics/sensors, changeover checklist, documentation checklist, photos, standards, warnings, and source summary.
- **Setup Verification Packet**: focuses on verifying the selected Machine + Tool + EOAT combination, robot/setup details, warnings, and a short verification checklist.
- **Maintenance / PM Packet**: focuses on EOAT inspection, machine/robot context, pneumatic/gripper/vacuum/sensor checks, PM checklist, photos, standards, warnings, and notes.
- **Documentation Review Packet**: focuses on documentation score, missing fields, photo coverage, source references, standards, warnings, and the documentation checklist.

Photo inclusion options:

- **No photos**: the PDF lists the photo folder/path, count, missing categories, and a note that photos are available in Atlas/folders.
- **Key photos only**: default. Atlas prioritizes overall, mounting/connection, tubing routing, gripper/vacuum cup, sensor, and quick-disconnect style photos.
- **All photos**: every available photo is included, with one photo per page, large and centered.

If a photo cannot be loaded, the PDF includes a clear placeholder note with the path.

Generated PDFs are timestamped, never overwritten, and saved under:

```text
06_Final_Handoff/Atlas_Exports/Setup_Packets/
```

The Setup Packet page has packet-specific options for default packet type, photo inclusion, open behavior after generation, QR label inclusion when QR Codes are enabled, detail level, and manual override availability. These settings persist per user and are stored outside source workbooks. Changing these packet options is a local, lightweight update: Atlas does not refresh workbooks, rescan photos, rebuild the packet library, or move the page scroll position just because an option changed.

If global QR Codes are disabled in Settings, the Setup Packet **Include QR label** option is disabled and explains that QR Codes must be enabled first. When global QR Codes are enabled, the checkbox is selectable and only affects future packet generation.

The right side of the page is a **Packet Library** with:

- **Latest Packet**: clean metadata for the most recently generated or viewed packet, led by Machine, Tool, and EOAT rather than the raw filename. It shows packet type, compatibility, generated time, file size, photo inclusion, manual override status when relevant, a muted filename, and actions for **View**, **Open**, **Folder**, and **Copy Path**.
- **Previous Packets**: recent PDFs from the Setup Packet export folder, newest first, shown as compact document rows/cards with parsed Machine, Tool, EOAT, packet type, compatibility, generated time, file size, and actions for **View**, **Open**, and **Folder**.

Atlas writes an optional `.json` sidecar next to newly generated PDFs with packet metadata. Older PDFs still appear in the library by parsing the timestamped filename and using file modified time when needed.

**View** opens a large Atlas PDF viewer modal using QtPdf when available. The viewer is PDF-first: a compact toolbar sits at the top, a narrow metadata/actions sidebar lists the setup details, and the PDF canvas receives the remaining space with fit-width as the default. The viewer includes page navigation, page count, zoom in/out, fit width, fit page, Print, Open, Folder, Copy Path, and Close controls. If embedded PDF support is unavailable in a local build, Atlas detects that dynamically and shows a clean fallback message while keeping Open, Folder, and Copy Path available.

After generation, Atlas sets the PDF as Latest Packet, refreshes Previous Packets, and follows the selected open behavior: view in app, open externally, open folder, or ask each time with **View In App**, **Open PDF**, **Open Folder**, and **Stay Here** choices.

Setup Packets are read-only exports. They do not modify source workbooks or photo folders.

## Compare Mode

EOAT, machine, and tool selectors include a subtle **Compare** checkbox. When two or more comparable items are selected, Atlas shows a small **Compare Selected** bar with the selected count and a clear action.

The compare view opens as a themed Atlas dialog, not a raw table. It has a title, selected-record chips, summary counts for same fields, different fields, warning differences, and compatibility differences, then grouped comparison sections. Difference badges show **Same**, **Different**, **Missing**, or **Warning**. Long values wrap in the dialog, and copy/export/open actions are available without changing source data.

Compare supports:

- EOAT vs EOAT: identity, type/status, compatible tools/machines, documentation, photos, missing photo categories, warnings, robot/setup fields, known issues, and standards.
- Machine vs Machine: machine number, robot context, compatible EOATs/tools, documentation, warnings, and current EOAT context.
- Tool vs Tool: tool number, part description, compatible EOATs/machines, source, and warnings.

Selections can be cleared without changing source data.

## Recent And Pinned Items

Atlas tracks recently viewed EOATs, machines, and tools as IDs/keys in user settings. EOAT and machine profiles include a compact **Pin / Unpin** action.

When the EOAT or machine search box is empty, Atlas orders list sections as **Pinned**, **Recently Viewed**, then **All**. Duplicates are removed between sections. As soon as the user types a search query, normal search relevance takes priority and pinned/recent priority is ignored.

Tool / Mold / Part Search now uses a library/detail layout. The left side is a searchable grouped navigation list for all tools, machine groupings, EOAT link status, warning status, source, and recently viewed tools when practical. Each tool row shows the tool number, part description, machine count, EOAT link status, warning count, and a compare checkbox. The right side shows the selected tool detail page with compatible EOATs, compatible machines, a **Tool -> EOAT -> Machine** relationship map, warnings/actions, source metadata, and actions for **Run What Do I Need?**, opening linked EOAT/machine profiles, compare selection, exporting a tool summary, and launching **Setup Packet** for the selected tool context.

Settings includes **Hide tools missing EOAT links**. When enabled, Tool / Mold / Part Search hides tools that have no compatible/linked EOAT, search respects the filter, compare selection ignores hidden tools, and the page shows a visible **Hiding tools missing EOAT links** filter chip. The Tool page also has a quick toggle so users can show missing-link tools again when investigating data cleanup.

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
- Photo indexing records file paths only; the Photos page uses a tree/detail library and loads images only when the in-app carousel is opened.
- Photo decoding runs through an async loader with a small worker pool, a configurable session LRU cache budget, and idle-aware preloading for current/next/previous carousel images, remaining open photo-set images, visible photo-library entries, related recommendation/profile photos, and in Aggressive mode other EOAT photo sets until the cache budget is reached. Idle preloading is locked while the startup loading screen is visible and starts only after Atlas has loaded data, revealed the main window, and waited briefly for the UI to become usable. Background preloads pause when Atlas is inactive, pause/drop queued work as soon as the user interacts with the app, avoid UI-thread network file probes, and keep worker capacity available for user-requested image opens.
- When the photo cache is full, Atlas stops queueing additional preload jobs and reports **Photo cache full. Additional photos will not be queued until cache space is available.** Clearing the cache or increasing the cache limit allows photo loading to resume. Source photos are never deleted.
- Search and recommendation use normalized lookup keys.
- Manual **Refresh Data** is available on Settings / Diagnostics.
- The last refreshed timestamp is shown in the status bar and dashboard.

Diagnostics on Settings / Diagnostics include workbook load time, photo index time, cache build time, bundle counts, preload mode, cache status, idle status, event-loop lag, queued/active photo jobs, decoded image totals, thumbnail/full image counts, cache memory and limit, last preload reason, last completed preload file, last decode time, failed loads, **Clear Photo Cache**, and **Prime Photo Cache**.

## Settings And Dark Mode

Settings / Diagnostics includes editable Atlas preferences that persist per user in the app config folder, not in source workbooks. Current settings include:

- Light, Dark, or System/default theme
- Color scheme: Atlas Blue, Nolato Logo, Industrial Graphite, or Aurora Tech
- Default startup page
- Default search mode
- Photo viewer behavior: in-app carousel, open folder, or external viewer
- Photo preload mode: Off, Conservative, Balanced, or Aggressive
- Photo cache controls, including cache stats, cache limit, cache-full status, and a clear-cache action
- Lazy photo preview and carousel prefetch options
- Advanced diagnostics visibility
- Compact or comfortable list/card density
- Hide tools missing EOAT links
- Export and external-open behavior
- Auto-refresh data on startup
- Enable QR Codes
- QR payload mode: Compact Human-Readable Text, Atlas Deep Link, JSON Record, or Full Offline Record
- QR error correction: Low, Medium, Quartile, or High
- QR default label size: Small, Medium, or Large
- Show payload preview before export
- Phone-number-like QR payload guard, always enabled unless debug builds explicitly override it
- Command palette enabled

Setup Packet-specific options live on the **Setup Packet** page rather than Settings / Diagnostics.

Theme and color scheme changes apply immediately. Atlas defaults to light mode with Atlas Blue unless the user changes it. The Nolato Logo color scheme uses controlled red accents, charcoal anchors, and neutral surfaces. Industrial Graphite uses graphite, steel blue, cyan, and safety amber for a manufacturing-floor dashboard feel. Aurora Tech uses navy, electric blue, teal, and subtle indigo accents for a more navigation-inspired Atlas look. Each color scheme supports light and dark mode through the same design tokens.

## QR Codes And Labels

QR Codes are disabled by default. When **Enable QR Codes** is on, EOAT profiles show a small **Make QR** action. When disabled, the button is hidden.

QR payloads are scan-safe and must not look like phone numbers:

- **Compact Human-Readable Text**: default mode for printed labels. It starts with `EOAT_ATLAS_RECORD`, includes `EOAT=<id>` before any tool value, prefixes tools as `T-5620040010`, prefixes machines as `M-1`, and includes type, status, documentation, photo count, warning count, and generated date. It is never just a tool number.
- **Atlas Deep Link**: future app-integration mode such as `eoat-atlas://record/eoat/P4-EOAT-0001?tool=T-5620040010`. Phone scanners may not open it without an installed app, but it should not be interpreted as a phone call.
- **JSON Record**: compact structured JSON with `app`, `record_type`, EOAT ID, prefixed tools, prefixed machines, EOAT type/status, docs, photos, and warnings.
- **Full Offline Record**: full text record with setup notes, vacuum/pressure, tubing, gripper, sensors, known issues, standards, and PM/reference details. It is optional and warns clearly about payload size.

Before generation, Atlas validates that the payload is not empty, is not numeric-only or phone-number-like, does not start with a digit, does not start with `tel:` or `call:`, and that compact mode starts with `EOAT_ATLAS_RECORD`, includes EOAT ID, and uses `T-` tool prefixes instead of raw numeric tool values. After the label PNG is generated, Atlas decodes the generated QR image and verifies the decoded payload exactly matches the preview text. Large payload warnings include payload length, error correction level, and a recommended minimum printed QR size. For small printed labels, Atlas recommends Compact Human-Readable Text or Atlas Deep Link.

Generated labels include both the QR code and human-readable text: EOAT ID, main tool numbers, compatible machines, EOAT type, docs/photos/warnings, payload mode, generated date, recommended size guidance, and a short scan instruction. PNG labels are saved safely under:

```text
06_Final_Handoff/Atlas_Exports/QR_Labels/
```

The preview shows the exact payload text that will be encoded and includes **Save / Export**, **Open Folder**, **Copy QR Payload**, **Decode Generated QR**, and **Close** actions. Files are timestamped and never overwrite existing labels.

If a phone scanner shows `call: <tool number>`, the generated QR is unsafe or stale. Regenerate the label with Compact Human-Readable Text and confirm the preview starts with `EOAT_ATLAS_RECORD`. Use **Decode Generated QR** to verify the saved PNG decodes to the same payload shown in the preview.

## Dialog And Popup Styling

Atlas dialogs and popups use the same theme tokens as the main window. QMessageBox warnings, QR warnings, export confirmations, photo errors, unsupported image messages, settings warnings, compare dialogs, and setup packet dialogs should have readable text, visible buttons, consistent padding, and theme-safe warning accents. Dark mode must avoid black-on-black table or dialog styling; light mode must avoid inherited dark backgrounds with dark text.

## Command Palette

Press **Ctrl+K** to open the Atlas command palette. It searches cached Atlas data only, so it does not rescan workbooks on every keystroke.

The palette supports page navigation, EOAT/machine/tool lookup, recent and pinned items, opening What Do I Need?, **Generate Setup Packet** for the current context, opening Settings, toggling dark mode, refreshing data, opening Standards and Information Library, compare commands, and Make QR for the current EOAT when QR Codes are enabled.

Use Up/Down to move, Enter to run, and Escape to close.

## Relationship Maps

EOAT, machine, and tool profiles/cards include compact relationship maps. They show simple flows such as **Tool -> EOAT -> Machine**, **Machine -> EOATs -> Tools**, and **Tool -> EOATs -> Machines** with small evidence nodes for robot info, photos, and standards.

Large lists are summarized with `+N more` chips. Missing links are shown as warning nodes. The map complements the Compatibility Matrix; it is not a full-screen graph editor.

## Photo Viewer

The Photos page uses an Information Library-style layout. The top area has search and optional filters for all EOATs, photo status, missing folder, missing categories, tool, machine, and photo category. The left side is a tree with **All EOAT Photo Sets**, **By Photo Status**, **By Tool**, **By Machine**, and **By Category Coverage**. Selecting an EOAT opens a stable detail page on the right with the EOAT ID, tool chips, machine chips, photo count, folder found/missing status, missing category chips, shortened folder path with tooltip, action buttons, and a category checklist.

**View Photos** opens a resizable in-app carousel/gallery. The top bar shows EOAT ID, filename/category, photo count, a compact view menu, optional maximize/restore, and close. The main image is centered on a dark stage and scales smoothly while preserving aspect ratio. The bottom filmstrip shows clickable thumbnails; the selected thumbnail is larger with an accent border/glow and nearby thumbnails are slightly smaller. Clicking a thumbnail changes the main image with a short fade transition. Left/right arrow keys navigate, mouse wheel over the filmstrip moves through photos, double-clicking the main image toggles fit/actual size, and Escape closes the viewer.

The viewer supports `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, and `.heif` when the local Qt/Pillow decoders can read them. HEIC/HEIF preview uses Qt support first and falls back to Pillow plus `pillow-heif` when available. If the format cannot be decoded, Atlas shows a clear in-view message such as HEIC support unavailable, file missing, unsupported format, or decode failed, while keeping **Open Folder** and **Open Externally** available.

Clicking **View Photos** opens the carousel immediately. The current image decodes in a background worker and shows a loading/failure state in the viewer instead of freezing the Atlas window. Carousel thumbnails and selected images load through the same worker pool. When carousel prefetch is enabled, Atlas queues previous/next full-size image loads first and then remaining images in the open EOAT photo set. Low-priority preload work backs off when recent interaction or event-loop lag suggests the UI is busy.

Fit, Fill, Actual Size, Zoom In, Zoom Out, and Reset Zoom controls keep large images readable while preserving aspect ratio.

Large photo folders are not eagerly rendered on the library page, which keeps filtering and navigation fast. Optional previews should only use already-cached images. Settings / Diagnostics exposes photo preload mode, cache statistics, failed-load counts, and a clear-cache button for troubleshooting.

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

**Information Library** is a searchable, sortable reference browser with a left-side topic tree and a right-side detail page. The tree groups entries as category -> subcategory/source -> item and collapses duplicate consecutive labels so pages such as **EOAT Profiles** or **Compatibility Matrix** do not repeat as parent and child. It collects:

- App help and settings help
- EOAT standardization documents and design guidelines
- Compatibility logic explanation
- Photo and documentation rules
- PM / inspection guidance
- Standards references
- Troubleshooting and support notes
- Reports / export behavior

The library builds an in-memory index at refresh time. It searches title, summary, expanded body text, tags, source filename/path, and tree path without reparsing documents on every keystroke. Each item in the tree opens a detail page with title, category, tree path, summary, expanded explanation, source document/file, source section, tags, related references, indexed/modified dates, **Open Source Document**, **Copy Summary**, and **Copy Full Text / Reference** actions.

Detail pages use structured mini-reference sections instead of one-line placeholder summaries. App-help entries explain what the page does, when to use it, how to use it, what results mean, related actions, and troubleshooting notes. Standard-derived entries explain the standard/rule, what it means, why it matters, what to check in the EOAT audit, related fields/pages, common warning signs, and source. Warning/gap entries show the issue, why it matters, suggested fix, related standard/source, and related Atlas page.

DOCX/PDF files are listed with metadata and an open-source button even when lightweight text extraction is unavailable. Markdown and text standards may be split into source-section entries when headings or short sections can be parsed cheaply.

## Main Pages

- **Home / Command Deck**: search, quick actions, source status, project health metrics.
- **What Do I Need?**: guided recommendation, install checklist, and direct full-profile actions.
- **Setup Packet**: guided Machine + Tool / Mold / Part + EOAT selection, compatibility-safe PDF generation, packet options, Packet Library, and in-app PDF viewing.
- **EOAT Search / Profiles**: compact EOAT selector tiles plus structured profile dashboard details.
- **Machine Search / Profiles**: compact machine selector tiles plus compatibility and robot context.
- **Tool / Mold / Part Search**: library/detail tool-to-EOAT and tool-to-machine lookup with compare selection.
- **Compatibility Matrix**: EOAT/machine, tool/EOAT, and tool/machine table views.
- **Overall Maps**: machine grid and documentation heatmap.
- **Photos**: EOAT photo tree/detail library with in-app carousel viewing.
- **Standards**: standard document list and search.
- **PM / Inspection**: generated inspection guidance and missing PM data.
- **Information Library**: tree/detail standards, help, compatibility, photo, PM, settings, and troubleshooting references.
- **Reports / Export**: timestamped CSV/Markdown exports.
- **Settings / Diagnostics**: editable preferences, dark mode, color scheme, source paths, refresh button, and performance timings.

## Known Limitations

- Atlas does not edit source data.
- Smart Missing Data Assistant is not implemented yet.
- Confidence / Data Quality Mode is not implemented yet.
- Standards text extraction is lightweight; DOCX/PDF documents are listed and opened externally.
- Plant-floor map views are grid/coverage views, not a floor-plan drawing.
- Photo thumbnails are session-lazy; Atlas indexes photo paths without generating persistent thumbnail files.
- Recommendation quality depends on clean EOAT IDs, Tool #s, machine fields, and Press Capacity relationships.
