# Rollback Decision Matrix

| Condition | Before authority | After writes | Decision |
|---|---|---|---|
| Source checksum changed | Stop and resnapshot | N/A | No-go |
| Import/FK/constraint failure | Reset staging and correct migration | Freeze API, export changes | Roll back |
| Backup cannot restore exactly | Do not enable authority | Freeze writes; retain current DB | No-go/escalate |
| API unavailable, database healthy | Restart API; remain legacy | Clients use read cache, writes blocked; restart API | Continue if recovered within 15 minutes |
| Database unavailable | Remain legacy | Block writes; recover/restore; roll back if RTO exceeded | Incident decision |
| Client cache corrupt | Rebuild cache | Rebuild from server; no authority change | Continue |
| Stale-write conflicts | Expected test result | User refresh/retry | Continue |
| Unauthorized writes accepted | Stop | Freeze and roll back | Critical no-go |
| Critical data parity mismatch | Stop | Freeze, export, roll back | Critical no-go |
| Noncritical display/performance issue | Record owner/workaround | Monitor | Conditional go |

Incident commander owns the decision; database operator executes backup/restore; application lead controls API/launcher; data steward signs reconciliation; business owner signs UAT.
