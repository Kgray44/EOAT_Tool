# MySQL Backup and Restore Plan

Use the migration account and `mysqldump --single-transaction --no-tablespaces --routines --triggers --set-gtid-purged=OFF`. Passwords are passed through the process environment and never command-line logs. Store the dump outside the repository, record SHA-256 and size, and restrict access to the cutover operators.

Verification is an actual restore, not a syntax check. Create only the allowlisted disposable database `eoat_atlas_staging_restore_check`, restore the dump, compare all business/import/audit/feed counts, verify the Alembic revision, then drop the disposable database. A hash mismatch, restore error, count mismatch, or missing schema revision blocks cutover.

Retention: preserve the pre-write backup through the rollback window and the post-import/pre-authority backup through final acceptance. A production procedure must add encrypted storage, access review, and the site retention policy; this local rehearsal does not claim those production controls.
