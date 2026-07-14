# MySQL Read Conversion Results

Date: 2026-07-13

- Foundation/schema suite: 8 passed, including 5 real MySQL tests and runtime DDL denial.
- Read-conversion integration suite: 11 passed (9 full-suite cases plus 2 added outage/recovery cases run after refinement).
- Ruff: passed for all migration/API/gateway and touched integration modules.
- Python compilation: passed.
- Data parity: no missing/extra supported identifiers, value mismatches, or relationship mismatches; one expected source-conflict class and one deferred SQLite-annotation class.
- Read parity: 335 matches, 3 expected normalization differences, 15 expected unresolved-source differences, 0 unexpected failures.
- Multi-client: two equivalent independent caches; client B deleted/rebuilt without affecting A; no desktop MySQL connection and no Excel access in `mysql_api` mode.
- Standard Refresh: passed at cursor 0 with zero changes.
- Deep Refresh: passed with 57 EOATs, 56 machines, 65 tools, 158 documents, and 158 photos.
- Offline: explicit `OFFLINE_READ_ONLY`; Home and search served from cache.
- Version mismatch: `INCOMPATIBLE_SERVER` and refresh blocked.

Measured warm API operations were approximately 56–138 ms; full snapshot approximately 2.93 seconds; Deep Refresh approximately 3.15 seconds. Cold API process startup from the network-share virtual environment was approximately 73 seconds and should be optimized before production packaging. Snapshot/profile assembly contains an N+1 optimization opportunity at larger scale.

The complete evidence is under `reports/mysql_import` and `reports/mysql_read_conversion`.
