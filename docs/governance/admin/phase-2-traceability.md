# EOAT Atlas Admin Phase 2 Traceability

Status: living implementation traceability.  `Implemented` means the stated
read-only behavior is present in the Phase 2 branch; it does not imply the
Phase 2 acceptance decision has been made.

| Governing requirement | Phase 2 disposition | Implementation and evidence |
| --- | --- | --- |
| ADM-GOV-001 to 004 | Implemented | `web/src/app/AdminApp.tsx` owns the isolated `/admin` area while preserving normal-profile links; `web/src/styles/admin.css` uses the EOAT Atlas visual vocabulary. |
| ADM-NAV-001 to 004 | Implemented | Server `require_admin` guards all Admin API contracts in `server/eoat_api/admin/routes.py`; real React routes use browser URL state. Focused negative authorization test: `tests/server/test_admin_phase2_readonly.py`. |
| ADM-AUTH-003, 008 | Implemented | Existing Phase 1 `read_actor_context` and `require_admin` remain authoritative. The browser does not derive an Administrator role. Corporate identity is Deferred to Phase 5. |
| ADM-HIS-001 to 003 | Tested | The ledger uses only `AuditEvent`; browser acceptance proves EOAT, Machine, and Tool detail links leave the Admin ledger for canonical normal profiles without exposing global Admin evidence through normal History. |
| ADM-AUD-001 to 010 / ADM-IMM-001 to 004 | Implemented | Phase 1 immutable event writer and repository remain unchanged; Phase 2 adds only GET contracts and no audit mutation endpoint or control. Existing foundation test plus source review protect this boundary. |
| ADM-SEC-001 to 004 | Implemented | API contracts return Phase 1-redacted fields; `AuditDiff` shows the redacted marker and never attempts recovery. Export is Deferred to Phase 4. |
| ADM-OVR-001 to 004 | Implemented | `/api/v1/admin/overview` uses `AuditEventRepository.overview` for bounded server-derived metrics, recent activity, and an observation time; UI route `/admin` distinguishes loading, error, and observed facts. |
| ADM-UI-001 to 009 | Implemented | `/admin/audit` sends URL-backed time, actor (directory/stable ID/display name), server-controlled taxonomy/entity type, entity, outcome, source, request/correlation, My activity, security, administrative-operation, and page-size filters to the existing server list API; it uses server pagination, catalog selectors, responsive table cards, and `AuditDiff` for field-level evidence. |
| ADM-COR-001, 003 to 005 | Implemented | Event Detail provides stable entity links, request/correlation filters, a bounded inline correlated-event list, and correlation investigation navigation. Entity-side audit pivots are Deferred to Phase 3 data views. |
| ADM-SYS-001 to 004 | Implemented | Safe `/api/v1/admin/system` and `/diagnostics` contracts plus `/admin/system` and `/admin/diagnostics`; no shell, SQL, filesystem, or unrestricted log capability exists. |
| ADM-API-001 to 008 | Implemented | Typed Pydantic contracts and `adminFetch` are the exclusive browser data path; no direct MySQL client is introduced. The query repository retains bounded, parameterized filtering and canonical ordering. |
| ADM-API-009 / ADM-EXP-001 to 004 | Deferred to Phase 4 | No export or bulk action is introduced in read-only Phase B. |
| ADM-PERF-001 to 005 | Tested | Server pagination defaults to 50, has a 250 maximum, and the UI fetches one page at a time. Real-MySQL acceptance populated 1,002 synthetic events, followed all pages, verified bounded 100-event pages and two-query repository behavior, and exercised the indexed filter dimensions. |
| ADM-UX-001 to 004 | Tested | Semantic headings, labelled filters, table headers, skip link, visible focus, status text, and mobile card treatment are in the Admin shell. Playwright covers keyboard skip navigation and narrow layout; project has no additional formal accessibility runner. |
| ADM-DATA-001 to 006 / ADM-SET-001 to 004 | Deferred to Phase 3 | No data-management, correction, or setting mutation control exists. |
| ADM-ACC-001 to 004 / ADM-IDP-001 to 004 | Deferred to Phase 5 | The isolated development/staging rehearsal mapper is retained; corporate provider and group mapping are not guessed. |
| ADM-DNG-001 to 006 | Deferred to Phase 4 | No Danger Zone route, operation, API, or placeholder action has been created. |
| ADM-TST-001 to 005 | Tested | 15 focused server tests, 9 real-MySQL tests, 1 frontend unit test, and 7 substantive Playwright scenarios passed. Broad desktop regression is baseline-equivalent but does not pass because of the pre-existing Qt runtime crash recorded below. |
| ADM-DEP-001 to 006 | Deferred to Phase 6 | This branch has no deployment, NGINX, production schema, identity, privilege, or write-gate change. |
| ADM-CHG-001 to 004 | Implemented | This design record, this traceability record, typed contracts, and focused tests document the Phase 2 change boundary. |

