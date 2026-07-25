# Release Notes

## EOAT Atlas 0.22.12 — Deployed Production Release

- Removed imported `audit_evidence` rows from the browser-facing Machine Profile contract. Those legacy rows can contain internal path-like source details and are not required to render a Machine Profile.
- Added a live Chromium/Playwright all-machine gate that obtains machine identifiers from the API, verifies direct navigation and refresh for every current machine, and checks relationship truth wording, read-only browser behavior, and console health.
- Updated deterministic deployment test fixtures to model the canonical schema head `20260721_0008`.
- Production was activated through a zero-migration coordinated transaction from authoritative source `0ddf66bfff6dd23c07279d55576736290d040dca`. All 56 current production Machine Profiles passed the live browser sweep and all 336 supported Machine Profile API calls passed the browser-boundary/path-leak scan. Production writes remain disabled; the database was not changed.

## EOAT Atlas 0.22.7 — Deployed Production Release

- Authoritative deployed source: `b39fb6057d6c18526a1802a47886b808194c47c9`; schema: `20260721_0008`.
- Production activation was zero-migration and left writes disabled. The API and MySQL remain loopback-only; the internal web host remains HTTP port 80 only.
- Machine 27 is an acceptance example, not a runtime special case. Machine Profile routing, API requests, relationships, media, and truthful empty/error states are parameterized by the current machine identifier.
- The release is preserved by annotated tag `v0.22.7` and the corresponding GitHub Release. Current production API and frontend release paths are recorded in the root-owned deployment transaction receipt, not in source control.

## Phase 2.6 Pre-Onedir Readiness Gate

- Added package-safe resource helpers for source and frozen modes.
- Made release metadata load from bundled resources in packaged mode and included `release_metadata.json` in `EOAT_Atlas.spec`.
- Added frozen-mode runtime folder selection for future `%LOCALAPPDATA%\EOAT_Atlas` production runtime.
- Added smoke-runtime initialization for metadata, identity, SQLite schema, pending update, and event probes.
- Added `scripts/preflight_onedir_readiness.py` for source preflight gates before PyInstaller.
- Rebuilt `scripts/smoke_test_package.py` for the future post-onedir package smoke.
- Added Phase 2.6 tests for metadata, LocalAppData runtime enforcement, spec readiness, preflight, package smoke failure behavior, and sync/lock identity metadata.

## Phase 2.5 Pre-Onedir Cleanup

- Centralized EOAT Atlas release metadata in `release_metadata.json` and `core/globalization/app_metadata.py`.
- Added stable LocalAppData install identity support for dev fallback and future installer-provided identity.
- Split Refresh from Deep Refresh: Refresh is local SQLite/UI reload only; Deep Refresh rebuilds the SQLite cache from staged workbook data.
- Hardened pending updates, effective-record overlays, conflict detection, sandbox workbook sync, backups, and audit-quality event JSON.
- Kept production workbook writes disabled by default.
- Removed active Command Center/classic Atlas naming from release-scope app paths.
- Fixed Settings startup/open freeze by deferring Settings creation, caching source defaults/metadata, avoiding eager network validation, and guarding delayed search focus callbacks.

## Phase 6 Release Candidate

- Added full system audit.
- Added safe workflow runner for daily start, daily end, weekly review, and final review.
- Added workbook/config/report-index/light project backup tool.
- Added packaging preparation scripts and docs.
- Added launcher troubleshooting for UNC paths and Python dependency issues.
- Added tests for registry completeness, CLI help, system audit, workflows, backups, and overwrite safety.

## Phase 0-5 Summary

- Phase 0: modular app foundation.
- Phase 1: foundation dashboard and existing tool integration.
- Phase 2: audit data collection tools.
- Phase 3: engineering analysis tools.
- Phase 4: standardization and routine reporting tools.
- Phase 5: final presentation and handoff tools.
