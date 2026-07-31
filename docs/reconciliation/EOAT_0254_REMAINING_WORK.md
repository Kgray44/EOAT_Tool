# EOAT Atlas 0.25.4 remaining work

## Intentionally deferred

- LDAPS network correction
- Real directory login
- AD administrator-group mapping
- Production LDAP activation

LDAPS remains disabled and fail-closed. No LDAP network or credential action
was performed for this release.

## Genuine non-LDAPS remaining issue

### Fresh capacity candidate and installed policy

- Exact blocker: the documented immutable capacity candidate is external to
  this worktree and bound to an earlier source commit; no fresh 0.25.4-bound
  read-only production catalog/backup/policy package is available.
- Evidence: `EOAT_0254_CAPACITY_READINESS.md` and the root-helper validation.
- Why it cannot be completed locally: it requires the current production
  catalog, verified backup receipt, root-owned installed policy, and the
  approved workbook on the governed host.
- Precise next action: after exact-source validation, obtain a GET-only
  production catalog, rebuild and hash the candidate for the exact commit,
  then install the populated root-owned capacity policy and perform its dry
  run.
- Production safety: safe; writes remain disabled and no capacity was changed.

### Approved media source

- Exact blocker: no approved accessible media root or owner approval packet.
- Evidence: `EOAT_0254_MEDIA_READINESS.md`.
- Why it cannot be completed locally: the source location and ownership are
  intentionally external to the repository.
- Precise next action: complete `EOAT_MEDIA_SOURCE_MANIFEST_TEMPLATE.md` with
  the source owner, provision a read-only server mount, then run governed
  inventory and disposable migration validation.
- Production safety: safe; browser media remains fail-closed with truthful
  unavailable states.

### Controlled production deployment

- Exact blocker: release candidate, complete exact-head/MySQL validation,
  installed data-operation policy, production maintenance/backup access, and
  approved host evidence are not yet jointly available.
- Evidence: final ledger and requirement matrix.
- Precise next action: resolve the preceding exact gates, verify production
  baseline, and use only the governed activation/data-operation interfaces.
- Production safety: safe; no production mutation was attempted.
