# EOAT Atlas Admin Phase 1: Governance and Schema Design Record

Status: Phase 1 implementation record.  No Phase 2 UI work and no production deployment are included.

## Baseline and scope

The actual source checkout has two relevant surfaces: a PySide desktop client
and a FastAPI/MySQL API used by the current web/data-gateway path.  The governed
administrator surface is therefore frozen at the API/database boundary.  It
does not move Home, Library, EOAT/Machine/Tool profiles, Fit Check, or normal
profile History under `/admin`.

Existing reusable foundations are:

- FastAPI request middleware assigns and returns `X-Request-ID`.
- `get_write_session` wraps each server-first write request in one SQLAlchemy
  transaction; write services already flush normalized business state before
  recording legacy change/history evidence.
- `users`, `roles`, and `user_roles` include Viewer, Technician, Engineer, and
  Administrator.  Development/staging identities are isolated from production
  enterprise authentication.
- `ChangeAuditLog` and `EntityHistoryEvent` provide current mutation evidence
  and entity timeline data, respectively.  They remain operational/legacy
  records and are not renamed or overloaded as the global ledger.
- Alembic migrations, SQLAlchemy models, idempotency records, optimistic row
  versions, and domain write services already exist.

The material gaps were a global immutable event model, central taxonomy,
pre-persistence secret redaction, query contracts, explicit administrator
capabilities, and a mandatory-audit failure seam.  Phase 1 adds those without
deleting or fictionalizing existing history.

## Frozen administrator information architecture

The following are governed browser contracts, reserved for later phases:

| Route | Purpose | Access |
| --- | --- | --- |
| `/admin` | Administrative overview | Administrator |
| `/admin/audit` | Global audit ledger | Administrator |
| `/admin/audit/events/:eventId` | Audit-event deep link | Administrator |
| `/admin/data`, `/admin/data/eoats`, `/admin/data/machines`, `/admin/data/tools`, `/admin/data/relationships`, `/admin/data/documents` | Governed data management | Administrator |
| `/admin/access` | Roles, mappings, sessions | Administrator |
| `/admin/system`, `/admin/diagnostics` | System/diagnostic state | Administrator |
| `/admin/settings` | Administrator configuration | Administrator |
| `/admin/danger-zone` | High-risk operations | Administrator plus future safeguards |

No substantial browser page is implemented in Phase 1.  The server namespace
is `/api/v1/admin`.  Its initial read-only contracts are overview, audit
catalog, audit list, and audit-event detail.  Future Data, Access, System,
Diagnostics, Settings, and operations contracts are reserved under that same
namespace; unsafe mutation endpoints are intentionally absent.

## Authorization model

`ADMINISTRATOR` is distinct from authenticated Viewer, Technician, and
Engineer roles.  The central permission map now names administrator capabilities
(`admin.area.view`, `admin.audit.view`, `admin.audit.export`,
`admin.data.manage`, `admin.access.manage`, `admin.system.diagnostics`,
`admin.settings.manage`, and `admin.danger.execute`) rather than relying on
frontend visibility.  `/api/v1/admin/*` independently requires its capability.

The current development/test mapper is an explicit local rehearsal seam only;
it is unavailable outside `development` and `staging_local`.  The future
corporate identity provider and exact administrator AD group remain deliberately
unconfigured.  No group name is encoded in source.

## Audit model and schema versioning

Migration `20260811_0005` creates `audit_events` and `audit_changes`.
`audit_events` is the durable global event record with permanent UUID event ID,
UTC server timestamp, trusted actor snapshot, controlled action/result/source,
entity identity/display ID, diff JSON, note, request/correlation/transaction
metadata, safe metadata, and `schema_version=1`.  `audit_changes` contains one
normalized material field row per event for indexed/controlled future querying.

The ordinary application exposes no update/delete repository, service, or API
for either table.  Corrections must be new events.  The runtime database role
cannot be proven from source alone; a deployment-time least-privilege grant
that denies `UPDATE`/`DELETE` on these tables remains an external operational
hardening item, not a claim made by this phase.

Event schema is additive: writers emit version 1; readers use the stored
version and keep old fields readable.  Future taxonomy/schema changes require
governance review and a new documented version, without rewriting historical
event meaning.

Indexes intentionally target administrator query patterns: time; actor + time;
action + time; entity type/id + time; result; request ID; correlation ID; and
changed field path.  The list repository uses parameterized SQLAlchemy filters,
bounded pagination, and deterministic `occurred_at_utc DESC, event_id DESC`
ordering; it does not accept arbitrary SQL.

## Event, diff, redaction, and transaction semantics

`AuditAction`, `AuditResult`, `AuditActorType`, and `AuditSource` are closed
typed taxonomies.  The taxonomy already covers lifecycle, relationships,
location, documents/photos, maintenance, imports, authentication/authorization,
settings, exports, system/migration, and the staged Danger Zone lifecycle.
Legacy operation labels are mapped centrally rather than preserved as ad hoc
new ledger action names.

`material_diff` compares authoritative pre-write and post-normalization values.
It records only material fields, distinguishes omitted keys from explicit null,
preserves empty string, and represents secret values with a structured
`{"_audit_value":"REDACTED"}` marker.  Redaction recursively denies passwords,
tokens, cookies, credentials, bind/database secrets, and private keys before
objects enter the persistence layer.  API logging receives identifiers and
error classes, never audit payload bodies.

Each existing mutation already runs in `get_write_session`'s transaction.
`audit_change` now calls the central `AuditEventWriter` in that same transaction
and the writer flushes its event/change rows immediately.  An audit persistence
failure therefore propagates and causes the outer business transaction to roll
back; no route may report a successful mutation from that path.  The shared
`execute_with_required_audit` seam provides the same validate/mutate/audit/flush
savepoint pattern for new governed services and is covered by the rollback test.
Request ID is the initial correlation key.  Database transaction IDs are absent
from the current SQLAlchemy/MySQL abstraction and remain nullable rather than
invented.

## Legacy history rules

Existing `EntityHistoryEvent` and domain records are retained as operational
history.  They may later be surfaced only as `legacy / limited-evidence` when
their original actor, timestamp, before/after values, and source can actually be
proven.  Phase 1 performs no false backfill into `audit_events`; the new audit
contract becomes authoritative at migration `20260811_0005` when a future
controlled deployment applies it.  Prior data is not reclassified as equivalent
global forensic evidence.

## Deferred work and nonconformances

- Phase 2 owns administrator browser pages, filter UI, deep-link UI, and
  browser authorization flows.
- Phases 3 and 4 own governed editing, exports, settings/access administration,
  data tooling, diagnostics, and Danger Zone implementation.
- Phase 5 owns approved enterprise identity and actual AD group mapping.
- Phase 6 owns controlled deployment, backup/recovery rehearsal, database-role
  grants, browser/integration/prod acceptance, and the authoritative date of
  the new contract.
- Retention duration, IP retention, exact AD groups, elevated-role policy, and
  emergency audit-failure policy remain governance decisions; none was guessed.
