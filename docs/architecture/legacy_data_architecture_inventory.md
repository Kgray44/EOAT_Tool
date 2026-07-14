# Legacy EOAT Atlas Data Architecture Inventory

## Scope and active roots

- Inspected source checkout: `KG_Nolato_Summer_2026` on branch `feature/eoat-atlas`, application version `0.1.0`.
- Active runtime project root from `config/local_config.json`: `EOAT_Standardization_Project`.
- Active master workbook: `01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx`.
- Supporting sources: `Robot_Info.xlsx`, `00_Project_Admin/reference_data/master_press_list.xlsx`, and `press_capacity.xlsx`.
- SQLite file: `project_data/annotations.sqlite`; this contains annotation/note state, not an EOAT cache.
- The architecture PDF names a separate `KG_Nolato_Summer_2026_Globalized_Development` path. That is not the Git root or configured project root inspected in this execution.

No legacy module was removed or disabled in this phase.

## Current data flow

```text
PySide6 pages/controllers
  -> feature-specific core services
  -> direct openpyxl reads/writes and workbook cache helpers
  -> EOAT_Master_Tracker.xlsx / Robot_Info.xlsx / reference workbooks

Annotation UI/services
  -> sqlite3 repository
  -> project_data/annotations.sqlite

Atlas UI refresh
  -> core.atlas_data_loader
  -> workbook readers + filesystem/photo/document indexers
  -> in-process AtlasDataBundle and indexes
```

The current implementation is not a queued Excel/SQLite synchronization engine. It is an Excel-authoritative application with direct feature-level workbook access, in-process caching, file modification checks, workbook backups/locks, and a separate authoritative SQLite annotation store.

## Component inventory

| Legacy component | Purpose | Called by | Data affected | Planned replacement | Removal status |
|---|---|---|---|---|---|
| `core.paths.EOATProjectPaths` | Resolves master/robot/reference workbook and annotation DB paths | Nearly all services | All legacy sources | Environment-aware gateway/server configuration | Retained; no behavior change |
| `core.workbook_io` | Generic openpyxl row reads and safe workbook access | Analysis, validation, reporting, services | All workbook sheets | Explicit migration import/export only after cutover | Retained |
| `core.workbook_cache` | Caches workbook rows keyed by source state | Workbook consumers | Read snapshots | Disposable SQLite/API cache later | Retained |
| `core.snapshots` | Builds and refreshes workbook snapshots | Dashboard and event bus | Workbook-derived summaries | API snapshot and change cursor | Retained |
| `core.workbook_truth` | Interprets workbook rows as current truth | Audit and validation workflows | EOAT Inventory | Server repositories/services | Retained |
| `core.workbook_locks` | Detects Excel lock files/write availability | Health checks and write flows | Master workbook | API transaction/concurrency controls | Retained |
| `core.workbook_repairs` | Backs up and repairs sheet/schema content | Workbook health/settings | Workbook schema and cells | Alembic plus administrator import validation | Retained |
| `core.atlas_data_loader` | Loads workbook/photo/reference data into `AtlasDataBundle`; caches by fingerprints | Atlas window startup/refresh | EOAT, machines, tools, photos, standards | Client Data Gateway (later phase) | Retained |
| `core.atlas_models` | UI-facing workbook-derived records and indexes | Atlas pages/search/Fit Check | EOAT, machine, tool, compatibility | Domain/API response models (later conversion) | Retained |
| `core.audit_entries`, `core.audit.completion` | Creates/updates EOAT Inventory audit rows | Audit UI | EOAT Inventory | API audit service/transaction | Retained |
| `core.audit_context`, `core.audit_compatibility`, `core.audit_by_press` | Enriches audits and writes compatibility/view rows | Audit pages and reports | EOAT Inventory, Audit by Press | Normalized asset/compatibility/audit tables | Retained |
| `core.action_items`, `core.interview_entries`, `core.fmea_suggestions` | Feature-level workbook reads/writes | Corresponding pages/tools | Action Items, Interview Notes, FMEA Draft | Server feature repositories (future phases) | Retained |
| `core.robot_info` | Reads/writes robot workbook derived from audits | Audit and Atlas loaders | Robot_Info.xlsx | `robots` and `machine_robot_assignments` | Retained |
| `core.press_lookup` | Reads press-list/capacity workbooks | Audit defaults, Fit Check, Atlas | Machine/reference data | `machines`, compatibility evidence | Retained |
| `core.photo_indexing`, `core.photo_evidence` | Writes photo metadata and links into workbook | Photo intake/audit | Photo Index and files | `documents`, `photos`, `document_links` | Retained |
| `core.data_import` | Explicit workbook/CSV import workflow | Data Import page | Workbook sheets | Administrator migration/import service | Retained |
| `core.eoat_ids`, `core.eoat_id_migration` | Identifier creation/repair across workbook and files | Admin tooling | IDs, photos, cached references | Server identifier policy/migration tool | Retained |
| `core.annotations.database`, `migrations`, `service` | Owns SQLite schema and annotation CRUD | Notes/tags/open-items UI | annotations.sqlite | Must be mapped into later server annotation tables; not silently discarded | Retained |
| `core.app_health`, workbook-health UI | Reports workbook existence, lock and dependency status | Diagnostics/settings | Paths/locks/counts | API/database/schema/cache health later | Retained |
| `app.atlas.atlas_window.refresh_data` | Starts background workbook reload | Atlas UI | In-process bundle | Gateway incremental refresh later | Retained |
| `app.dashboard_ui` + event bus | Invalidates/reloads workbook snapshots after writes | Command Center pages | Workbook-derived page data | Gateway change application later | Retained |
| `requirements.txt` openpyxl/pandas | Supports live operational Excel behavior | Packaging/runtime | Workbook I/O | Retain until explicit import/export is isolated | Retained |
| PyInstaller specs/build scripts | Bundle Excel/runtime dependencies | Packaging | Installer content | Cleanup only after full cutover | Retained |

