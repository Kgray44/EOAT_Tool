# Current Write Path Inventory

Repository inspection on 2026-07-13 found four persistence families: Excel workbooks, the permanent `project_data/annotations.sqlite` store, local JSON/configuration files, and the new MySQL/API path. The development `mysql_api` conversion below deliberately excludes EOAT Profile page data and UI changes, which are owned by a parallel redesign task.

| Operation | Current UI or tool | Legacy authority/path | New endpoint | MySQL tables | Transaction/audit/concurrency | Status in `mysql_api` |
|---|---|---|---|---|---|---|
| EOAT create/edit/archive/restore | Engineering/profile workflows | Excel master tracker | `POST/PATCH /api/v1/eoats`, archive/restore actions | `eoats` | One transaction; audit, history, feed; row version | API/gateway ready; Profile page UI deferred |
| Machine create/edit/archive/restore | Machine/admin workflows | Excel/reference workbooks | `/api/v1/machines` | `machines` | Same | API/gateway ready |
| Tool create/edit/archive/restore | Tool/admin workflows | Excel/reference workbooks | `/api/v1/tools` | `tools` | Same | API/gateway ready |
| Robot create/edit/archive/restore | Audit/robot utilities | `Robot_Info.xlsx` | `/api/v1/robots` | `robots` | Same | API/gateway ready; audit save no longer writes Robot Info in `mysql_api` |
| Compatibility writes | Fit Check and audit utilities | Excel compatibility sheets | `/api/v1/compatibility/*` | three compatibility tables | FK/date/duplicate validation; row version; audit/feed | API/gateway ready |
| Install/remove/store/unknown | Assignment workflows | Excel fields and inferred current state | install and EOAT move actions | installations/storage/history/audit/feed | Locked operation service; atomic | Ready; no deferred source locations fabricated |
| Audit create/update/complete/archive | Audit page and CLI | EOAT master workbook | `/api/v1/audits` | `audit_records` | Atomic; completed state explicit; row version | Audit UI save routed server-first in `mysql_api` |
| Maintenance/PM | Supported maintenance actions | Mixed workbook records | `/api/v1/maintenance-events` | `maintenance_events` | Atomic; nonnegative downtime; immutable completion | API/gateway ready |
| Document metadata/revision/archive | Document workflows | Files plus workbook metadata | `/api/v1/documents` | `documents`, `document_links` | File must exist before metadata commit; row version | Ready |
| Photo metadata/archive | Photo workflows | Files plus workbook metadata | `/api/v1/photos` | `documents`, `photos`, links | File must exist; document row version | Ready; profile-photo selection excluded |
| Tags/annotations/notes | Audit annotation UI | `project_data/annotations.sqlite` | tags, entity tags, annotations, targets | five annotation/tag tables | Server-first, audit/feed, annotation row version | Migrated and API facade active in `mysql_api` |
| Fit Check history | Fit Check | Previously disabled | `POST /api/v1/fit-checks/evaluate` with `persist=true` | `fit_check_records` | Optional savepoint; valid result survives optional history failure | Ready |
| Application instance | Startup/heartbeat | Local instance UUID | register/heartbeat endpoints | `application_instances` | Upsert by stable UUID | Ready |
| Central settings | Settings pages | Local JSON (user preferences) and legacy workbook settings | Future controlled central-setting endpoints | `system_settings` | Row version required | Schema ready; current local-only preferences intentionally remain local |
| Imports | Migration CLI | Source workbooks/SQLite | Controlled server-side utilities | import tables plus targets | Whole-batch transaction and checksum idempotency | Ready for annotation import; Excel importer retained |
| Exports | Reports/tools | Output files | No authority change | None | Read-only | Remains local export behavior |

Legacy write sites retained for the production `legacy` backend include `core/audit_entries.py`, `core/workbook_repairs.py`, `core/action_items.py`, `core/robot_info.py`, and `core/annotations/service.py`. They were not deleted. In explicit `mysql_api` mode, audit and annotation entry points bypass those authorities and never fall back to them.
