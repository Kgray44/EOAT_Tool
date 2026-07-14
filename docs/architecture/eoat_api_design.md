# EOAT Atlas API Design

The FastAPI service is under `server/eoat_api` and exposes `/api/v1`. Read routes use repositories; write routes use operation-specific services and one request transaction. The desktop never receives MySQL credentials.

Implemented endpoint groups:

- Health, version, schema status, and server status
- Lookups
- Paginated/filterable EOAT, machine, and tool lists/profiles/relationships/history
- EOAT documents and photos
- Typed cross-entity search
- Fit Check evaluation, optional authenticated history, recent history, and alternatives
- Setup Packet authoritative data
- Sync status, change cursor, and full snapshot
- Home summary

Write groups cover assets, compatibility, transactional location moves, audits, maintenance, documents, photo metadata, tags, annotations, application instances, and structured EOAT history. Ordinary operations require no user login. Settings administration uses separate `/api/v1/auth/*` and `/api/v1/settings/*` authorization routes. API version is `1.3.0`; expected schema revision is `20260714_0005`. Errors use `error_code`, `message`, `details`, `request_id`, `timestamp`, `retryable`, and `current_record_version`. Database details and secrets are never returned.

The local development service binds only to `127.0.0.1:8765`. The start script stages server code beside a local Python runtime and enables writes only with `-EnableWrites`. No plant-network exposure or production deployment was introduced. Profile-photo selection is deliberately excluded from this phase.
