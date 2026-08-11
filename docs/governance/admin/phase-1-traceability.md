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
| ADM-AUD-001 to 010 | Implemented / Tested | `admin/taxonomy.py`, `admin/service.py`, `admin/redaction.py`, `admin/diffing.py`, migration 0005, focused tests. |
| ADM-IMM-001 to 008 | Implemented / External Dependency | No application update/delete paths or routes; correction-by-new-event design. Database-role denial requires approved deployment grant. |
| ADM-SEC-001 to 004, 010 to 017 | Implemented / Deferred | Pre-persistence recursive redaction tests and safe contract handling. HTTPS/CSRF/upload/dependency scanning remain their appropriate existing/later controls. |
| ADM-API-001 to 010 | Implemented / Deferred | Typed `/api/v1/admin` overview/catalog/list/detail contracts, parameterized filtering, role checks; exports/bulk mutations are deferred. |
| ADM-DB-001 to 005 | Implemented / Deferred recovery evidence | Migration 0005, model constraints and indexes. Forward/rollback script exists; controlled real-MySQL execution remains environment-bound. |
| ADM-TXN-001 to 003 | Implemented / Tested | Existing write transaction plus `AuditEventWriter` flush and `execute_with_required_audit`; failure rollback test. Transaction ID remains nullable until the database layer exposes one. |
| ADM-TST-001 to 005 | Partially Implemented | Unit/service coverage added; browser/production acceptance belongs to Phases 2/6. |
| ADM-MIG-001 to 005 | Implemented / Deferred deployment evidence | Honest limited-evidence policy documented; no fabricated backfill. Deployment evidence waits for Phase 6. |
| ADM-CHG-001 to 004 | Implemented | This traceability file, taxonomy/versioning policy, and source/test mapping. |

Focused test coverage: closed taxonomy, absent/null/empty/redacted diff behavior,
recursive secret suppression, structured event/change serialization,
Administrator-versus-Viewer permission distinction, and deliberate audit
persistence failure rollback.  Migration/database/API integration tests are
environment-gated and must run against the approved `eoat_atlas_test` MySQL
database before any acceptance decision.
