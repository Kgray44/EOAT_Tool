# EOAT Atlas application versioning

## Architecture

`release_metadata.json` at the repository root is the one authoritative application-version source. It is UTF-8 JSON and its `app_version` is strict three-part semantic versioning (`MAJOR.MINOR.PATCH`). It can be read without starting Qt, MySQL, the API, or any network service:

```powershell
python -c "from core.versioning import get_app_version; print(get_app_version())"
```

The runtime metadata loader, Settings diagnostics, startup/events, support exports, PyInstaller build, package validator, installer, release publisher, and launcher-installed-version reader consume `release_metadata.json`. `app\atlas\version.json` remains checked-in only for compatibility with older launcher layouts; it is derived and synchronized by the bump utility. The publisher builds versioned archives and manifests from the canonical value rather than choosing a second version.

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

`release_history.json` is the tracked audit ledger. Each successful finalization atomically appends one strictly increasing version with its release ID, build ID, task ID, UTC time, and `finalized` state. The exclusive `.git\eoat-version-bump.lock` is the short-lived reservation: concurrent tasks cannot calculate or claim the same next version. The lock is removed automatically on success or handled failure. A failed transaction rolls back canonical, derived, and ledger files, so it creates no permanent gap.

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

`--set` must be a strict version greater than the current version. The utility validates all inputs before writing, updates the canonical and derived files as one rollback-protected operation, preserves their existing layout, and refuses inconsistent sources.

The checker discovers the pull-request/push baseline in GitHub Actions, accepts `--base` or `EOAT_VERSION_BASE`, and defaults to `HEAD~1`. It fails for missing/malformed/decreased/reused versions, mismatched release IDs, canonical/derived/component disagreement, missing or non-monotonic ledger history, more than one finalized task entry, unexpected hard-coded authoritative sources, or application changes without an increment. Developer-only docs, tests, reports, logs, caches, temporary/build output, and repository instructions do not independently require a bump. Documentation or resources packaged with the app do.

CI runs the checker with full Git history. `scripts\pre_commit_check.ps1` validates the staged snapshot; a Git hook is not the authority.

## Builds, releases, and troubleshooting

`EOAT_Atlas.spec` bundles canonical metadata and maps semantic `X.Y.Z` deterministically to Windows `X.Y.Z.0` through `build_tools\version_metadata.py`. The installer validates that bundled metadata and advertises/records the application package version while retaining its own implementation version. Both launcher paths read installed release metadata and compare strict numeric application versions with deployment `latest.json`; manifests and packages must agree on application version, release ID, and build ID. `scripts\publish_release.py` requires the already-bumped canonical version to be newer than the published manifest and does not bump again.

Production build IDs use `eoat-atlas-VERSION-COMMIT7-YYYYMMDDTHHMMSSZ`. The release ID remains `eoat-atlas-VERSION` across builds. MySQL `application_releases` registers build-level provenance, while stable EOAT/tool/machine/audit/document/photo/client IDs and Alembic revision IDs remain unchanged.

If validation reports a mismatch, do not hand-edit the derived file. Inspect both JSON files, restore unintended edits, then run the bump utility once. Confirm with:

```powershell
python scripts\check_version_bump.py --skip-change-check
python -c "from core.versioning import get_version_info; print(get_version_info())"
```

Common examples: a typo or small crash fix is patch; a new reporting workflow is minor; a platform rewrite is major; analysis-only documentation or test-output cleanup receives no bump.
