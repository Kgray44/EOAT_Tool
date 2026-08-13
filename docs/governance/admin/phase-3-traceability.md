# EOAT Atlas Admin Phase 3 Traceability

## Scope-to-implementation map

| Required outcome | Implemented evidence |
| --- | --- |
| Isolated baseline | `feature/admin-phase3-governed-editing` begins at accepted `532e3adef34e1b6290647ee9637de396f5f7afa8`; the UNC archive and Phase 2 worktree were not changed. |
| Server-resolved mutation actor | `security.py` issues an opaque, short-lived HttpOnly/SameSite local rehearsal session only in development/staging-local, after a server-held rehearsal-secret comparison and persisted mapping lookup. |
| Anti-forgery and mutation controls | `require_admin_mutation` requires the session-bound CSRF value, JSON requests, a bounded declared body, current capability, and route validation; mutations require idempotency keys. |
| EOAT/Machine/Tool editing | `admin/mutation_routes.py` and `mutation_service.py` reuse canonical `write_services` for preview, update/correction, archive, restore, concurrency, history, audit and rollback. |
| Relationships, documents, photos and bulk | Typed Admin endpoints and browser pages provide relationship linking/unlinking, safe document/photo metadata/archive controls, and one previewed EOAT bulk status workflow. |
| Settings and access | Existing persisted `SystemSetting` records use typed, secret-safe updates. Persisted development/test mappings and rehearsal-session revocation are capability limited and audited. |
| Audit integrity | The canonical `AuditEventWriter` remains in the same transaction as domain writes. Source is `WEB`, correlation uses the request ID, and no endpoint mutates audit evidence. |

## Validation record

| Check | Result |
| --- | --- |
| `python -m compileall -q server/eoat_api ...` | PASS |
| Focused Phase 1/2 server tests | PASS: 14 tests |
| Real MySQL migration | PASS on Debian MySQL 8.4.10: `20260811_0006 -> 20260811_0007`; recovery/repeat PASS after the MySQL downgrade index-order correction. |
| New `test_mysql_admin_phase3_governed_editing.py` | PASS: 5/5 against `eoat_atlas_test` through the protected loopback SSH tunnel. |
| `pnpm --dir web typecheck` | PASS |
| `pnpm --dir web lint` | PASS |
| `pnpm --dir web build` | PASS |
| Normal-profile link contract | Implemented: Audit Event Detail uses only same-origin relative links and the immutable Audit `entity.display_id`: EOAT `/eoats/:identifier`, Machine `/machines/:number`, Tool `/tools/:identifier`. Events without a canonical display identifier deliberately have no profile link. |
| Canonical web-client provenance | The existing normal browser router is on unrelated newer lineage `codex/web-desktop-full-parity` at `7d9b6952ca` (Machine profile first introduced by `6d39823d08309cba3a109edda698ad8c47563748`; EOAT QR profile by `7918d0da79dc244081937d2f67a1fc2389123d39`). It defines `/eoats/:identifier`, `/machines/:number`, and `/tools/:identifier`; `git merge-base` with this accepted Admin lineage returns no common ancestor. No broad merge or duplicate profile components were introduced. |
| Browser-to-real-MySQL EOAT mutation | Partial PASS: rehearsal session, preview, commit and `/admin/audit/events/:eventId` exact diff/actor/correlation were observed. The audit href contract now points to the canonical normal-app path, but rendered cross-navigation awaits the separately reconciled normal-client lineage. |

## Production isolation

No production database, filesystem, deployment, service configuration, NGINX
configuration, LDAP/AD mapping, or production write gate was read or changed.
The only database target used for acceptance was the explicitly named
`eoat_atlas_test`, reached through the established Windows-loopback to
Debian-loopback SSH tunnel. The local Windows MySQL service was not started or
used.

## Acceptance status

**ADMIN PHASE 3: NOT YET ACCEPTED.** Real-MySQL migration and the original
five tests now pass, but full mutation/browser/security/performance/regression
reconciliation is still required.
