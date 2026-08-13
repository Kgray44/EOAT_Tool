# EOAT Atlas Admin Phase 3: Governed Mutation Registry

Status: active. Every listed operation is implemented only through a typed
Admin API, a server-side session actor, capability authorization, canonical
domain validation, atomic mandatory audit persistence, and a structured
success/failure contract.

| Operation | Route | Capability | Editable scope / controls | Audit | Retry and test evidence |
| --- | --- | --- | --- | --- | --- |
| `admin.eoat.update` | `PATCH /api/v1/admin/data/eoats/{identifier}` | `admin.eoat.edit` | Allowlisted EOAT business fields; immutable identity/system fields denied; expected version; optional reason | `UPDATE`, or `CORRECTION` when correction reason supplied | Idempotent key; API/MySQL/browser/forgery/CSRF/conflict tests |
| `admin.machine.update` | `PATCH /api/v1/admin/data/machines/{identifier}` | `admin.machine.edit` | Allowlisted Machine business fields; authoritative plant/area/lookup validation; expected version | `UPDATE` or `CORRECTION` | Idempotent key; API/MySQL/browser tests |
| `admin.tool.update` | `PATCH /api/v1/admin/data/tools/{identifier}` | `admin.tool.edit` | Allowlisted Tool business fields and status lookup; expected version | `UPDATE` or `CORRECTION` | Idempotent key; API/MySQL/browser tests |
| `admin.asset.lifecycle` | `POST /api/v1/admin/data/{kind}/{identifier}/archive|restore` | `admin.asset.archive` | Exact target, expected version, required reason and confirmation; existing domain constraints | `ARCHIVE` / `RESTORE` | Idempotent key; valid/invalid lifecycle tests |
| `admin.relationship.link` | `POST /api/v1/admin/data/relationships/{kind}` | `admin.relationship.manage` | Authoritative EOAT/Machine/Tool selectors and a server-backed compatibility-status selector; duplicate and compatibility validation | `LINK` | Idempotent key; real-MySQL selector/duplicate/rejection/unlink tests and real browser LINK evidence |
| `admin.relationship.unlink` | `POST /api/v1/admin/data/relationships/{kind}/{id}/unlink` | `admin.relationship.manage` | Existing relationship, expected version, required reason and confirmation | `UNLINK` | Idempotent key; stale/unlink tests |
| `admin.document.metadata` | `PATCH /api/v1/admin/documents/{id}` | `admin.document.manage` | Safe metadata fields only; no raw storage path, checksum, physical delete, or association reassignment | `METADATA_CHANGE` | Idempotent key; redaction/path tests |
| `admin.document.lifecycle` | `POST /api/v1/admin/documents/{id}/archive` | `admin.document.manage` | Reversible archive semantics, expected version, required reason and confirmation | `ARCHIVE` | Idempotent key; history tests |
| `admin.photo.metadata` | `PATCH /api/v1/admin/photos/{id}` | `admin.document.manage` | Safe photo/document metadata only; binary location and file internals denied | `METADATA_CHANGE` | Idempotent key; redaction/path tests |
| `admin.photo.lifecycle` | `POST /api/v1/admin/photos/{id}/archive` | `admin.document.manage` | Reversible archive semantics, expected version, required reason and confirmation | `PHOTO_ARCHIVE` | Idempotent key; history tests |
| `admin.eoat.bulk-status` | `POST /api/v1/admin/data/eoats/bulk-status/preview|commit` | `admin.bulk.execute` | Explicit EOAT identifiers, one status, versions, preview, typed confirmation | `BULK_OPERATION` parent plus correlated `STATUS_CHANGE` children | Idempotency key; dry-run/atomic rollback/retry tests |
| `admin.setting.update` | `PATCH /api/v1/admin/settings/{key}` | `admin.settings.edit` | Existing persisted `SystemSetting` key only, server-declared type, secret write-only behavior | `SETTINGS_CHANGE` | Idempotent key; secret containment tests |
| `admin.access.mapping` | `PATCH /api/v1/admin/access/test-mappings/{identity}` | `admin.access.manage` | Configured development/test identities only and role selector; no corporate groups | `ROLE_MAPPING_CHANGE` | Idempotent key; invalid/unauthorized tests |
| `admin.session.revoke` | `POST /api/v1/admin/access/sessions/{id}/revoke` | `admin.session.manage` | Phase 3 local rehearsal sessions only; confirmation | `SESSION_REVOKED` | Idempotent key; revoked-session test |

All failure responses use the Phase 1/2 safe error envelope: controlled error
code, safe message, request ID, and field errors where applicable. Audit
persistence failure is never represented as success; the transaction rolls
back. No registry entry permits audit-ledger mutation.
