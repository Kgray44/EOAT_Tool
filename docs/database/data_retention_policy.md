# Data Retention and Archival Policy

- EOATs, machines, robots, tools, parts, compatibility evidence and documents are archived (`is_active = false`, archive actor/time) rather than normally deleted.
- Installation/storage history, Fit Check results, completed audits, entity history, change-audit events and approved import records are not rewritten or physically deleted by normal users.
- `change_feed` is append-only. A future retention job may compact old feed rows only after all supported client cursors and backup/audit requirements are satisfied.
- An unapproved test/import batch may be physically removed by an administrator if no approved permanent record depends on it.
- The isolated `eoat_atlas_test` database is disposable and never contains production authority.
- SQLite annotation records remain permanent legacy data until a separately validated server migration is completed.
- Large files remain on controlled network storage. Temporary file unavailability does not delete document metadata.
- Backup/restore requirements for the future IT-hosted service remain an IT handoff item; no production backup policy was changed in this phase.

