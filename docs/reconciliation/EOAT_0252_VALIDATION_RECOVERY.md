# EOAT Atlas 0.25.3 validation recovery receipt

Date: 2026-07-30  
Branch: `integration/mirrorline-parity-completion-0.25.2`  
Target application version: `0.25.3`
Target schema: `20260729_0009`

## Scope and production boundary

This receipt covers local source validation only. No production mutation,
candidate creation, deployment, LDAP activation, capacity import execution, or
media migration was performed. The read-only production snapshot remains
`0.24.1` at schema `20260721_0008`, with writes disabled and no active
candidate or deployment transaction.

## Validation results

| Gate | Result | Evidence |
| --- | --- | --- |
| Exact-head non-MySQL pytest collection | Pass | `1275 passed, 10 skipped, 8 warnings` in `147.72s`; one `pytest -n 8 --dist=worksteal --ignore=tests/integration` invocation. |
| Disposable MySQL integration | Pass | Fresh `eoat_atlas_test` reset through Alembic head, `20260729_0009 -> 20260721_0008 -> 20260729_0009` round trip, then `143 passed, 1 skipped, 1 warning` in `248.79s`. |
| Disposable MySQL teardown | Pass | The allow-listed loopback database and run-specific runtime/migration accounts were dropped after the integration suite. |
| Reset-target safety | Pass | `tests/test_reset_mysql_test_database.py`: `8 passed`; reset now permits only `eoat_atlas_test` on `127.0.0.1`, `::1`, or `localhost`, and rejects invalid account lengths before connecting. |
| Web static checks | Pass | `pnpm run typecheck`, `pnpm run lint`, `pnpm test` (`41 passed`), and `pnpm run build`. |
| Browser fixture checks | Pass with bounded skips | Playwright: `12 passed, 4 skipped`. Skips require a supplied live base URL or an explicitly requested visual-capture run; neither was supplied. |

The test warning in the Python suites is the existing FastAPI/Starlette
TestClient deprecation notice. It is not a test failure.

## Full-suite investigation

The original serial invocation stopped near photo-service tests with exit code
`124`. Controlled subset runs of `test_photo_indexing.py` and
`test_photo_service.py` completed (`30 passed`), so neither module was a
minimal reproducer. The observed `124` was caused by the local command/task
execution envelope: short tool windows and a temporary Windows scheduled task
configured with `StopOnIdleEnd=true` terminated the process before the serial
collection could finish. It was not a pytest assertion, Python exception, Qt
crash, or PhotoService lifecycle defect.

The acceptance run used one exact non-integration collection with eight
isolated pytest workers and generated JUnit output. It completed normally in
`147.72s` with exit code zero. No speculative PhotoService production patch was
introduced. Temporary runner logs and JUnit receipts remain outside the
repository; temporary scheduled tasks were removed after validation.

## Source parity verification

| Area | Verification evidence | Status |
| --- | --- | --- |
| Home search and global command palette | Fixture browser checks cover home-local input, `Ctrl+K`, overlay focus/escape, and restored Library state. | Verified |
| Profile URL tabs and Library filtering | `EntityProfilePage`, `EoatProfilePage`, `DiscoveryPage`, and browser deep-link tests passed. | Verified |
| Settings and Danger Zone access | `SettingsPage` verifies controls remain locked without a real administrator session. | Verified, LDAP activation deferred |
| Fit Check | Browser fixture verifies three selectable inputs and non-persistent evaluation; MySQL integration verifies server-truth routes. | Verified |
| Relationships and Machine overview | Machine browser fixtures verify deduplicated relationship cards, semantic empty states, overview display, and no exposed sentinels. | Verified |
| Governed media | `web_content.py` requires server-only approved roots and fails closed; fixture tests verify browser-safe media routes. | Verified in source; production source not configured |
| Physical EOAT identity | MySQL integration exercises physical UUIDs and alias fail-closed semantics at schema `20260729_0009`. | Verified |
| Subtitle and density presentation | Fixture browser tests cover profile/Library presentation across desktop, tablet, and phone sizes. | Verified |

