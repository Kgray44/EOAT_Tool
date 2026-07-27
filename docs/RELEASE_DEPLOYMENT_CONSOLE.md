# EOAT Atlas Release and Deployment Console

`tools/release_deployment_console.py` is the PySide6 operator application and
`tools/eoat_release.py` is its automation-equivalent CLI.  Both call
`deployment.convergence.ReleaseDeploymentService`; neither GUI callbacks nor
CLI parsing contain an alternate deployment workflow.

The console has Overview, Release Preparation, Release Inventory, Target
Inspection, Deployment Plan, Deployment Transaction, Logs/Receipts, and
Settings pages.  Overview begins at **NOT RUN**.  Long-running work runs on a
`QThread`; the window warns before closing an active operation.  The visible
summary is the primary UI and expanded, redacted diagnostics remain in Logs.

## Commands

```text
python tools/eoat_release.py status
python tools/eoat_release.py diagnose
python tools/eoat_release.py candidate rehearse --bump patch
python tools/eoat_release.py candidate prepare --version 0.24.0
python tools/eoat_release.py candidate list
python tools/eoat_release.py candidate show candidate-0.23.0-<commit>
python tools/eoat_release.py candidate build-core-artifacts candidate-0.24.0-<commit>
python tools/eoat_release.py candidate verify-core-artifacts candidate-0.24.0-<commit>
python tools/eoat_release.py candidate inspect-platform-attachment candidate-0.24.0-<commit> path/to/windows-attachment
python tools/eoat_release.py candidate attach-platform-artifacts candidate-0.24.0-<commit> path/to/windows-attachment
python tools/eoat_release.py candidate verify-platform-artifacts candidate-0.24.0-<commit>
python tools/eoat_release.py candidate show-components candidate-0.24.0-<commit>
python tools/eoat_release.py candidate verify-for-sealing candidate-0.24.0-<commit>
python tools/eoat_release.py candidate seal-release-set candidate-0.24.0-<commit> --confirm "SEAL candidate-0.24.0-<commit>"
python tools/eoat_release.py candidate verify-sealed-release-set candidate-0.24.0-<commit>
python tools/eoat_release.py candidate discard candidate-0.23.0-<commit>
python tools/eoat_release.py publish start candidate-0.23.0-<commit> --confirm-version 0.23.0
python tools/eoat_release.py publish resume publication-candidate-0.23.0-<commit>
python tools/eoat_release.py publish status publication-candidate-0.23.0-<commit>
python tools/eoat_release.py releases list
python tools/eoat_release.py releases verify --version 0.23.0
python tools/eoat_release.py target inspect --server-config path/to/test-target.json
python tools/eoat_release.py target status --inspection inspection-<id>
python tools/eoat_release.py plan create --release 0.23.0 --inspection inspection-<id>
python tools/eoat_release.py deploy stage --plan plan-<id> --confirm-version 0.23.0
python tools/eoat_release.py deploy status --transaction transaction-<id>
python tools/eoat_release.py receipts list
```

Use `--json` for an identical structured result.  The deprecated
`tools/release_manager.py` and `tools/server_updater.py` intentionally reject
legacy arguments and print the exact unified replacement; they do not forward
unknown commands into a different semantic workflow.

## Safety model

Candidate rehearsal and preparation use a clean, up-to-date source revision
and an isolated clone.  They do not change the canonical worktree, tag,
release, target, or tracked version.  A retained candidate contains the exact
source and candidate commits/trees, server artifact and manifest hashes, and a
Git bundle.  The candidate is built twice with the same timestamp and is
blocked when hashes differ.

Phase 1B-2 candidates are deliberately unsigned and publication-ineligible.
The Release Preparation page runs core evidence validation through its existing
background worker, displays the complete component inventory, and can inspect
or attach a Windows bundle only when candidate ID, product/release/build
identity, commit/tree, hashes, metadata, manifests, and packaged smoke
receipts agree. Bootstrap remains explicitly not applicable until Phase 2;
the final release-set manifest and signature remain pending until Phase 1B-3.

Phase 1B-3 adds background-worker actions to revalidate a complete candidate,
seal it with a typed candidate-ID confirmation, and verify the detached
signature. The preparation page shows the canonical digest, signature key and
trust result, outer manifest/signature components, derived missing components,
and publication eligibility. It never exposes private key material. The seal
action remains unavailable for incomplete or blocked candidates and does not
create a publication or production deployment.

Phase 1C adds publication-readiness, disposable-backend publication/resume,
asset inventory, trusted release inventory, and read-only planning views. The
operator must provide a disposable bare remote and filesystem registry and
type `PUBLISH <candidate-id>`. Production GitHub publication controls remain
disabled; a trusted inventory result is planning evidence only and adds no
stage or activation control.

Publication requires typing the exact candidate version.  It records and
verifies every step: candidate promotion, local tag, branch push, tag push,
release creation, primary assets, and receipt attachment.  Resume first proves
completed local/remote state still matches the candidate.  A mismatched ref,
release, asset, tree, archive, or manifest is blocked; it is never replaced.

Release verification downloads only the selected release, validates the
external manifest, archive and checksum, verifies tag/manifest commit
identity, and retains the exact cache evidence.  Inventory never silently
chooses the newest release and explains draft, prerelease, duplicate archive,
or missing-asset ineligibility.

Target inspection requires a JSON configuration containing
`"test_target": true` and rejects known production hostnames.  It first uses a
versioned, fixed-shape `diagnose` helper request with no supplied command,
path, environment, or secret.  Only an explicitly labelled compatibility
fallback may use the existing read-only inspection boundary.  Missing facts
remain UNKNOWN/UNAVAILABLE rather than becoming a healthy inference.

Plans distinguish `NO_MIGRATION_REQUIRED`, `MIGRATION_REQUIRED`,
`MIGRATION_STATE_UNKNOWN`, `MIGRATION_BLOCKED`, and
`ROLLBACK_OR_RECOVERY_REQUIRED`.  Unknown is never treated as no migration.
Application rollback and database recovery are separate, explicit transaction
states.  Dangerous transaction controls require typing the exact transaction
ID; they are never auto-confirmed.

## Receipts, diagnostics, and readiness

Receipts are atomically written below `.local/release-deployment-console/`.
Malformed records are moved to quarantine; exports refuse to overwrite an
existing user file.  Persisted command diagnostics include bounded, redacted
output, timestamps, duration, exit category, retryability, and whether a local
or remote mutation might have occurred.  No receipt stores passwords, tokens,
private keys, raw environment files, or database credentials.

Readiness is scope-aware.  Candidate readiness requires the clean upstream
state, version metadata, Git/Python/migration graph/storage, and for web
repositories Node plus the `packageManager`-pinned pnpm and lockfile.
Publication adds GitHub CLI, origin, authentication, and unfinished-publication
checks.  Required BLOCKED, UNKNOWN, and NOT_RUN facts block the corresponding
operation; optional diagnostics are visible but do not become a false pass.

This tooling does not authorize or perform a production deployment merely by
being present in the repository.  Production host/database inspection,
privileged-helper installation, NGINX/systemd changes, release tags, and GitHub
Release publication remain explicit external authorization boundaries.
