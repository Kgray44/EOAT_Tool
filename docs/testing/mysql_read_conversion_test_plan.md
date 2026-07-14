# MySQL Read Conversion Test Plan

The phase is tested at four layers:

1. Import: checksum/source immutability, batch/row/issue traceability, candidate deferral, duplicate prevention, idempotent safe stop, and zero fabricated parts/installations.
2. API: system endpoints, pagination/filtering/search, profiles/relationships/history/documents/photos, Fit Check, Setup Packet, snapshot/cursor, errors, schema compatibility, and runtime-account restrictions.
3. Gateway/cache: contract mapping, Deep and Standard Refresh, atomic replacement, offline reads, incompatible server blocking, independent caches, and connection recovery behavior.
4. Application isolation/parity: both UI workers avoid `load_atlas_data` in `mysql_api`; the gateway contains no MySQL driver/credentials; identifier/value/relationship/profile/Fit Check/Setup Packet outputs are compared to legacy evidence.

Unexpected parity classifications fail the validation runner. Expected differences require evidence and remain visible in JSON/Markdown reports.