## Operational openpyxl surface

Direct openpyxl imports were found in: `core/action_items.py`, `core/annotations/exports.py`, `core/annotations/service.py`, `core/audit/tool_lookup.py`, `core/audit_by_press.py`, `core/audit_compatibility.py`, `core/audit_context.py`, `core/audit_entries.py`, `core/compatibility_health.py`, `core/data_import.py`, `core/eoat_id_migration.py`, `core/eoat_ids.py`, `core/fmea_suggestions.py`, `core/interview_entries.py`, `core/photo_evidence.py`, `core/photo_indexing.py`, `core/press_lookup.py`, `core/robot_info.py`, `core/snapshots.py`, `core/validation.py`, `core/workbook_io.py`, and `core/workbook_repairs.py`.

## Legacy mechanism search results

| Mechanism requested by specification | Finding |
|---|---|
| Workbook polling/file watcher | No dedicated watcher or polling daemon found. Refresh is user/startup/event driven and uses file fingerprints/mtime. |
| Pending Excel write queue | No operational queue found. Writes are synchronous feature-level operations. |
| Failed-write retry queue | No retry queue found. Errors are returned/logged by the calling workflow. |
| SQLite-to-Excel synchronization | No general sync engine found. Annotation export is explicit and feature-specific. |
| Excel-to-SQLite synchronization | No EOAT cache import found. SQLite is annotation storage only. |
| Background synchronization worker/timer | Background UI tasks refresh workbook-derived data, but no permanent bidirectional sync loop was found. |
| Excel conflict resolution | Workbook lock checks/backups exist; no record-level merge/conflict engine exists. |
| Startup workbook loading | Present in both Atlas and Command Center flows. |
| Shutdown synchronization | No generalized shutdown sync found. |
| Deep Refresh | UI commands force workbook/cache recomputation; terminology does not yet mean a server cache rebuild. |

## Test and documentation dependencies

The test suite contains extensive workbook fixtures and tests for audit writes, workbook truth/repair/cache/locks, Atlas loading/search/Fit Check, photos, validation, and annotations. Existing documentation still describes the workbook as the operational source. These tests and documents remain valid legacy comparison evidence and must not be deleted until later read/write cutover validation.

## First-phase disposition

- Legacy reads and writes remain active.
- No production deployment or configured project source was modified.
- No workbook was modified by the dry-run importer (SHA-256 and file metadata were rechecked).
- New domain/database code is additive and is not wired into UI data access in this phase.

