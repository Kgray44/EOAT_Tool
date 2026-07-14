# Production Cutover Runbook

This is a prepared runbook, not authorization to deploy.

## T-24 hours

Confirm approved release commit/artifact hashes, named roles, maintenance window, production authentication, monitoring, backup destination, rollback deadline, issue classifications, and UAT signatories. Announce the freeze.

## T-30 minutes

Stop legacy writes and close Excel. Capture source timestamps, sizes, and hashes. If they differ from the approved baseline, stop. Create the frozen snapshot and cutover-session UUID. Take and restore-test the pre-cutover MySQL backup.

## Import and validation

Create/migrate the target, run dry analysis, execute final workbook and SQLite imports, reconcile identifiers/relationships/counts/files, validate constraints and schema, and take the post-import backup. Any blocker invokes the pre-write rollback path.

## Authority switch

Start the production API with approved identity/network controls, verify health/version, deploy the signed launcher/client configuration, and enable writes for a limited pilot group. Confirm audit/change-feed entries and monitor errors, latency, connections, locks, and storage.

## Acceptance window

Run the signed UAT plan with at least two simultaneous clients. Record every issue and final cursor. Expand access only after incident commander, data steward, and business owner approve.

## Rollback

Freeze API writes, export post-cutover changes, preserve a post-write backup, apply the rollback decision matrix, reconcile every change into controlled legacy copies/manual queue, restore authority, and communicate status. Never overwrite the original freeze snapshot.

## Completion

Close the cutover session, retain evidence/backups per policy, remove temporary accounts/artifacts, and schedule legacy retirement as a separate approved phase. Do not delete legacy synchronization code in this runbook execution.
