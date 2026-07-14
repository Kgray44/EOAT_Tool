# Optimistic Concurrency

Mutable entities expose `row_version`. PATCH/action requests carry `expected_row_version`; the service locks the row, compares versions, applies the change, increments the version, and returns the authoritative record. A stale request receives HTTP 409 with `STALE_RECORD_VERSION` and `current_record_version`. The gateway raises `ConcurrencyConflictError` and does not change its cache.

This applies to assets, compatibility records, annotations, tags, documents/photos (photo metadata uses its owning document version), audits, maintenance, installations, and entity-tag assignments. Location moves combine row versions with database locks and active-row uniqueness constraints.
