# Phase 3 deployment readiness

This checklist is a handoff boundary, not permission to activate a release.
The repository deliberately contains no Phase 3 deployment command.  A
validated GitHub Release and a PASS/READY Phase 2 read-only receipt are both
required before any of the actions below can be designed, tested, or approved.

## Required control plane

Before active deployment work can begin, infrastructure owners must provide
and document:

- A dedicated server-side deployment account with a narrowly scoped public-key
  authorization and the read-only inspection permissions required by Phase 2.
- Approved upload and staging paths under the controlled application root.
- A server-side deployment lock with ownership, timeout, stale-lock recovery,
  and audit rules.
- A tested database backup mechanism, restore owner, retention period, and
  verification procedure.
- A reproducible dependency-provisioning method using locked inputs only.
- An explicit migration approval gate, including destructive-migration review
  and a database recovery boundary.
- An atomic, reversible current-release switch and a retention policy for the
  previous known-good release.
- Scoped service and NGINX restart authority, bounded to verified unit names.
- Post-switch health checks for both release identity and API behavior.
- An automatic application rollback design, plus separately documented
  database recovery limits.
- Disposable-environment evidence covering upload, activation, failure,
  rollback, and retained-release recovery.

## Phase 2 acceptance inputs

The active-deployment design must consume a Phase 2 receipt that confirms the
selected GitHub Release, verified hash/manifest identity, server runtime,
available disk space, current release metadata, migration state, service
metadata, and local health probes.  Any UNKNOWN or FAIL result is a blocker;
it must not be converted into an assumption by a deployment script.
Filesystem metadata, the current symlink, systemd executable paths, host-routed
health responses, and declared runtime environment must agree. A disagreement
is a deployment truth violation and blocks release publication until the owner
resolves it or supplies authoritative evidence that changes the expected model.

Known-host verification and non-interactive authentication are separate gates.
The SSH host key must be matched to a trusted out-of-band fingerprint before
its known-host entry is added.  The deployment account must then authenticate
without password prompts, copied private keys, or relaxed host checking.

## Future release procedure constraints

An eventual Phase 3 implementation must preserve this order:

1. Acquire the deployment lock and verify the selected immutable artifact.
2. Confirm backup approval and create a verified recovery point.
3. Upload and stage without changing the current release.
4. Verify the staged hash, provision only locked dependencies, and review the
   migration plan before any database action.
5. Perform the approved migration, switch the release atomically, then restart
   only the approved services.
6. Verify versioned health checks, release identity, and service state.
7. Automatically roll back the application on failed health checks, while
   stopping at the documented database recovery boundary.

No implementation may skip a failed gate, broaden service scope, or treat an
application rollback as proof that a database migration is reversible.
