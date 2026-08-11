# EOAT Atlas Admin Phase 1 Acceptance Review

Status: Pending final UI-history runner dependency; database/API acceptance is complete.

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

The non-UI EOAT History unit coverage passed before the UI check required a
desktop-capable runner. The Debian runner can import the UI module but lacks
the system `libGL.so.1` dependency required to create the Qt test application;
that final UI-only validation remains outstanding.

## Safety review

All destructive acceptance work was limited to `eoat_atlas_test`; the prior
write-test state was backed up and restored after each run. `eoat_atlas_prod`
and `eoat_atlas_dev` were not migrated, reset, or queried for business data.
MySQL remained bound to loopback; test access used temporary SSH forwarding and
dedicated test credentials outside Git. No production deployment, NGINX,
authentication, AD, or production-write change occurred.
