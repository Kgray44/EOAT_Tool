# Data Freeze and Delta Strategy

The rehearsal uses a hard freeze because the source set is small and import time is short. At T-24 hours, announce the window and resolve blocker-class issues. At T-30 minutes, stop legacy application writes, close the workbook, and record file size, modified time, and SHA-256 for the master workbook, Robot workbook, SQLite database, and referenced photo files. Copy them into an immutable rehearsal directory and import only those copies.

Before authority changes, compare the final hashes with the announced freeze hashes. Any changed workbook or SQLite hash is a stop condition. Photo additions are allowed only if their workbook metadata is included in the same final snapshot. A source change after the snapshot requires a new snapshot UUID and a clean database import; it is never patched silently.

For production, a delta window may be used only if every post-snapshot legacy change is captured in an operator log with entity, old value, new value, author, and timestamp. The delta must be replayed through the API after base import and reconciled against the API change feed. Unlogged legacy changes force rollback to the freeze step.

The rehearsal snapshot UUID is recorded in `reports/cutover_rehearsal/frozen_source_manifest.json`. Original sources remain byte-identical and authoritative only for rollback; the rehearsal copies are explicitly non-production.
