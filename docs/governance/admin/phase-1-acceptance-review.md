# EOAT Atlas Admin Phase 1 Acceptance Review

Status: Incomplete pending the existing write-conversion regression candidate.

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

## Outstanding criterion

`tests/integration/test_mysql_write_conversion.py` completed with 16 passing
tests and one failure in pre-existing EOAT history ordering. The unchanged
assertion expects the most recent history item to be `EOAT_UPDATED`; the
observed current-history item was `EOAT_LOCATION_MARKED_UNKNOWN`. Phase 1 did
not modify the history ordering code or that assertion. Until the baseline
owner classifies or repairs this regression, the complete relevant regression
suite cannot be reported as passing, so the Phase 1 exit criterion is not yet
met.

## Safety review

All destructive acceptance work was limited to `eoat_atlas_test`; the prior
write-test state was backed up and restored after each run. `eoat_atlas_prod`
and `eoat_atlas_dev` were not migrated, reset, or queried for business data.
MySQL remained bound to loopback; test access used temporary SSH forwarding and
dedicated test credentials outside Git. No production deployment, NGINX,
authentication, AD, or production-write change occurred.