The complete requirement-level evidence is maintained in the
[feature-verification matrix](EOAT_0252_FEATURE_VERIFICATION_MATRIX.md). During
this recovery, Fit Check was strengthened from three role-fixed controls to
three typed universal entity slots; automated tests cover role swapping and
all six selection orders.

## Capacity and media readiness

The attached `press_capacity.xlsx` has now been inspected read-only and used
for a governed non-mutating Plant 4 dry run. Its SHA-256 is
`2254269d4eabfd3478a6404005e4efdc850e3223e3ed6882b4bdbd0d71a785e3`.
With the explicit supplemental `master_press_list.xlsx` input, all 54 grouped
press headings parse, including the six headings that omit tonnage. No current
Plant 4 Atlas machine catalog was supplied, so all 54 normalized candidates,
including Machine 27 at `P4 Capacity` row 99, are fail-closed
`REVIEW_REQUIRED`/`NO_CANONICAL_MACHINE_MATCH` decisions. The plan proposes
zero writes and is not safe to execute. The full human review and a pointer to
the immutable machine-readable receipt are in
[the capacity dry-run review](EOAT_0252_PRESS_CAPACITY_DRY_RUN.md).

The importer records SHA-256, per-sheet headers and layout,
formula/hidden-cell/merged-range metadata, and every exact, unmapped, or
conflicted source-to-machine decision with source sheet and row locations. It
never uses fuzzy mapping and remains dry-run by default.

The remaining canonical-catalog dependency has now been completed through the
existing production API's read-only machine contracts. Production was observed
at `0.24.1`, schema `20260721_0008`, with writes disabled. The sanitized
catalog contains 56 active `P4` records and no existing capacities. The
catalog-aware dry run maps 52 of 54 source sections by exact canonical machine
number to future capacity-only updates; source machines 24 and 64 remain
unmapped and review-required. It proposes no inserts, relationship changes, or
executed writes. The catalog receipt, full review, Machine 27 proof, and
exception report are maintained in
[the canonical catalog receipt](EOAT_0252_CANONICAL_CATALOG_RECEIPT.md),
[the canonical mapping review](EOAT_0252_CANONICAL_CAPACITY_MAPPING.md), and
[the exception report](EOAT_0252_CAPACITY_MAPPING_EXCEPTIONS.md).

The six remaining discrepancies were reconciled without production mutation.
Presses 24 and 64 remain excluded pending identity governance; Machines 6, 70,
and 72 remain null without an approved source; Machine 8 has a 50-ton master
list reference but remains excluded until its independent-source scope is
approved. The 52 exact mappings are packaged as a non-executable,
drift-protected candidate. See
[the reconciliation](EOAT_0252_CAPACITY_EXCEPTION_RECONCILIATION.md),
[the decision packet](EOAT_0252_CAPACITY_HUMAN_DECISION_PACKET.md),
[the final candidate](EOAT_0252_FINAL_CAPACITY_IMPORT_CANDIDATE.md), and
[the policy template](EOAT_0252_CAPACITY_IMPORT_POLICY.md).

The default sanitized media root also does not exist locally. Browser media
delivery remains safely unavailable until an approved server-side source root
and mapping are supplied. This is a readiness dependency, not a reason to
weaken the fail-closed content policy or to mutate production.

The required next human action is to complete the controlled
[media-source manifest template](EOAT_MEDIA_SOURCE_MANIFEST_TEMPLATE.md) with
the approved source owner and server-side root. The template keeps the root
out of browser-visible configuration and captures identity, approval, and
read-only-mount evidence.

## Remaining predeployment dependencies

- Resolve workbook source machines 24 and 64 against the controlled Plant 4
  machine catalog before any future capacity execution; no alias or machine
  creation may be used to bypass this review.
- Supply and approve the production media root/mapping before governed media
  can be activated.
- The LDAP source implementation and anonymous preflight are now recorded in
  `EOAT_0252_LDAPS_*.md`. The endpoint resets each tested connection during
  TLS negotiation; activation remains fail-closed pending the precise IT
  network/policy action and administrator-group mapping in
  `EOAT_0252_LDAPS_REMAINING_IT_INPUTS.md`.
