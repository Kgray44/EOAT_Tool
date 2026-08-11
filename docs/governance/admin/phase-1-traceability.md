# EOAT Atlas Admin Phase 1 Traceability

Status definitions: Implemented = source foundation exists; Tested = focused
automated evidence exists; Deferred = intentionally owned by a later phase;
External Dependency = requires approved operational/IT action.

| Requirement group | Phase 1 disposition | Evidence |
| --- | --- | --- |
| ADM-GOV-001 to 005 | Implemented / Deferred UI | Governed route contract and history separation in `phase-1-governance-schema-design.md`; no Phase 2 pages. |
| ADM-NAV-001 to 005 | Deferred to Phase 2 | Frozen route names/access; server `/api/v1/admin` authorization is implemented, browser routes are not. |
| ADM-AUTH-001 to 009 | Partially Implemented / Tested | Explicit Administrator capability map and trusted local server identity; production provider/group remains Phase 5. `tests/server/test_admin_audit_foundation.py`. |
| ADM-HIS-001 to 003 | Implemented | Existing `EntityHistoryEvent` preserved; new `AuditEvent` is distinct. Design record legacy section. |
| ADM-AUD-001 to 010 | Implemented / Tested | `admin/taxonomy.py`, `admin/service.py`, `admin/redaction.py`, `admin/diffing.py`, migrations 0005/0006, focused tests. |
| ADM-IMM-001 to 008 | Implemented / MySQL Tested | No application update/delete paths or routes; correction-by-new-event design. Isolated MySQL runtime role was denied audit `UPDATE` and `DELETE`; production deployment grants remain Phase 6. |
| ADM-SEC-001 to 004, 010 to 017 | Implemented / Deferred | Pre-persistence recursive redaction tests and safe contract handling. HTTPS/CSRF/upload/dependency scanning remain their appropriate existing/later controls. |
| ADM-API-001 to 010 | Implemented / Deferred | Typed `/api/v1/admin` overview/catalog/list/detail contracts, parameterized filtering, role checks; exports/bulk mutations are deferred. |
| ADM-DB-001 to 005 | Implemented / MySQL Tested | Migrations 0005/0006 advanced real MySQL from `20260714_0004` to `20260811_0006`; schema/constraints/indexes were inspected. Explicit downgrade and forward recovery were also exercised on the isolated test schema. |
| ADM-TXN-001 to 003 | Implemented / MySQL Tested | Existing write transaction plus `AuditEventWriter` flush and `execute_with_required_audit`; real MySQL forced-audit FK failure rolled back the business mutation. Transaction ID remains nullable until the database layer exposes one. |
| ADM-TST-001 to 005 | Partially Implemented / MySQL Evidence Added | Focused unit/service coverage and real MySQL migration, privilege, API authorization, redaction, query, and atomicity evidence exist. Full relevant regression execution remains required before final Phase 1 acceptance. |
| ADM-MIG-001 to 005 | Implemented / Deferred deployment evidence | Honest limited-evidence policy documented; no fabricated backfill. Deployment evidence waits for Phase 6. |
| ADM-CHG-001 to 004 | Implemented | This traceability file, taxonomy/versioning policy, and source/test mapping. |

Focused test coverage: closed taxonomy/category mapping, absent/null/empty/redacted diff behavior,
recursive secret suppression, structured event/change serialization, honest
legacy limited-evidence projection, Administrator-versus-Viewer permission
distinction, and deliberate audit-persistence failure rollback.  Migration/database/API integration tests are
environment-gated and must run against the approved `eoat_atlas_test` MySQL
database before any acceptance decision.

## Isolated MySQL acceptance evidence

Real acceptance used EOAT Atlas Debian MySQL 8.4.10 through a temporary SSH
tunnel terminating at remote loopback MySQL. Only `eoat_atlas_test` was
mutated; `eoat_atlas_prod` and `eoat_atlas_dev` were excluded. Dedicated
migration and runtime test identities were test-schema-scoped, with credentials
kept outside Git in a protected local acceptance configuration.

Recorded results: predecessor `20260714_0004`, resulting revision
`20260811_0006`, clean migration and downgrade/forward recovery passed.
Audit schema constraints/indexes/defaults/nullability/version storage were
inspected. Runtime access to protected schemas, schema administration, and
audit update/delete was denied. Application-backed persistence proved
redaction, server actor, UTC timestamp, correlation query, and rollback on a
deliberately failed mandatory audit write. Administrator API integration
returned 401 without identity, 403 for Viewer, and 200 for Administrator. The
temporary test state was restored afterward.

Focused server regression: `tests/server/test_admin_audit_foundation.py` ran
on the disposable Debian test runner with **8 passed** (0.61 seconds), including
the MySQL parent-event flush-order regression check.

Real MySQL foundation regression: `tests/integration/test_mysql_foundation.py`
ran against a clean isolated migration with **6 passed** (0.41 seconds).
