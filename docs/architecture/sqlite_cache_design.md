# Disposable SQLite API Cache

The default development cache is `%LOCALAPPDATA%/EOAT Atlas Development/eoat_atlas_api_cache_dev.db`. It is separate from the permanent legacy annotations database.

Cache schema version `1` stores JSON API contracts for EOATs, machines, tools, documents, and photos; lookup values; search support; change receipts; and metadata:

- API and cache versions
- Server schema/revision
- Creation, successful-sync, and full-refresh timestamps
- Last server-issued cursor

Standard Refresh checks compatibility and requests changes after the stored cursor. With no changes it advances metadata transactionally. If authoritative changes exist, this initial implementation reconciles through a full snapshot because change payloads are not yet embedded in the feed.

Deep Refresh builds and validates a `.building` database, retains the previous cache, atomically replaces only after validation, and restores the old file on failure. The cache contains no permanent unsynchronized edits and can be deleted/rebuilt independently.

