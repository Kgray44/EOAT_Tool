# EOAT Atlas Admin Phase 2 Acceptance Review

Status: **INCOMPLETE — source implementation and focused evidence are present;
the required real-MySQL and broad-regression acceptance gates have not passed.**

This is an honest review record, not an authorization to deploy Phase 2.

## Candidate identity

| Item | Evidence |
| --- | --- |
| Accepted source baseline | `8634a55649` (`ADMIN PHASE 1: PASS`) |
| Isolated worktree | `C:\Users\kgray\eoat-admin-phase2-readonly` |
| Branch | `feature/admin-phase2-readonly` |
| Phase 2 commits reviewed | `120e97a4ef`, `ccc4322216`, `1fae8575c6`, `e3fede5562`, `461cc8e5a9` |

## Implemented read-only surface

| Browser route | Server contracts | Disposition |
| --- | --- | --- |
| `/admin` | `GET /api/v1/admin/overview` | Implemented: server-observed identity, audit metrics, recent activity, and safe shortcuts. |
| `/admin/audit` | `GET /api/v1/admin/audit/catalog`, `GET /api/v1/admin/audit/events` | Implemented: safe search, server filters, URL state, bounded pagination, controlled selectors, and deterministic newest-first ordering. |
| `/admin/audit/events/:eventId` | `GET /api/v1/admin/audit/events/{eventId}` | Implemented: event/actor/entity evidence, structured diff, request/correlation links, related events, and ordinary-profile links. |
| `/admin/system` | `GET /api/v1/admin/system` | Implemented: safe read-only status. |
| `/admin/diagnostics` | `GET /api/v1/admin/diagnostics` | Implemented: safe schema/health compatibility state. |

The React browser client uses typed API contracts and `credentials: include`; it
does not read MySQL or derive Administrator privilege.  Every Admin API route
uses the existing server-side `require_admin` boundary.  Anonymous and Viewer
catalog access receive 401/403 in focused tests.  A spoofed browser-local role
does not cause the UI to receive audit data when the server returns 403.

## Security and scope boundary

* Redacted audit markers remain redacted in `AuditDiff`; no secret recovery is
  attempted.
* No Admin audit mutation endpoint, edit control, export, data correction,
  access administration, settings mutation, or Danger Zone capability was
  introduced.
* Normal profile History remains outside the `/api/v1/admin/audit` surface;
  Event Detail links outward to normal entity profiles rather than merging the
  datasets.
* No production deployment, migration, NGINX, AD/LDAP, write-gate, MySQL
  exposure, or production database privilege change was made.

## Evidence executed locally

| Evidence | Result |
| --- | --- |
| Focused server foundation and Phase 2 tests | 15 passed; one existing Starlette/httpx deprecation warning. |
| Static analysis | Ruff passed for Admin sources and focused tests. |
| FastAPI contract generation | Passed; catalog entity types and administrative filter are present in OpenAPI. |
| Browser unit test | Vitest: 1 passed. |
| Browser build checks | TypeScript, ESLint, and production Vite build passed. |
| Browser acceptance | Playwright: 6 passed, including direct routes, URL state, authorization-denied, errors, responsive keyboard navigation, pagination, and empty state. |
| Synthetic representative precheck | 1,000 in-memory synthetic audit events: two 100-event pages were bounded, ordered, and disjoint. This is not real-MySQL performance acceptance. |

## Acceptance gates not satisfied

1. **Real MySQL:** the secure process environment has no approved
   `EOAT_MYSQL_TEST_URL`, `EOAT_MYSQL_RUNTIME_URL`, database name, host, or
   environment configuration. No connection was guessed, and no database was
   mutated. Real-MySQL filters, pagination, detail, tied ordering, and role
   acceptance remain unproven.
2. **Broad regression:** the earlier full `pytest -q` attempt aborted at 6% in
   the unrelated Qt cleanup path for
   `tests/integration/test_fake_project_full_workflow.py`; the fatal abort was
   at `tests/conftest.py:49`. This has not been waived or counted as a pass.
3. **Formal accessibility and representative MySQL performance:** focused
   keyboard, labels, semantics, responsive layout, and browser behavior are
   covered, but the complete governed acceptance evidence remains open.

## Explicit deferrals

* Phase 3: data corrections, settings, and access administration.
* Phase 4: exports, operations, and Danger Zone.
* Phase 5: corporate identity provider and group mapping.
* Phase 6: controlled staging/production deployment and production operations.

**Decision: ADMIN PHASE 2: INCOMPLETE.**
