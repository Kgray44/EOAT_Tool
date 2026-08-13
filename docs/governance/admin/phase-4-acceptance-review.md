# EOAT Atlas Admin Phase 4 Acceptance Review

Date: 2026-08-13  
Branch: `feature/admin-phase4-danger-operations`  
Baseline: `eed879b5ce1d5840ce76bc81bbf31ed62ce443ce`

## Privilege repair and scope proof

The existing test runtime identity retained its prior read access and received
only these additional table permissions in `eoat_atlas_test`:

| Table                      | Additional DML     | Exercised live                                 |
| -------------------------- | ------------------ | ---------------------------------------------- |
| `admin_danger_step_ups`    | `INSERT`           | Yes: scoped step-up creation.                  |
| `admin_operations`         | `INSERT`, `UPDATE` | Yes: integrity and Danger operation lifecycle. |
| `admin_operation_fixtures` | `INSERT`, `DELETE` | Yes: bounded test-fixture recovery.            |

`DELETE` is present only because the owned recovery rehearsal deletes an exact
test-fixture namespace. It is absent from operation and audit evidence tables.
Direct runtime SQL exercised the approved DML and rejected audit-table update,
test-schema DDL, production-schema read, and `GRANT`. The diagnostics guard
now verifies this exact three-table privilege shape and fails closed if it is
not available.

## Passed evidence

- Real MySQL Phase 4 integration and failure-mode tests passed with the normal
  runtime identity. The successful operation persisted its evidence and
  removed only named disposable `phase4-...` fixtures.
- The failure matrix passed live CSRF, namespace, bad step-up, missing
  idempotency key, no-step-up, revoked newest step-up, target-drift, and
  conflicting-operation denial paths. The revocation test found and corrected
  a fallback-to-older-proof defect before this decision.
- The recovery metadata unit test passed missing hash, incorrect revision,
  modified artifact, and stale artifact cases. The clean `0008` artifact was
  hash-verified, restored with an explicit `eoat_atlas_test` target, and
  verified at `20260813_0008` with all three tables and zero Phase 4 rows.
- A real browser session used the local Vite/API pair backed by MySQL to start
  a governed session, perform a scoped step-up, obtain a server preview with
  all required preconditions, type the confirmation, and complete deletion of
  exactly one disposable fixture. Mobile (375x812) and tablet (768x1024)
  checks preserved the live operation state.
- Local HTTP observations were all below one second: diagnostics 567.1 ms,
  integrity 558.9 ms, bounded audit export 435.5 ms, and support bundle
  625.4 ms. An unbounded audit export correctly remained rejected with
  `EXPORT_SCOPE_TOO_LARGE`.
- `python -m compileall -q server` and the focused Phase 2/3/4 real-MySQL
  regression suite passed: 30 tests. The only warning was the existing
  FastAPI TestClient deprecation warning.
- OpenAPI generation/check, TypeScript, ESLint, Vitest (47 tests), production
  build, and Playwright (10 tests) passed. The build retained its existing
  chunk-size advisory only.
- No production database, production migration, deployment, NGINX, LDAP/AD,
  external MySQL privilege, secret disclosure, or browser backup/restore
  capability was introduced.

## Cleanup evidence

- Local API/Vite acceptance processes and the protected SSH tunnel were
  stopped.
- The temporary remote Codex sudo rule was removed, credentials invalidated
  with `sudo -k`, and `sudo -n true` then failed as required.
- The original UNC checkout was not changed; all source changes remain in the
  owned Phase 4 worktree and branch.

## Decision

**ADMIN PHASE 4: PASS.** This is acceptance of the isolated development/test
scope only. Phase 5 corporate identity and Phase 6 broader operational or
production-like capabilities remain separately governed and unstarted.
