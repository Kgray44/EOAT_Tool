# EOAT release and deployment convergence design

## Current architecture and operator workflow

The existing `deployment.release_manager` builds a deterministic server archive,
validates its embedded and external manifests, and can publish through Git and
the GitHub CLI. `deployment.server_updater` discovers releases, verifies local
caches, and performs a read-only SSH preflight. `deployment.active_deployment`
uses the fixed privileged helper for explicit stage, activate, rollback, abort,
and recovery operations. The helper owns the production lock, immutable release
directories, atomic symlink changes, and post-activation health rollback.

Those components are valuable safety boundaries, but their entry points present
them as separate historical phases. The packager mutates the source branch
before its build and validation have proved a candidate. The updater reports a
single latest eligible release rather than an inventory, and its status wording
does not distinguish inspection, planning, staging, activation, and recovery.
Existing receipts are timestamped JSON files rather than one recoverable
transaction model. Migration-bearing deployment is intentionally blocked by
the installed helper protocol; that boundary must remain truthful until a
capable helper is installed by an authorized administrator.

## Converged architecture

`deployment.convergence` is the shared application-service layer. It defines
typed immutable state and result records, receipt persistence with corruption
quarantine, a bounded/redacting subprocess adapter, candidate preparation,
publication reconciliation, release inventory, read-only inspection, and
deployment planning. The console and `tools/eoat_release.py` call those same
services; neither contains business rules in callbacks or argument handling.

Candidate preparation always starts from a clean, up-to-date source revision,
uses an isolated clone, applies the governed version change only there, commits
the candidate, validates and archives that exact commit, and stores a Git bundle
plus artifact hashes outside the tracked tree. Publishing is a separately
confirmed transaction. It may fast-forward the verified candidate and perform
remote steps one at a time, recording identity checks after each step. A
conflict is never overwritten and a partially completed publication remains
recoverable rather than cosmetically rolled back.

The deployment service builds an explicit no-migration, migration-required,
unknown, blocked, or recovery-required plan. It delegates no-migration staging
and activation to the existing narrow helper. A migration plan is blocked
unless inspection proves a helper with the required installed capability; it
never treats unknown as not required and never claims a database rollback when
only the application symlink was restored.

## Compatibility and safety invariants

Existing archive/manifest formats and the root helper remain authoritative.
Legacy wrappers delegate to the unified CLI and identify their replacement.
Legacy valid receipts are readable as unversioned historical records; malformed
new receipts are atomically moved to a quarantine directory.

The following invariants are enforced by the new layer:

- Candidate rehearsal and preparation do not change the canonical worktree,
  tracked version, tag, branch, release, or production state.
- A candidate stores exact source, candidate commit/tree, bundle, manifest, and
  artifact identities before publication is permitted.
- Publication only resumes matching steps; conflicting Git refs, releases, and
  assets are blocked rather than overwritten.
- All persisted command diagnostics are redacted, bounded, timestamped, and
  categorized.
- Inspection is explicitly read-only. Staging, activation, rollback, and
  database recovery require separate state-aware commands and confirmations.
- Unknown capability, schema, or migration state is visible as unknown or
  blocked, never as a pass.

## Test strategy

Focused tests use temporary Git repositories and injectable fake publication
backends to prove clean-source rehearsal, immutable candidate capture, state
transition rejection, receipt quarantine, inventory classification, resume
rules, next-action resolution, and GUI worker/action truth. Existing archive,
manifest, helper, and deployment suites remain the lower-level regression
coverage. Real MySQL and production-helper installation are external gates:
they require a disposable MySQL 8.4 environment or an administrator-installed
helper, and are not represented as successful when unavailable.
