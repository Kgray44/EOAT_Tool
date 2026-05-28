# SQLite Audit Mirror Decision

Decision for Phase 5: do not add a workbook audit mirror yet.

Rationale:

- The app already has a local SQLite database for annotations, tags, ignored suggestions, and open-item states.
- Audit save/load behavior remains workbook-first, and Phase 5 is focused on validation and safe repair rather than changing the audit persistence model.
- Adding an audit mirror would introduce synchronization and privacy risk before there is a clear downstream reader that needs it.

Small foundation added instead:

- Validation findings are structured and exportable as JSON.
- Audit history records validation repair and workbook repair activity.
- Open Items can consume structured validation findings without copying workbook rows into SQLite.

Deferred mirror scope, if a later phase needs it:

- Audit ID and key non-sensitive audit fields only
- Compatibility source relationships
- Validation finding snapshots
- Audit history references
- Explicit rebuild/import command from the local workbook

Safety boundary:

- Do not mirror real company workbooks by default.
- Do not store mold numbers, part numbers, customer names, capacity data, downtime data, scrap data, private operational details, internal paths, photos, reports, logs, caches, or local configs in a committed database artifact.
