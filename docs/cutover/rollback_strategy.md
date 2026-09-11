# Rollback Strategy

Before MySQL authority is enabled, rollback is immediate: keep legacy sources unchanged, stop the staging API, discard/reset the isolated database, and continue legacy mode.

After MySQL writes begin, stop clients and API writes first. Record the cutover UUID and final change-feed cursor. Export all post-cutover changes to JSON/CSV, preserve a post-write database backup, and classify each write by its legacy representation. Restore the verified pre-write MySQL backup only into an allowlisted database. Re-enable legacy authority only after all user-visible post-cutover writes are either applied to controlled legacy copies or entered in a signed manual reconciliation queue.

Compatibility, asset fields, and annotations can be represented in controlled workbook/SQLite copies. Transactional movements, maintenance, document lifecycle, profile-photo changes, and archives require operator-reviewed reconciliation because the legacy model cannot represent all server audit/concurrency semantics. No change may be silently discarded.

The rollback window is 24 hours in the rehearsal session. After the window, rollback requires change-management approval and a new reconciliation plan.

## EOAT Atlas 0.27.0 onboarding release

The production baseline is schema `20260828_0017`; the approved forward chain
ends at `20260910_0019`. Retain the current production application release as
the application rollback target. If rollback is required, first disable
`EOAT_ONBOARDING_ENABLED`, preserve the deployment receipt and verified backup,
and restore the retained application release under the governed deployment
procedure. `20260910_0019` is additive: its downgrade drops
`eoat_engineering_profiles.command_center_data` and deliberately does not
delete controlled lookup rows, because they can pre-exist or be in use. Never
rewrite a migration to make an old release note match the chain.
