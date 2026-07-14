# MySQL Write Conversion Test Plan

Use only `eoat_atlas_test`, freshly recreated by the allowlisted reset utility. Test direct API authorization, asset CRUD/archive, compatibility validation, location locking, audit/maintenance completion, document/photo file checks, annotations/tags, Fit Check history, application instances, optimistic conflicts, idempotent replay/body mismatch, transaction rollback, change-feed atomicity, offline blocking, cache-after-commit behavior, independent caches, cache rebuild, and bounded snapshot query count.

Then run the prior foundation/read/outage/parity suite against `eoat_atlas_dev`, verify workbook and annotation-source checksums, run Alembic drift checks, compile/lint scoped code, and inspect the live schema. Blocked/skipped tests are reported separately and never counted as passes.
