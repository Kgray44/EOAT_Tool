# Phase 9 Local Production-Style Rehearsal Report

Local rehearsal result: **PASS_WITH_ACCEPTED_RISK**. Production remains **NO-GO / NOT AUTHORIZED** until production identity/security approval and human business UAT sign-off.

## Import and reconciliation

The empty staging database migrated to `20260714_0003`. Final frozen-source import produced 57 EOATs, 56 machines, 65 tools, 102 audits, 158 documents, and 158 photos. Compatibility counts are 87/65/88. Annotation import exactly matched 15 tags, 52 targets, 45 assignments, 11 notes, and 2 links with zero orphans and unchanged source checksum.

Parity has no missing/extra identifiers or relationship mismatches. Two documented differences are intentional: one conflicting cleanroom source value remains unknown, and the comparison utility labels permanent SQLite annotations as deferred even though the separate exact annotation import passed.

## Tests, UAT, performance, outage

MySQL tests: 30 passed, 0 failed (5 foundation, 11 read, 14 write). Automated UAT passed all 12 cases and exported 20 change-feed records. A controlled outage preserved cache reads, blocked writes without a queue, and recovered compatible health in 5.365 seconds.

## Package and rollback

The exact EOAT Atlas client and launcher were built from a local mirror of the checkpointed candidate to avoid UNC build latency. Launcher check, packaged-client smoke, uninstall, reinstall, and second smoke all passed. The installer ZIP hash is `0e6582a870a9b666aa7f66ef899b16309c7952fd0b31115550298ade2646b180`.

Pre-write rollback restored in 2.348 seconds with exact baseline counts. All 20 post-cutover records were classified; zero were unclassified. Four installation/maintenance events require a manual reconciliation queue because legacy storage cannot represent all server semantics. Original legacy sources remain unchanged.

Cleanup restored the actual isolated staging database to the pre-write baseline, removed UAT business rows, marked the cutover session rolled back, and stopped the staging API. Backups, frozen evidence, the installer candidate, and reports remain outside production for review.

No production database, deployment, configuration, source workbook, or real user authority was modified. Legacy synchronization code remains present.
