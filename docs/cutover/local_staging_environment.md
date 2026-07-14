# Local Production-Style Staging Environment

The rehearsal environment is intentionally isolated:

- database: `eoat_atlas_staging_local` on loopback only;
- separate `eoat_staging_migrator` and `eoat_staging_runtime` accounts;
- secrets: `%LOCALAPPDATA%\EOAT Atlas Staging\staging.env`, never Git;
- API: `127.0.0.1:8766`, `staging_local`, no reload/debug, writes disabled unless explicitly enabled;
- client: `mysql_api`, staging URL, staging identity, separate cache schema 2 files;
- source: read-only frozen copies under a rehearsal UUID;
- production defaults and deployment are unchanged.

Create/reset/verify/start/stop scripts live in `scripts/cutover`. Reset requires the exact marker `EOAT_STAGING_REHEARSAL_ONLY`; database and restore names are hard allowlisted. The local auth identities exist only for rehearsal and are forbidden in other environments.

PowerShell execution policy may require `powershell -ExecutionPolicy Bypass -File <script>` on this workstation. That is a workstation policy detail, not an application bypass.
