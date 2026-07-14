# EOAT History Test Results

Date: 2026-07-14

## Passed

| Suite | Result |
|---|---:|
| MySQL write/history integration | 16 passed |
| MySQL read/API/cache integration after controlled import | 12 passed |
| MySQL schema/constraint/runtime-privilege foundation | 5 passed |
| History unit, gateway, UI, and PDF | 8 passed after final assertion normalization |
| Live development runtime/cache/PDF validator | PASS |
| Schema verifier and Alembic head check | PASS |

The only emitted warning is Starlette's dependency deprecation notice for `httpx`; it does not affect behavior. There are no failed or blocked History tests.

## Verified outcomes

- Development API: MySQL 8.4.9, API 1.3.0, schema `20260714_0004`, compatible.
- Schema: 49 total tables, 180 FKs, 249 indexes, 50 unique constraints, 21 checks; no verifier errors.
- Controlled import: 102 audit records created 102 traceable History events; workbook SHA-256 `207e166c3c75f4a517a47f572c84d683b3b7a194bb23b1f5649e97c5d76b7eac` remained unchanged.
- Live P4-EOAT-0001: seven events online, seven after cache deletion/rebuild, seven offline; identical source authority.
- Deep Refresh: 57 EOATs, 56 machines, 65 tools, 158 documents, 158 photos, 102 history events.
- Legacy isolation: zero workbook-open attempts through API-mode detail, history, refresh, and PDF path.
- PDF: two rendered pages, seven events, source/limitation labels, complete continuation content, no clipping or sensitive connection data.
- Visual states: eight states each at typical, compact 1024×640, and high-DPI 1280×720 render sizes, including light/dark.

Detailed machine-readable timings are in `reports/eoat_history/runtime_validation.json`; schema evidence is in `reports/eoat_history/history_schema_verification.json`.
