# EOAT Atlas Admin Phase 4 Local Performance Evidence

Scope: one local HTTP run through the Vite proxy/API process pair backed by
the protected loopback route to `eoat_atlas_test`. These are observability
figures, not a production SLO or capacity certification.

| Operation                       | Status | Elapsed time |
| ------------------------------- | ------ | ------------ |
| Diagnostics                     | 200    | 567.1 ms     |
| Integrity scan                  | 200    | 558.9 ms     |
| Bounded audit JSON export       | 200    | 435.5 ms     |
| Selected-section support bundle | 200    | 625.4 ms     |

All four requests completed below one second in this isolated acceptance run.
The audit export used the login request ID after an unbounded export correctly
failed with `EXPORT_SCOPE_TOO_LARGE`; Phase 4 does not relax that guard merely
to improve a benchmark.

Browser responsiveness was also checked at 375x812 and 768x1024 after a live
fixture recovery. Both preserved the operation state and the mobile/tablet
layouts; the viewport override was reset after the check.
