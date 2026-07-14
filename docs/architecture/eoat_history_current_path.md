# EOAT History Current Data Path

Verified on 2026-07-14 for `EOAT_ATLAS_DATA_BACKEND=mysql_api`.

## Active call chain

`RecordWorkspace._ensure_tab(3)` creates `RecordHistoryTab` and supplies `LibraryDataService.get_eoat_history`. That service selects `GatewayEOATHistoryRepository`, which creates `AtlasDataGateway` and calls `get_eoat_history`. The gateway requests the paginated `GET /api/v1/eoats/{identifier}/history` endpoint through `EOATApiClient`; the endpoint resolves the EOAT and calls `AtlasRepository.history_page`; SQLAlchemy queries `entity_history_events` joined to `history_event_types`, `users`, and `application_instances` in MySQL. Returned typed events are normalized by `EOATHistoryService` and rendered by `RecordHistoryTab`.

The SQLite table `cached_eoat_history` is a replaceable API snapshot. It is used only for explicit offline read-only delivery. Deleting it and running Deep Refresh reconstructs it from the API/MySQL snapshot.

## Inventory

| File | Class/function | Purpose | Current data source | Legacy mode | mysql_api mode | Required change/result |
|---|---|---|---|---|---|---|
| `app/atlas/minimalist/library.py` | `RecordWorkspace._ensure_tab`, `RecordHistoryTab` | Creates History tab; async load, filters, selection, details, export | Application service | Legacy widget for non-EOAT records | Yes | Uses approved two-panel typed History UI |
| `core/library_data_service.py` | `LibraryDataService.get_eoat_history` | Profile-facing application service | Configured history provider | Yes | Yes | Verified gateway provider selection |
| `core/eoat_history.py` | `configured_eoat_history_repository` | Backend boundary | Environment configuration | Selects legacy audit JSONL | Selects gateway | Explicit separation retained |
| `core/eoat_history.py` | `GatewayEOATHistoryRepository` | Converts gateway payloads into source records | Data Gateway | No | Yes | Typed MySQL/API path |
| `core/eoat_history.py` | `EOATHistoryService` | Normalize, sort, search/filter, export model | Repository output | Yes | Yes | Structured fields and cache-delivery metadata added |
| `core/data_gateway/gateway.py` | `AtlasDataGateway.get_eoat_history` | Online API retrieval with offline cache fallback | API or disposable cache | No | Yes | Fetches bounded API pages and write-through caches selected EOAT |
| `core/data_gateway/api_client.py` | `EOATApiClient.get_eoat_history` | HTTP operation | EOAT Atlas API | No | Yes | Typed query parameters and URL-quoted identifier |
| `core/data_gateway/cache_repository.py` | `cached_eoat_history` methods | Disposable offline history cache | API snapshot | No | Yes | Cache schema v3; snapshot/rebuild validation |
| `server/eoat_api/app.py` | `eoat_history` | Paginated REST endpoint | Server repository | No | Yes | Typed `PaginatedHistory` response |
| `server/eoat_api/repositories.py` | `AtlasRepository.history_page` | Filtered deterministic history query | MySQL | No | Yes | Pagination, filters, search, stable UUID tie sort |
| `server/eoat_api/repositories.py` | `eoat_history_snapshot` | Bulk Deep Refresh history dataset | MySQL | No | Yes | Bulk join avoids per-EOAT N+1 queries |
| `server/eoat_api/contracts.py` | `HistoryEvent`, `PaginatedHistory` | API serialization contract | Typed server data | No | Yes | Structured source/related/before-after fields |
| `server/eoat_api/database/models.py` | `EntityHistoryEvent`, `HistoryEventType` | Authoritative timeline and stable taxonomy | MySQL | No | Yes | Structured columns, indexes, unique event UUID |
| `server/eoat_api/write_services.py` | `add_history_event`, `audit_change` | Transactional event, audit, and change-feed generation | MySQL transaction | No | Yes | All supported writes emit traceable events |
| `tools/migration/import_pipeline.py` | `execute_import` | Controlled structured-audit import | Read-only workbook to MySQL | Migration only | Migration only | Emits only documented audit history; no inferred locations |
| `server/migrations/versions/20260714_0004_structured_eoat_history.py` | `upgrade` | Schema and existing-audit backfill | MySQL | No | Yes | Initial structured History migration |
| `core/reporting/eoat_history_pdf.py` | `export_eoat_history_pdf` | Complete History report | Typed API/gateway model | Supported by provider | Yes | API/MySQL source label, limitations, multi-page flowables |
| `tests/test_eoat_history.py` | unit/UI/PDF tests | Normalization, state, filtering, PDF | Controlled fixtures only | Test | Test | No fixture is reachable from runtime providers |
| `tests/test_eoat_history_gateway.py` | gateway/cache tests | Mapping and cache rebuild | Controlled adapter | No | Test | Proves cache disposal and recovery |
| `tests/integration/test_mysql_read_conversion.py` | History API/read tests | Live MySQL endpoint/cache behavior | `eoat_atlas_test` | No | Test | 12 passing |
| `tests/integration/test_mysql_write_conversion.py` | History generation tests | Transaction, idempotency, multi-client behavior | `eoat_atlas_test` | No | Test | 16 passing |
| `tools/validation/validate_eoat_history_runtime.py` | runtime validator | Live API/cache/PDF/Excel-isolation proof | Development API/MySQL | No | Validation only | PASS |
| `tools/validation/render_eoat_history_states.py` | screenshot renderer | Visual state coverage | Test fixtures | No | Validation only | Never loaded by production code |

## Legacy paths

`LegacyAuditHistoryRepository` remains available only when the configured backend is `legacy`. No `mysql_api` branch calls it. No routine History, refresh, cache rebuild, or PDF operation opens the workbook or queries legacy SQLite authority. The existing legacy code is intentionally retained for the separate legacy runtime and was not deleted.
