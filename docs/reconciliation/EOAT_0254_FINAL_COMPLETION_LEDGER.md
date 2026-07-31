# EOAT Atlas 0.25.4 final completion ledger

This ledger is the durable execution record for the non-LDAPS completion goal.
It is updated from current source and validation evidence; it never authorizes
production mutation by itself.

| ID | Description | Status | Implementation files | Tests / evidence | Commit | Remaining action | Final result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | Preserve current branch/worktree and governed 0.25.4 transition | PASS | `app/atlas/version.json`, `release_history.json` | Version checker passed at 0.25.4; baseline `5714e208` preserved | Uncommitted | Commit source transition | Pending exact-head |
| R02 | Relationship semantic mapping and expandable evidence | IN_PROGRESS | `web/src/components/profile/*` | ProfileBlocks: 11 passed; focused Machine browser: 7 passed; explicit incompatible state prevents substring misclassification | Uncommitted | Preserve richer source provenance where present; exact-head tests | Pending |
| R03 | Responsive relationship-card layout | IN_PROGRESS | `web/src/styles/global.css`, ProfileBlocks | Chromium layout fixture: 1 passed covering zero/one/two/three/many, long text, desktop, mobile, font scale, no overflow | Uncommitted | Exact-head browser regression and final receipt linkage | Pending |
| R04 | Bounded authoritative Library selectors | IN_PROGRESS | API app/repository/contracts; `LibraryPage.tsx` | Discovery suite: 6 passed; catalog options: 3 passed; machine options are plant-qualified | Uncommitted | Complete selector/filter/browser matrix | Pending |
| R05 | Machine Overview field parity | IN_PROGRESS | API contracts/repository; `MachineProfilePage.tsx`; Machine browser fixture | Entity-profile: 4 passed; Machine browser: 7 passed with P4 Machine 27, null live capacity, robot system, and no synthetic 165 | Uncommitted | Add governed candidate-to-live import evidence and parity receipt | Pending |
| R06 | Universal Fit Check retention | PASS | `FitCheckPage.tsx`, API routes | Discovery suite executes six orders | Existing + uncommitted regression | Exact-head regression | Pending exact-head |
| R07 | Content-density audit | NOT_STARTED | - | - | - | Audit desktop/web surfaces and record decisions | Pending |
| R08 | Desktop/browser parity receipt | NOT_STARTED | - | Existing fixture tests are insufficient as side-by-side evidence | - | Perform controlled comparison and document differences | Pending |
| R09 | Media readiness | IN_PROGRESS | `web_content.py`, existing media template | Existing source is fail-closed; no approved accessible root evidenced | Existing | Inspect governed references and classify | Pending |
| R10 | Capacity candidate readiness | IN_PROGRESS | `tools/migration/*`, reconciliation receipts | 39 focused backend tests passed; existing immutable hashes retained | Existing | Revalidate against exact source/policy | Pending |
| R11 | Restricted production helpers | IN_PROGRESS | `governed_data_operations.py`, deploy helper dispatch, root-owned policy templates | New data-helper and existing helper suite: 37 passed; rejects caller SQL, database, command, policy/path control, drift, stale/missing dry run | Uncommitted | Validate installed Linux policy/receipt flow and exact-head suite; no production mutation before release candidate | Pending |
| R12 | Exact-head validation | PASS | validation scripts | Non-MySQL: 1,311 passed/10 skipped; web: 52 passed; focused Chromium: 8 passed; loopback MySQL final head: 137 passed/7 skipped/1 warning; final LDAP unit: 11 passed | Uncommitted receipt | Package and verify coordinated release artifacts | Exact head validated |
| R13 | Coordinated release candidate | NOT_STARTED | release tooling | - | - | Package/hash exact committed source | Pending |
| R14 | Controlled production deployment | NOT_STARTED | governed deployment tooling | Historical baseline receipt: 0.24.1 / 0008 / writes disabled | - | Only after R12 and R13 PASS | Pending |
| R15 | Final docs, commit, push, parity | NOT_STARTED | reconciliation docs | - | - | Complete receipts, push, verify clean 0 0 | Pending |

## Frozen boundary

LDAPS remains intentionally disabled, fail-closed, and outside this release.
No entry in this ledger authorizes an LDAPS network probe, credential test,
certificate change, group mapping, or activation.
