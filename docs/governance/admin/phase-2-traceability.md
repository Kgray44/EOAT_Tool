# EOAT Atlas Admin Phase 2 Traceability

Status: living implementation traceability.  `Implemented` means the stated
read-only behavior is present in the Phase 2 branch; it does not imply the
Phase 2 acceptance decision has been made.

| Governing requirement | Phase 2 disposition | Implementation and evidence |
| --- | --- | --- |
| ADM-GOV-001 to 004 | Implemented | `web/src/app/AdminApp.tsx` owns the isolated `/admin` area while preserving normal-profile links; `web/src/styles/admin.css` uses the EOAT Atlas visual vocabulary. |
| ADM-NAV-001 to 004 | Implemented | Server `require_admin` guards all Admin API contracts in `server/eoat_api/admin/routes.py`; real React routes use browser URL state. Focused negative authorization test: `tests/server/test_admin_phase2_readonly.py`. |
| ADM-AUTH-003, 008 | Implemented | Existing Phase 1 `read_actor_context` and `require_admin` remain authoritative. The browser does not derive an Administrator role. Corporate identity is Deferred to Phase 5. |
| ADM-HIS-001 to 003 | Implemented | The ledger uses only `AuditEvent`; the detail page links outward to normal entity routes without exposing Admin evidence through normal History. |
| ADM-AUD-001 to 010 / ADM-IMM-001 to 004 | Implemented | Phase 1 immutable event writer and repository remain unchanged; Phase 2 adds only GET contracts and no audit mutation endpoint or control. Existing foundation test plus source review protect this boundary. |
| ADM-SEC-001 to 004 | Implemented | API contracts return Phase 1-redacted fields; `AuditDiff` shows the redacted marker and never attempts recovery. Export is Deferred to Phase 4. |
| ADM-OVR-001 to 004 | Implemented | `/api/v1/admin/overview` uses `AuditEventRepository.overview` for bounded server-derived metrics, recent activity, and an observation time; UI route `/admin` distinguishes loading, error, and observed facts. |
| ADM-UI-001 to 009 | Implemented | `/admin/audit` sends URL-backed filters to the existing server list API, uses server pagination, catalog selectors, responsive table cards, and `AuditDiff` for field-level evidence. |
| ADM-COR-001, 003 to 005 | Implemented | Event Detail provides stable entity links, request/correlation filters, and correlation investigation navigation. Entity-side audit pivots are Deferred to Phase 3 data views. |
| ADM-SYS-001 to 004 | Implemented | Safe `/api/v1/admin/system` and `/diagnostics` contracts plus `/admin/system` and `/admin/diagnostics`; no shell, SQL, filesystem, or unrestricted log capability exists. |
| ADM-API-001 to 008 | Implemented | Typed Pydantic contracts and `adminFetch` are the exclusive browser data path; no direct MySQL client is introduced. The query repository retains bounded, parameterized filtering and canonical ordering. |
| ADM-API-009 / ADM-EXP-001 to 004 | Deferred to Phase 4 | No export or bulk action is introduced in read-only Phase B. |
| ADM-PERF-001 to 005 | Implemented | Server pagination defaults to 50, has a 250 maximum, and the UI fetches one page at a time. Representative-volume real-MySQL measurement remains pending acceptance infrastructure. |
| ADM-UX-001 to 004 | Implemented | Semantic headings, labelled filters, table headers, skip link, visible focus, status text, and mobile card treatment are in the Admin shell. Formal browser accessibility acceptance remains pending. |
| ADM-DATA-001 to 006 / ADM-SET-001 to 004 | Deferred to Phase 3 | No data-management, correction, or setting mutation control exists. |
| ADM-ACC-001 to 004 / ADM-IDP-001 to 004 | Deferred to Phase 5 | The isolated development/staging rehearsal mapper is retained; corporate provider and group mapping are not guessed. |
| ADM-DNG-001 to 006 | Deferred to Phase 4 | No Danger Zone route, operation, API, or placeholder action has been created. |
| ADM-TST-001 to 005 | In progress | Focused backend authorization/overview/tied-order tests, frontend API tests, and three Playwright direct-route/detail/narrow-layout scenarios pass. Real-MySQL, formal accessibility, and full regression evidence remains required before acceptance. |
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

* `tests/server/test_admin_phase2_readonly.py`: 3 passed (overview UTC metrics,
  tied timestamp order, anonymous/Viewer/Administrator catalog authorization).
* `tests/server/test_admin_audit_foundation.py`: 8 passed before the Phase 2
  extension.
* `web/src/api/admin.test.ts`: 1 passed.
* `web/tests/e2e/admin.spec.ts`: 3 passed (overview direct link and URL state,
  Event Detail redaction/correlation/no-mutation controls, narrow layout).
* Web typecheck, ESLint, and production Vite build passed.
* FastAPI OpenAPI generation recognizes `AdminOverviewContract`.

The mandatory real-MySQL, formal accessibility, performance-volume, full
regression, and final acceptance evidence remains open.  No protected
`eoat_atlas_test` connection configuration is available in this worktree or
its process environment, so a connection has not been guessed.  This document
is intentionally not an acceptance review.
