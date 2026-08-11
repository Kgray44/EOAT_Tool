# EOAT Atlas Admin Phase 2 Acceptance Review

Status: **PASS - the governed Phase 2 read-only scope, real-MySQL acceptance,
and baseline-equivalent desktop-regression classification are complete.**

This acceptance does not authorize deployment. Phase 2 remains source and test
work only.

## Candidate identity

| Item | Evidence |
| --- | --- |
| Accepted source baseline | `8634a55649` (`ADMIN PHASE 1: PASS`) |
| Isolated worktree | `C:\Users\kgray\eoat-admin-phase2-readonly` |
| Branch | `feature/admin-phase2-readonly` |
| Phase 2 implementation commits | `120e97a4ef`, `ccc4322216`, `1fae8575c6`, `e3fede5562`, `461cc8e5a9`, `cefb3d7c85`, `5fd5ba414e`, `aba15d2da9` |

## Implemented read-only surface

| Browser route | Server contracts | Disposition |
| --- | --- | --- |
| `/admin` | `GET /api/v1/admin/overview` | Server-observed identity, audit metrics, recent activity, and safe shortcuts. |
| `/admin/audit` | catalog and list `GET` contracts | Safe search, server filters, URL state, bounded pagination, controlled selectors, and timestamp/persisted-sequence ordering. |
| `/admin/audit/events/:eventId` | detail `GET` contract | Event/actor/entity evidence, structured diff, request/correlation links, related events, and ordinary-profile links. |
| `/admin/system` | `GET /api/v1/admin/system` | Safe read-only status. |
| `/admin/diagnostics` | `GET /api/v1/admin/diagnostics` | Safe schema and health compatibility state. |

The browser uses typed API contracts and `credentials: include`; it neither
reads MySQL nor derives Administrator privilege. Every Admin API contract uses
the server-side `require_admin` boundary.

## Real-MySQL acceptance

The protected Phase 1 acceptance file was found and reused without displaying
or committing its contents. Both migration and runtime URLs were checked before
use, resolved to loopback and `eoat_atlas_test`, and then each returned
`eoat_atlas_test` from MySQL `SELECT DATABASE()` after a controlled temporary
SSH forward from local `127.0.0.1:58571` to the server's remote loopback MySQL.
No port was exposed.

The recovered test database held an unrelated legacy Alembic revision without
the Phase 1 audit tables. Only in `eoat_atlas_test`, Alembic metadata was
purged/stamped to the known Phase 1 predecessor, then the additive
`20260811_0005` and `20260811_0006` audit migrations were applied. No database
was dropped or reset; development and production were not contacted.

`tests/integration/test_mysql_foundation.py` and
`tests/integration/test_mysql_admin_phase2_readonly.py` passed **9/9** in 17.76
seconds. The Phase 2 suite created **1,002** namespaced synthetic audit events
and proved:

* migration/runtime access is isolated to `eoat_atlas_test`;
* Administrator API access succeeds while anonymous and Viewer access return
  401/403;
* date, actor, action, administrative-operation, entity type/ID, result,
  source, request, correlation, and safe-search filters run server-side;
* 11 pages contain all 1,002 events without duplication or omission;
* UUID-reversed tied events return by immutable persisted `id` sequence;
* Event Detail returns actor, entity, UTC timestamp, request/correlation data,
  and persisted redaction markers; and
* a 100-event repository page uses count-plus-data SELECTs only (two), with no
  per-row query pattern and an under-10-second bounded assertion.

## Browser, accessibility, and focused validation

* Focused Admin server/foundation tests: **15 passed**; Ruff and OpenAPI
  contract validation passed.
* Frontend unit test: **1 passed**. TypeScript, ESLint, and production Vite
  build passed.
* Playwright: **7 passed**. It asserts overview metric truth, direct deep links,
  URL filters and Back restoration, detail actor/timestamp/request/diff/
  correlation evidence, EOAT/Machine/Tool links, keyboard skip navigation,
  narrow layout, role-spoof denial, controlled errors, pagination, and empty
  results.

The repository has no additional accessibility runner. Browser coverage proves
the implemented semantic labels, headings, table semantics, focus visibility,
and keyboard flow.

## Broad desktop regression classification

Candidate and a disposable, clean, detached worktree at exact accepted Phase 1
`8634a55649` ran the same desktop workflow with the same Windows Python
3.14/PySide runtime and `--timeout=300`. Both completed the test body before a
Windows access violation at `tests/conftest.py:49` during `cleanup_qt_widgets`.
The disposable baseline worktree was then removed. The Phase 2 diff does not
change `app`, `core`, or `tests/conftest.py`.

**Broad regression: baseline-equivalent pre-existing Qt runtime crash; no Phase
2 regression demonstrated.** This is not a claim that the broad suite passed.
The appropriate follow-up is a separately governed desktop test-runtime effort
for Python 3.14/PySide lifecycle compatibility, not an Admin semantic change.

## Security and scope boundary

* Redacted audit markers remain redacted; no secret recovery is attempted.
* No Admin audit mutation endpoint, edit control, export, data correction,
  access administration, settings mutation, or Danger Zone capability exists.
* Normal profile History remains separate from global Admin Audit; detail links
  outward to normal entity profiles.
* No production deployment, migration, NGINX, AD/LDAP, write-gate, MySQL
  exposure, or production database privilege change was made.

## Explicit deferrals

* Phase 3: data corrections, settings, and access administration.
* Phase 4: exports, operations, and Danger Zone.
* Phase 5: corporate identity provider and group mapping.
* Phase 6: controlled staging/production deployment and production operations.

**Decision: ADMIN PHASE 2: PASS.**
