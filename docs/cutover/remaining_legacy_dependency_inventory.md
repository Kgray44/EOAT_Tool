# Remaining Legacy Dependency Inventory

The release candidate keeps legacy mode intact for rollback. Production still defaults to `legacy`; the local rehearsal is the only environment configured for `mysql_api` authority.

| Dependency | Legacy authority | MySQL/API replacement | Cutover handling |
|---|---|---|---|
| EOAT, machine, tool, compatibility, audit, photo metadata | `EOAT_Master_Tracker.xlsx` | normalized MySQL tables and `/api/v1` | Freeze workbook, final checksum import, prohibit legacy writes during the window |
| Robot circuit details | `Robot_Info.xlsx` | `robots`, assignments, audits | Freeze and retain; current file contains no production robot entities to import |
| Tags, notes, annotation targets | `project_data/annotations.sqlite` | annotation/tag tables and API | Freeze, exact-count import, retain read-only rollback copy |
| Photo/document binaries | `01_EOAT_Audit/Cell_Photos` | controlled file paths plus MySQL metadata | Snapshot all referenced binaries; verify file checksums and metadata paths |
| Desktop cache | per-client SQLite | disposable API cache schema 2 | Never authoritative; rebuild from snapshot/change feed |
| Local JSON preferences and recent lists | per-user files | local-only preferences | Retain; exclude from business-data reconciliation |
| Excel synchronization code | application legacy modules | Data Gateway/API | Keep for rollback; do not call it in `mysql_api` mode |

Search and runtime validation found no direct desktop MySQL connection. The supported server-first write groups are assets, compatibility, movement, audits, maintenance, documents/photos, tags, annotations, fit checks, and application instances. Legacy code is deliberately not deleted in Phase 8/9.

Known residual risks are explicit local staging authentication (not a production identity decision), unresolved source ambiguities, and the need for a real human change-freeze announcement at production cutover.
