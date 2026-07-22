# Phase 3 deployment controls

Phase 3 is implemented as two intentionally separate trust domains:

- The unprivileged updater verifies an immutable GitHub release, runs the
  existing strict production preflight, transfers only the verified artifact,
  manifest, and checksum to a non-final incoming location, and asks for one
  structured helper operation.
- The root-owned helper has a fixed operation allowlist.  It accepts neither a
  shell command nor caller-provided paths, service names, environment data, or
  database credentials.  It is the only component permitted to create the
  deployment lock, extract a release, provision a locked virtual environment,
  atomically change `current`, or restart `eoat-atlas.service`.

## State machine and durable evidence

The helper writes root-owned JSON transaction records under
`/opt/eoat-atlas/shared/deployment-transactions`, receipts under
`/opt/eoat-atlas/shared/deployment-receipts`, and an exclusive lock at
`/var/lock/eoat-atlas-deploy.lock`.  State transitions are append-only events:

`CREATED -> LOCK_ACQUIRED -> BACKUP_CREATED -> ARTIFACT_TRANSFERRED ->
ARTIFACT_VERIFIED -> RELEASE_EXTRACTED -> RUNTIME_READY ->
STAGED_VALIDATED -> ACTIVATION_STARTED -> ACTIVATED -> SERVICE_RESTARTED ->
HEALTH_VALIDATED -> COMPLETED`.

The non-mutating `recover` operation reports the required bounded action for
an interrupted transaction; it never guesses, deletes a stale lock, or
silently changes a release.  `abort` is available only before activation.
`rollback` is available only for an activated transaction and restores the
recorded `previous` release.  A failed rollback health probe preserves the
lock and records `MANUAL_INTERVENTION_REQUIRED`.

## Gates

Before staging, the updater requires a trusted OpenSSH host key, complete
GitHub release assets, external and embedded manifest agreement, checksum and
archive-safety validation, no Phase 2 blocking deployment-truth violation,
known compatible runtime/disk facts, and a verified `NOT_REQUIRED` migration
decision.  Phase 3 intentionally refuses a migration-bearing release until a
separate owner-approved backup/restore and migration runbook is supplied; it
does not treat an application rollback as database rollback.

The helper repeats server-side SHA-256 verification, parses the external
manifest/checksum, compares its canonical core to the embedded manifest,
rejects traversal/symlink/device/FIFO archive entries, requires runtime source
and `requirements.lock`, uses `pip install --require-hashes`, and imports the
staged API before the release directory is promoted.

## Migration-bearing releases

`--stage-only` remains intentionally limited to `NOT_REQUIRED` migrations. A
release that declares a schema change uses the separately installed helper v2
workflow: `prepare-migration`, `migration-backup`,
`migration-verify-backup`, `migration-stage`, `migration-preflight`,
`migration-apply`, `migration-verify`, then the existing explicit `activate`.
The root helper derives the production database, backup location, predecessor,
target revision, migration environment, and release path from its protected
transaction and package manifest. Operators cannot supply a command, URL,
database name, backup file, revision, service name, or environment value.

The transaction records `PACKAGE_VERIFIED`, `BACKUP_STARTED`,
`BACKUP_CREATED`, `BACKUP_VERIFIED`, `STAGED_VALIDATED`,
`MIGRATION_PREFLIGHT_PASSED`, `MIGRATION_STARTED`, `MIGRATION_COMPLETE`, and
`MIGRATION_VERIFIED` before activation. A failed migration preserves the lock
and receipt for the constrained `downgrade-migration` or `restore-backup`
operation. See
[the administrator handoff](../deployment/privileged/ADMINISTRATOR_MIGRATION_HELPER.md)
for installation and recovery details.

## Operator commands

All active commands require a verified non-secret server configuration and a
preinstalled helper.  They retain OpenSSH `BatchMode=yes` and
`StrictHostKeyChecking=yes`.

```powershell
# Stages only. It does not modify current, restart a service, or run a migration.
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json deploy-latest --stage-only

# An explicit second operator decision is required for any activation.
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json activate DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json deployment-status DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json rollback DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json recover DEPLOYMENT_ID
```

Each local invocation writes a receipt below
`.local/active-deployment-receipts`.  Stage and activation receipts are
separate evidence; neither command updates Git, creates a GitHub release, or
changes NGINX.

## One-time privileged bootstrap

The human administrator installs the root-owned helper using the exact
procedure in [privileged helper README](../deployment/privileged/README.md).
It creates only the helper, its narrowly scoped sudo rule, and dedicated
control directories.  It must be followed by `sudo -l -U kgray`, `visudo -cf
/etc/sudoers.d/eoat-atlas-deploy`, and a read-only helper status operation.
No deployment or service restart is part of bootstrap.

The currently approved reverse proxy remains the internal HTTP endpoint on
port 80.  Missing HTTPS/TLS on port 443 is a non-blocking infrastructure
warning for deployment automation, but should be resolved before broad
browser/mobile rollout or any exposure beyond the approved internal network.
