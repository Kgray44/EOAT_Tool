# EOAT Atlas 0.25.4 requirement matrix

| Requirement | Current result | Evidence | Gate |
| --- | --- | --- | --- |
| Governed 0.25.4 source | PASS at source commit `445fcbd62a` | Version checker, release history, release-format commit | Production activation remains separate |
| Relationship semantics | PASS for implemented mapping | 11 component tests, 7 Machine browser tests | Preserve source provenance if data contract expands |
| Relationship layout | PASS for focused layout contract | Isolated Chromium 1 passed | Retain bounded browser-matrix exception |
| Library selectors | PASS for source contract | 3 API tests, 6 Discovery tests | Full representative-data performance remains unrun |
| Machine Overview | PASS for source contract | 4 component tests, 7 Machine browser tests | Production candidate/import proof pending |
| Universal Fit Check | PASS retained | Discovery tests include all six orders | Exact-head backend suite pending |
| Content-density audit | PASS for source-level audit | `EOAT_0254_CONTENT_DENSITY_AUDIT.md` | Live side-by-side remains parity gate |
| Desktop/web parity | Deterministic 27-state comparison complete; reviewer gate blocked | `EOAT_0254_DESKTOP_WEB_PARITY_RECEIPT.md` | Direct review and difference dispositions |
| Media readiness | PASS as `NOT_LOCATED` classification | `EOAT_0254_MEDIA_READINESS.md` | Owner-approved source required before migration |
| Capacity readiness | IN_PROGRESS | Immutable historical evidence and policy boundary | Fresh catalog and 0.25.4-bound candidate required |
| Restricted helper | PASS for source/harness boundary | 37 helper tests | Installed Linux policy validation required before production use |
| Exact-head validation | PASS | Non-MySQL: 1,311 passed/10 skipped; web: 52 passed; focused browser: 8 passed; exact-head MySQL: 138 passed/7 skipped/1 warning; 0008→0009→0008→0009 recovery passes | No browser-matrix relaunch under owner exception |
| Release candidate | PASS | Hash-validated deployment tar and server zip from `b67d9d`; schema `20260729_0009` | Do not tag, publish, or deploy without separate authority |
| Production deployment | BLOCKED_EXTERNAL | Baseline verified 0.24.1/0008/writes-disabled; candidate ready; installed root policy, fresh production catalog/backup/dry-run, approved media source, controlled desktop/browser session, and host access are absent | Use only governed activation/data-operation interfaces after all gates |
| Final closure | BLOCKED_EXTERNAL | `EOAT_0254_FINAL_COMPLETION_RECEIPT.md` records source/package closure and production non-execution | Push documentation and retain branch parity; no mainline convergence authorization |

LDAPS remains intentionally deferred and is not a non-LDAPS release gate.
