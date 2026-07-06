# EOAT Atlas Library Optimization Architecture

This note documents the optimized Library path implemented across Phases 1-7. The main rule is simple: Library browsing and record navigation must use cached normalized data only. Workbook reads, photo path scanning, and image decoding must not happen on the UI thread during navigation.

## Data Service And Cache

`core/library_data_service.py` owns the normalized Library index. It loads cached JSON from:

- `00_Project_Admin/cache/library_index.json`
- `00_Project_Admin/cache/library_index_meta.json`

The cache contains EOAT, Tool, and Machine summaries, record detail data, relationship maps, photo metadata maps, documentation status, search text, and source metadata. Source workbook path, modified time, and size are tracked so stale workbooks can be detected.

Warm navigation uses `LibraryDataService` dictionary lookups:

- `get_record`
- `get_record_detail_data`
- `get_relationships`
- `get_photos`
- `get_documentation_status`
- `search`

If the cache is stale, the old cache remains usable while a background rebuild is scheduled. If no cache exists, the Library shell renders with an indexing/skeleton state instead of blocking on workbook parsing.

## Relationship And Record Rendering

The record page uses a reusable `LibraryRecordStateView`. Record open binds cached detail data, renders the hero panel, tabs, overview, relationship panel, and summary metrics immediately, then lazy-builds inactive tabs on first click.

Relationship maps are precomputed during indexing. `RelationshipOverviewPanel` uses custom `QPainter` drawing and hit zones, with `qwidgets_created: 0` for relationship cards. Record navigation must not rebuild relationships from raw workbook rows.

## PhotoService

`core/photos/photo_service.py` resolves cached photo path candidates and decodes images in background workers. It uses `QThreadPool` with bounded concurrency. Worker threads may use `QImageReader` and `QImage`; UI code converts returned `QImage` to `QPixmap` before display.

Memory cache behavior:

- Total budget defaults to about 2 GB.
- Thumbnail budget defaults to about 512 MB.
- Entries are LRU-evicted by decoded image memory cost.

Disk thumbnail cache:

- `00_Project_Admin/cache/photo_thumbnails/`
- cache keys include resolved source path, modified time, and requested size.
- `.webp` is preferred when supported, otherwise an image format supported by Qt is used.

Photo request contexts prevent stale updates:

- `library:...`
- `record:...`
- `photos:...`
- `lightbox:...`

Changing Library page/category/search/filter or record cancels old contexts. Thumbnail callbacks verify the context and photo id before painting.

## UI Thread Rules

Allowed on UI thread:

- cached data dictionary lookup
- widget creation for visible cards only
- `QPixmap.fromImage` after worker decode
- opacity fades and status/toast updates

Not allowed on UI thread during normal navigation:

- Excel/workbook reads
- Photo Index scans
- recursive folder scans
- photo path resolution across slow storage
- image or thumbnail decoding
- full-resolution image loads

Performance warnings must remain active for:

- `excel_read_on_ui_thread`
- `photo_path_resolution_on_ui_thread`
- `image_decode_on_ui_thread`
- `thumbnail_decode_on_ui_thread`

## Library Interaction

The Library browse view renders only the current page slice. It does not create hidden cards for other records or categories. Search is debounced at 125 ms. Pagination, category switches, filter changes, and sort changes cancel stale thumbnail contexts and request thumbnails only for visible cards.

Back to Library restores the previous Library state where possible:

- selected category
- search query
- filters
- sort
- page number

## Loading And Feedback

The Library page should never be blank. It uses skeleton cards when cached records are unavailable. Empty, error, missing photo, cache refresh, thumbnail fade-in, and toast events are logged with `ui.*` performance markers.

PDF export runs in a background thread from the record page. The Export button shows an `Exporting...` busy state and success/failure is reported through non-blocking status/toast feedback.

## Performance Logs And Doctor

Logs are written to:

- `00_Project_Admin/logs/performance.log`
- `00_Project_Admin/logs/performance.jsonl`

Use `core.performance.summarize_library_performance(events)` with events from `read_recent_performance_events(project_root)` to produce a pass/fail summary against Library targets, UI-thread warning counts, and thumbnail cache hit rate.

Relevant tests:

- `tests/test_minimalist_library.py`
- `tests/test_photo_service.py`
- `tests/test_performance.py`
- `tests/core/test_performance_doctor.py`

## Release Guardrails

Before changing Library behavior, verify:

- warm Library open stays under 500 ms
- visible card render stays under 250 ms
- record open stays under 500 ms
- relationship render stays under 150 ms
- Details and Docs & Photos lazy tabs stay under target
- no UI-thread workbook/photo/image warnings appear during navigation
- old thumbnail contexts cannot paint into new cards or records
- Machine current EOAT logic still uses indexed audit evidence and does not guess missing data
