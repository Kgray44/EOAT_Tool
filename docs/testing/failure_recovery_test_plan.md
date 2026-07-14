# Failure and Recovery Test Plan

| Failure | Injection | Required invariant |
|---|---|---|
| Database unavailable before request | Override write-session dependency with `OperationalError` | normalized retryable 503; no write |
| Business validation in transaction | Unknown compatibility lookup | no relationship/audit/feed residue |
| Response lost after commit | Replay same idempotency key | original result; no duplicate |
| Offline client | API health failure adapter | gateway blocks before send; no cache/queue |
| Cache refresh after commit fails | cache repository raises during snapshot build | server result remains; refresh-required flag |
| Change-feed cache application fails | metadata update raises inside SQLite transaction | cursor unchanged; transaction rolled back |
| Document file unavailable | nonexistent path | 422; no document metadata |
| Stale edit | two independent client versions | 409; first writer remains authoritative |