## Route and contract inventory

| Route | Server contract | Status |
| --- | --- | --- |
| `/admin` | `GET /api/v1/admin/overview` | Implemented, read-only |
| `/admin/audit` | `GET /api/v1/admin/audit/catalog`, `GET /api/v1/admin/audit/events` | Implemented, read-only |
| `/admin/audit/events/:eventId` | `GET /api/v1/admin/audit/events/{eventId}` | Implemented, read-only |
| `/admin/system` | `GET /api/v1/admin/system` | Implemented, read-only |
| `/admin/diagnostics` | `GET /api/v1/admin/diagnostics` | Implemented, read-only |
| `/admin/data*`, `/admin/access`, `/admin/settings` | none | Deferred to Phase 3/5; no misleading controls |
| `/admin/danger-zone` | none | Deferred to Phase 4; no destructive surface |

## Current focused evidence

* `tests/fixtures/admin_phase2.py`: deterministic, synthetic records cover the
  governed entity, audit action, outcome, system-actor, redaction, correlation,
  null, and tied-timestamp investigation cases without production data.
* Focused server tests: 15 passed (8 Phase 1 audit-foundation tests, 3 initial
  Phase 2 overview/order/authorization tests, 3 contract/repository filter and
  bounded-volume tests, and 1 deterministic fixture-coverage test).
* `tests/integration/test_mysql_foundation.py` plus
  `tests/integration/test_mysql_admin_phase2_readonly.py`: **9 passed** against
  recovered `eoat_atlas_test` only. The Phase 2 suite writes 1,002 namespaced
  synthetic events, follows every server page, proves UUID-reversed tied events
  sort by immutable persisted sequence, validates filters/detail/redaction,
  exercises runtime API authorization, and asserts two repository SELECTs for a
  bounded page.
* `web/src/api/admin.test.ts`: 1 passed.
* `web/tests/e2e/admin.spec.ts`: **7 passed** (overview metric truth, direct
  link and URL/Back state, all supported filter controls, Event Detail
  actor/timestamp/request/redaction/correlation/no-mutation evidence, EOAT /
  Machine / Tool links, narrow-layout keyboard navigation, role-spoof denial,
  controlled not-found/outage states, and distinct server-pagination/empty-state
  evidence).
* Web typecheck, ESLint, and production Vite build passed.
* FastAPI OpenAPI generation recognizes `AdminOverviewContract`.
* **Broad regression classification:** candidate and a detached clean baseline
  at accepted Phase 1 `8634a55649` both ran the same exact desktop workflow on
  the same Windows Python/PySide runtime with `--timeout=300`. Both completed
  the test body before a Windows access violation at
  `tests/conftest.py:49` during `cleanup_qt_widgets`; the Phase 2 diff contains
  no `app`, `core`, or Qt-fixture change. This is a
  **PRE-EXISTING TEST-RUNTIME LIMITATION - NOT INTRODUCED BY ADMIN PHASE 2**.
  It is not reported as a broad-suite pass.

The controlled Phase 1 tunnel and protected local acceptance file were reused
without printing or committing a credential. Both migration and runtime
connections selected `eoat_atlas_test` from MySQL itself. The recovered test
schema had an unrelated legacy Alembic revision with no audit tables; only the
test schema's Alembic metadata was reconciled to the known predecessor, then
the additive Phase 1 audit migrations were applied. No database was dropped,
and neither development nor production was contacted. This document maps
implementation and evidence; the final decision is in the acceptance review.
