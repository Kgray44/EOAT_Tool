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

### Controlled desktop/browser parity session

- Exact blocker: no controlled desktop session or captured side-by-side
  evidence is available in this worktree.
- Evidence: `EOAT_0254_DESKTOP_WEB_PARITY_RECEIPT.md` records the completed
  source comparison and explicitly does not substitute it for visual proof.
- Precise next action: run the installed desktop app and hash-matched browser
  candidate against the same non-production records, capture the agreed
  viewport/font-scale cases, and attach a difference register.

### Controlled production deployment

- Exact blocker: the candidate and validation evidence now exist, but an
  installed data-operation policy, fresh production catalog and backup/dry-run
  receipts, approved media source, controlled desktop/browser parity evidence,
  production maintenance access, and approved host evidence are not jointly
  available.
- Evidence: final ledger and requirement matrix.
- Precise next action: resolve the preceding exact gates, verify production
  baseline, and use only the governed activation/data-operation interfaces.
- Production safety: safe; no production mutation was attempted.
