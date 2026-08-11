# EOAT Atlas Admin Phase 1 Acceptance Review

Status: Phase 1 acceptance complete.

## Verified Phase 1 criteria

- The governed Admin route and API namespace are frozen; normal application
  navigation and operational history remain separate.
- Administrator authorization is server-side and distinct from authentication.
- The centralized audit taxonomy, redaction, diffing, trusted actor context,
  schema version, query repository, and typed contracts are implemented.
- Real MySQL migration advanced the representative predecessor revision
  `20260714_0004` to `20260811_0006`; clean migration, constraints, indexes,
  audit table defaults, foreign key, uniqueness, and downgrade/forward recovery
  were exercised on `eoat_atlas_test`.
- The dedicated runtime role was denied protected-schema access, schema
  administration, and audit-event update/delete. No application audit update or
  delete path exists.
- Real persistence proved successful mutation plus audit, server actor, UTC
  timestamp, schema version, redaction, correlation lookup, and rollback when
  mandatory audit persistence was deliberately made to fail.
- Administrator API integration returned 401 without identity, 403 for Viewer,
  and 200 for Administrator through the runtime identity.
- Focused server tests passed 8/8; real MySQL foundation tests passed 6/6.

## EOAT History regression correction

The original 16/17 result exposed a pre-existing query defect: tied normal
History timestamps were broken by random UUID order. The corrected contract is
authoritative event timestamp followed by immutable persisted event sequence.
The targeted MySQL regression deliberately reversed UUID order for tied events,
and the complete write-conversion suite then passed **18/18** in 4.50 seconds.
Normal History remains separate from the global Admin audit ledger.

The complete EOAT History unit/UI module then passed **5/5** on a disposable
local Windows runner using a source archive of the committed candidate. This
avoided the Debian runner's missing `libGL.so.1` while neither changing the
server nor using dirty worktree files. The UI case exercised empty selection,
filtering, read-only behavior, and the large model.

## Final acceptance report

### Test infrastructure and isolation

- Server: the established `EOAT-ATLAS` Debian host, MySQL 8.4.10.
- Connection method: a temporary SSH forward from Windows to remote
  `127.0.0.1:3306`; MySQL remained loopback-only throughout.
- Isolated schema: `eoat_atlas_test` only.
- Test identities: `eoat_adminp1_migrator` (migration/recovery scope) and
  `eoat_adminp1_runtime` (ordinary application scope). Their protected local
  acceptance configuration is ACL-restricted and is outside Git. No credential
  value or credential-bearing URL is recorded here.
- Safety: each reset/migration checked the selected schema on the connected
  MySQL server. `eoat_atlas_prod` and `eoat_atlas_dev` were neither migrated,
  reset, fixture-loaded, nor queried for business data.

### MySQL migration, recovery, and privileges

- Representative predecessor revision: `20260714_0004`.
- Resulting revision: `20260811_0006`.
- Migration/clean-repeat result: PASS. A clean reconstructed test schema and a
  representative predecessor schema both advanced successfully; audit tables,
  columns, types, indexes, foreign key, uniqueness, defaults, nullability, and
  audit-event schema version storage were inspected on MySQL.
- Recovery result: PASS. The supported Alembic downgrade from head to
  `20260714_0004` and forward migration back to head both passed on the
  isolated schema.
- Runtime role result: PASS. The runtime identity performed required runtime
  reads/writes and approved audit inserts through application behavior, while
  protected-schema access, schema creation, privilege escalation, and audit
  `UPDATE`/`DELETE` were denied.

### Audit, transaction, query, and API acceptance

- Append-only result: PASS. Audit records have no application mutation/delete
  route; the runtime database role is restricted to audit `SELECT`/`INSERT`.
- Atomicity result: PASS. A deliberately failed mandatory audit write rolled
  back the governed business mutation, returned no success, and left no false
  successful audit event. The successful equivalent committed the mutation and
  audit event together with server-derived actor, request/correlation evidence,
  correct before/after data, and UTC timestamp.
- Structured evidence and redaction: PASS. Single/multi-field changes, null
  transition, normalization, unchanged-field omission, stable entity identity,
  actor, UTC timestamp, correlation, and persistence-path secret redaction
  were verified. Sensitive submitted values were absent from audit core,
  change rows, payload/metadata, and operation logs.
- Query repository: PASS. Persisted MySQL evidence covered timestamp, actor,
  action, entity type/ID, result, source, request/correlation filters plus
  deterministic ordering and pagination.
- API/service integration: PASS. The runtime-backed API returned 401 with no
  identity, 403 for Viewer, and 200 for Administrator; database credentials did
  not bypass application authorization.

### Regression evidence

| Suite | Result |
| --- | --- |
| `tests/server/test_admin_audit_foundation.py` | 8 passed, 0 failed (6.46 s) |
| `tests/integration/test_mysql_foundation.py` | 6 passed, 0 failed (0.41 s) |
| `tests/integration/test_mysql_write_conversion.py` | 18 passed, 0 failed (4.50 s) on clean real MySQL |
| `tests/test_eoat_history.py` | 5 passed, 0 failed (24.857 s) |

Total: **37 passed, 0 failed** across the targeted relevant regression suites.

### Repository and production safety

The candidate remains on `archived/mysql-source-retained` with the three
original Phase 1 implementation commits preserved, followed by the focused
MySQL parent-flush correction and the focused normal-History ordering
correction. Unrelated working-tree modifications and untracked files remain
unstaged and unchanged.

No production deployment, production migration, development-database mutation,
production write enablement, production authentication change, NGINX change,
AD/LDAP change, or port-3306 exposure occurred. No secret was committed.

Phase 2–6 UI, deployment, production-role, and provider work remains deferred
as designed; none is a remaining Phase 1 exit criterion.

## Safety review

All destructive acceptance work was limited to `eoat_atlas_test`; the prior
write-test state was backed up and restored after each run. `eoat_atlas_prod`
and `eoat_atlas_dev` were not migrated, reset, or queried for business data.
MySQL remained bound to loopback; test access used temporary SSH forwarding and
dedicated test credentials outside Git. No production deployment, NGINX,
authentication, AD, or production-write change occurred.
