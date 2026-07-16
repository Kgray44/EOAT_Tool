# EOAT Atlas application versioning

## Architecture

`app/atlas/version.json` is the one tracked application-version source. Its `version` is strict three-part semantic versioning (`MAJOR.MINOR.PATCH`). `release_defaults.json` contains component and schema defaults that are independent of build identity.

```powershell
python -c "from core.versioning import get_app_version; print(get_app_version())"
```

`release_metadata.json` is not tracked. A release builder selects an exact committed source revision and generates this file into the artifact. It records `source_git_commit`; legacy `git_commit` is retained as an equal compatibility alias. Source checkouts synthesize a clearly marked `source_checkout` identity for development, while an extracted deployment with no `.git` directory must contain generated `release_artifact` metadata.

`core\versioning\version_info.py` exposes the lightweight unified release model: application version/release ID/build ID, commit and branch, release channel, schema revision, API contract version, launcher version, and installer version. Component values are associated snapshots and are validated against their independent sources; they do not replace those sources.

These are deliberately independent: `launcher\launcher_version.json`, `installer\installer_config.json`'s installer version, `core\versioning\compatibility.py` API/MySQL/schema expectations, server API contract versions, and database migration revisions.

## Required Codex workflow

For each modifying prompt: inspect; implement; add tests; run focused validation; run suitable regression checks; classify the largest change; bump once; synchronize metadata; run the checker; review the diff; and report the result. Do not bump during intermediate corrections.

Codex should use a stable task identifier so accidental retries do not bump twice:

```powershell
python scripts\bump_version.py minor --operation-id codex-authentication-workflow-20260715
```

Repeating that exact operation is a no-op if its recorded version is still current. Different concurrent tasks must use different operation IDs.

## Release ledger, reservation, and recovery

`release_history.json` is the tracked version/task ledger. Each successful finalization atomically appends one strictly increasing version with its stable release ID, task ID, UTC time, and `finalized` state. Build IDs and source commits are deliberately absent because they do not exist until after the source commit is created. The external artifact manifest owns those build facts. The exclusive `.git\eoat-version-bump.lock` is the short-lived reservation. A failed transaction rolls back the canonical version and ledger files, so it creates no permanent gap.

Per-worktree operation receipts under `.git\eoat-version-operations` make retries idempotent. If a process crashes and leaves a lock, verify that the recorded PID is no longer running and that canonical/derived/ledger validation passes before removing only that stale lock. Never delete or rewrite finalized ledger entries. Abandoned tasks that made no finalized change need no ledger entry; recovery reruns with the same task ID.

## Classification

Patch (`0.0.1`) covers small bugs, UI/text/style/tooltip/spacing corrections, narrow settings changes, small fields/options, localized validation/logging/error handling, and accompanying tests. Examples: `2.4.7 -> 2.4.8`, `2.4.9 -> 2.4.10`.

Minor/regular (`0.1.0`) covers a new page or workflow, substantial feature, broad UI redesign, significant database-backed capability, export/reporting/authentication integration, deployment enhancement, or cross-subsystem fix. Examples: `2.4.7 -> 2.5.0`, `2.9.4 -> 2.10.0`.

Major (`1.0.0`) covers a breaking architecture/platform migration, new product generation, foundational storage/service replacement with material product impact, or coordinated suite that redefines EOAT Atlas. Examples: `2.4.7 -> 3.0.0`, `3.8.2 -> 4.0.0`.

When uncertain, consider user impact, compatibility, deployment/database impact, workflows affected, and whether a complete new capability was introduced. File count alone is not classification.

## Commands

Run from the repository root in PowerShell:

```powershell
python scripts\bump_version.py patch
python scripts\bump_version.py minor
python scripts\bump_version.py major
python scripts\bump_version.py --set 3.0.0
python scripts\check_version_bump.py --base HEAD~1
python scripts\check_version_bump.py --skip-change-check
python -m pytest tests\test_versioning.py
```

`--set` must be a strict version greater than the current version. The utility validates all inputs before writing and updates the canonical version and ledger as one rollback-protected operation.

The checker discovers the pull-request/push baseline in GitHub Actions, accepts `--base` or `EOAT_VERSION_BASE`, and defaults to `HEAD~1`. It fails for missing/malformed/decreased/reused versions, mismatched release IDs, canonical/derived/component disagreement, missing or non-monotonic ledger history, more than one finalized task entry, unexpected hard-coded authoritative sources, or application changes without an increment. Developer-only docs, tests, reports, logs, caches, temporary/build output, and repository instructions do not independently require a bump. Documentation or resources packaged with the app do.

CI runs the checker with full Git history. `scripts\pre_commit_check.ps1` validates the staged snapshot; a Git hook is not the authority.

## Builds, releases, and troubleshooting

`EOAT_Atlas.spec` requires generated metadata through `EOAT_ATLAS_BUILD_METADATA` and maps semantic `X.Y.Z` deterministically to Windows `X.Y.Z.0`. The installer and launcher continue to consume the generated compatibility fields. `scripts\publish_release.py` requires the already-bumped canonical version and never writes generated identity back into source.

Production build IDs use `eoat-atlas-VERSION-COMMIT7-YYYYMMDDTHHMMSSZ`. The release ID remains `eoat-atlas-VERSION` across builds. MySQL `application_releases` registers build-level provenance, while stable EOAT/tool/machine/audit/document/photo/client IDs and Alembic revision IDs remain unchanged.

If validation reports a mismatch, do not hand-edit generated release metadata. Inspect the canonical version, defaults, and ledger, restore unintended edits, then run the bump utility once. Confirm with:

```powershell
python scripts\check_version_bump.py --skip-change-check
python -c "from core.versioning import get_version_info; print(get_version_info())"
```

Common examples: a typo or small crash fix is patch; a new reporting workflow is minor; a platform rewrite is major; analysis-only documentation or test-output cleanup receives no bump.
