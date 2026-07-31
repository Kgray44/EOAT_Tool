# EOAT Atlas 0.25.4 final completion ledger

This ledger is the durable execution record for the non-LDAPS completion goal.
It is updated from current source and validation evidence; it never authorizes
production mutation by itself.

| ID | Description | Status | Implementation files | Tests / evidence | Commit | Remaining action | Final result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | Preserve current branch/worktree and governed 0.25.4 transition | PASS | `app/atlas/version.json`, `release_history.json` | Version checker passed; baseline `5714e208` preserved | `445fcbd` | Keep source/candidate identifiers paired | PASS |
| R02 | Relationship semantic mapping and expandable evidence | PASS | `web/src/components/profile/*` | 11 component tests; 7 focused Machine browser tests | `445fcbd` | Future provenance may extend contract | PASS for source |
| R03 | Responsive relationship-card layout | PASS | `web/src/styles/global.css`, ProfileBlocks | Chromium layout: 1 passed for zero/one/two/three/many, long text, desktop/mobile, font scale, overflow | `445fcbd` | Preserve browser-matrix exception | PASS for focused contract |
| R04 | Bounded authoritative Library selectors | PASS | API app/repository/contracts; `LibraryPage.tsx` | Discovery: 6 passed; catalog options: 3 passed; plant-qualified machine values | `445fcbd` | Representative-data performance separate | PASS for source |
| R05 | Machine Overview field parity | PASS for source | API contracts/repository; `MachineProfilePage.tsx` | 4 component tests; 7 focused browser tests; null capacity remains truthful | `445fcbd` | Candidate-to-live import remains blocked | No data import |
| R06 | Universal Fit Check retention | PASS | `FitCheckPage.tsx`, API routes | Discovery suite executes six orders; release builder reran web tests | `445fcbd` | None in source scope | PASS |
| R07 | Content-density audit | PASS for source | reconciliation audit | Desktop/browser treatment decisions recorded | `445fcbd` | Visual proof is R08 | PASS for stated scope |
| R08 | Desktop/browser parity receipt | BLOCKED_EXTERNAL | `EOAT_0254_DESKTOP_WEB_PARITY_RECEIPT.md` | Source comparison complete; focused tests are not side-by-side proof | Recorded on integration branch | Controlled visual session/difference register | No visual-equivalence claim |
| R09 | Media readiness | PASS as `NOT_LOCATED` | `web_content.py`, media template | Fail-closed; no approved accessible root | `445fcbd` | Owner-approved source before migration | No media copied |
| R10 | Capacity candidate readiness | BLOCKED_EXTERNAL | migration tools, readiness receipt | 39 focused tests; historical candidate is older-source-bound | `445fcbd` | Fresh GET-only catalog and exact-source candidate/policy | No capacity imported |
| R11 | Restricted production helpers | PASS for source/harness | governed helper, policy templates | 37 tests reject caller-controlled operations and stale/missing dry run | `445fcbd` | Validate installed Linux policy/receipt flow | Not installed or run in production |
| R12 | Exact-head validation | PASS | validation scripts | 1,311/10 non-MySQL; 52 web; 8 focused Chromium; 137/7/1 MySQL; post-test change web-format only | `445fcbd` | No complete browser matrix by owner exception | PASS |
| R13 | Coordinated release candidate | PASS | release tooling | Self-validated deployment tar and server zip, exact `445fcbd`, schema `20260729_0009` | `445fcbd` | Do not tag/publish/deploy without authority | PASS |
| R14 | Controlled production deployment | BLOCKED_EXTERNAL | governed deployment tooling | Candidate ready; external safety gates absent | - | Installed policy, fresh catalog/backup/dry run, media authority, visual parity, host access | Not executed |
| R15 | Final docs, commit, push, parity | PASS for branch evidence | reconciliation docs | Receipts pushed; branch parity is `0 0` | Integration branch | Production gates and mainline convergence remain external/unauthorized | Branch evidence complete |

## Frozen boundary

LDAPS remains intentionally disabled, fail-closed, and outside this release.
No entry in this ledger authorizes an LDAPS network probe, credential test,
certificate change, group mapping, or activation.
