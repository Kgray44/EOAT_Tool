# Migration-capable restricted deployment helper

This package installs the root-owned helper required for a migration-bearing
EOAT Atlas deployment. It does **not** deploy an application, restart a
service, alter NGINX, or connect to MySQL during installation.

## Installed files

| Source | Destination | Owner/mode |
| --- | --- | --- |
| `eoat_atlas_deploy_helper.py` | `/usr/local/libexec/eoat-atlas/eoat_atlas_deploy_helper.py` | `root:root 0750` |
| `helper.manifest.json` | `/etc/eoat-atlas/deployment-helper.manifest.json` | `root:root 0640` |
| `eoat-atlas-deploy.sudoers` | `/etc/sudoers.d/eoat-atlas-deploy` | `root:root 0440` |

Verify the package checksum with `sha256sum -c helper.sha256`; the installer
does this before installation. It saves the prior files under
`/opt/eoat-atlas/shared/helper-backups/UTC-TIMESTAMP` and restores them if
sudoers validation or helper self-check fails.

## Installation and verification

```sh
sudo ./install_migration_helper.sh --source-dir /absolute/staged/privileged
sudo ./verify_migration_helper.sh
sudo -l -U kgray
```

The sudo policy permits only `/usr/bin/python3` executing the installed helper
with `--request-b64`; it does not grant a shell, generic Python, MySQL,
Alembic, service control, alternate paths, or caller-supplied environment.
Protected `/etc/eoat-atlas/migration.env` remains root-only and must contain
the approved production migration identity while keeping writes disabled.

## Rollback of the helper installation

```sh
sudo ./rollback_migration_helper.sh --backup-dir /opt/eoat-atlas/shared/helper-backups/UTC-TIMESTAMP
```

## Resume the already-verified 0.18.0 deployment

After administrator verification, a non-root operator uses the repository
client with the approved non-secret server configuration:

```powershell
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json --release-dir C:\safe\artifact-a prepare-migration 0.18.0
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json migration-backup DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json migration-verify-backup DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json migration-stage DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json migration-preflight DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json migration-apply DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json migration-verify DEPLOYMENT_ID
python tools/server_updater.py --server-config C:\safe\eoat-atlas-production.json activate DEPLOYMENT_ID
```

On a migration failure, use only `migration-downgrade` or `migration-restore`
with the same deployment ID. The helper derives the predecessor revision and
backup path from its lock-protected transaction; neither is accepted from the
operator.
