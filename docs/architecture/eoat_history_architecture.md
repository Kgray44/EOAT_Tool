# EOAT History Architecture

## Authority and boundaries

MySQL `entity_history_events` is the user-visible EOAT timeline authority. Each row has a stable UUID, type, category, occurrence time, actor/application attribution, structured source reference, optional relationship metadata, reason/notes, and before/after values. Important business records remain authoritative in their own structured tables; the history row points back through `source_table` and `source_record_id`.

The desktop never connects to MySQL. It uses the API through the standardized Data Gateway. SQLite `cached_eoat_history` is a disposable read model populated by an API snapshot or selected-EOAT fetch. Online API success replaces that EOAT's cached history; offline mode returns cached rows with explicit `offline_cache` and cache-timestamp metadata.

## Read sequence

1. The EOAT Profile opens `RecordHistoryTab` without blocking the event loop.
2. `LibraryDataService` selects `GatewayEOATHistoryRepository` in `mysql_api` mode.
3. `AtlasDataGateway.get_eoat_history` calls the paginated API and refreshes the selected EOAT cache.
4. `GET /api/v1/eoats/{identifier}/history` resolves the EOAT and queries `AtlasRepository.history_page`.
5. MySQL returns newest-first rows with event UUID as the deterministic timestamp tie-breaker.
6. Typed API fields map through `EOATHistoryService` into the UI and PDF models.

## Refresh sequence

Standard Refresh applies server change-feed records and invalidates/replaces cache state through the existing coordinator. Deep Refresh downloads a bulk snapshot, including `eoat_history`, validates the replacement database, and atomically replaces the disposable cache. The bulk history repository query prevents an EOAT-by-EOAT N+1 pattern.

## Write sequence

Business write, structured source update, user-visible history row, append-only audit row, and change-feed row share the same SQLAlchemy transaction. The idempotency record scopes retries by actor/operation/request key and returns the committed response without emitting a second history row. Any exception rolls the transaction back, leaving no source/audit/change/history orphan.

## Legacy import rule

The controlled importer creates `AUDIT_COMPLETED` events only from normalized `audit_records`, preserving source sheet, row, audit identifier, batch UUID, and checksum provenance. It deliberately does not infer installation, removal, location, or part history from repeated or ambiguous workbook rows.

## Query and performance controls

The public endpoint enforces bounded pages and returns pagination metadata. It filters in SQL by category, mapped public event type, date range, and text across summary, description, reason, notes, actor, type, and structured metadata. The selected EOAT's pages are aggregated only when the client needs the complete set for local interactive filtering and complete PDF export; the global table is never fetched by the profile operation.
