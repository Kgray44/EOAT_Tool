# Local MySQL Development Setup

## Installed environment

- MySQL Community Server 8.4.9 LTS portable ZIP distribution.
- Base: `%LOCALAPPDATA%\EOAT Atlas Development\mysql-8.4.9-winx64`.
- Data: `%LOCALAPPDATA%\EOAT Atlas Development\mysql-data`.
- Listener: `127.0.0.1:3306`; MySQL X protocol disabled.
- Credentials: `%LOCALAPPDATA%\EOAT Atlas Development\database.env`, current-user ACL only.
- Databases: `eoat_atlas_dev` and isolated `eoat_atlas_test`.
- Accounts: `eoat_atlas_migrator@127.0.0.1` and `eoat_atlas_app@127.0.0.1`.

The normal EOAT Atlas desktop application has not been given these credentials and is not connected to MySQL in this phase.

## Start, verify, and stop

From the repository root:

```powershell
scripts\setup\start_local_mysql.ps1
scripts\setup\verify_local_mysql.ps1
scripts\setup\stop_local_mysql.ps1
```

Upgrade or check schema:

```powershell
scripts\database\upgrade_database.ps1
scripts\database\check_schema_version.ps1
```

## Recreate on another workstation

1. Prefer the approved MySQL 8.4 LTS installer when local policy permits: `winget install --id Oracle.MySQL --exact`.
2. If elevation is unavailable, download the official `mysql-8.4.9-winx64.zip` and extract it below `%LOCALAPPDATA%\EOAT Atlas Development`.
3. Initialize a new data directory with `mysqld --initialize-insecure`, bind only to `127.0.0.1`, immediately assign a strong root password, and never expose the temporary empty-password state.
4. Run `scripts/setup/create_local_dev_database.sql` as an administrator.
5. Create a migrator account with privileges limited to `eoat_atlas_dev.*` and `eoat_atlas_test.*`.
6. Create a runtime account with only `SELECT, INSERT, UPDATE, DELETE` on `eoat_atlas_dev.*`; do not grant `EXECUTE`.
7. Store generated passwords outside Git and load them through the documented environment variables.
8. Run the Alembic upgrade and verification scripts.

The first MSI attempt in this execution returned Windows Installer code 1602, so the non-admin portable distribution was used. MySQL is development infrastructure and must not be bundled in the desktop installer.

