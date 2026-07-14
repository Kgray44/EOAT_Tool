# Multi-Client Write Test Plan

Build Client A and Client B with distinct SQLite cache paths against one API/database. Deep-refresh both, update the same machine from A, attempt B's stale version, verify 409/no cache mutation, then Standard Refresh B and compare values. Delete and rebuild B's cache and confirm A is unaffected. Separately, retry a committed keyed request and verify the original result. Conflicting location moves use the EOAT row version plus database active-location constraints.
