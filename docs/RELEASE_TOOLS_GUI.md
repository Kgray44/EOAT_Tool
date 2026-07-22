# EOAT Atlas Release Tools GUIs

`run_release_packager.py` opens **EOAT Atlas Release Packager**. It presents repository status, release validation, a dry-run package rehearsal, and the existing release-manager publication path. `run_server_updater.py` opens **EOAT Atlas Server Updater**. `run_release_tools.py` opens a small launcher for both.

Run from the repository root with the same Python environment used for EOAT Atlas:

```powershell
python run_release_tools.py
python run_release_packager.py
python run_server_updater.py
```

PySide6, Git, and (for GitHub release inspection/publication) GitHub CLI must be available. Server inspection and deployment operations require a selected non-secret JSON server configuration. The GUI deliberately does not read SSH passwords, private keys, database passwords, environment files, or tokens. OpenSSH configuration, agent, and `known_hosts` are used unchanged.

## Safe normal workflow

1. In the packager, refresh repository status and run validation.
2. Enter a proposed version and run the dry-run package rehearsal. No tag, GitHub release, or production change occurs in this mode.
3. Publication remains disabled until the repository is current and clean and validation passes. The operator must type `PUBLISH X.Y.Z` exactly before the established backend is called.
4. In the updater, choose a non-secret configuration, inspect the server, check/inspect a release, and run a deployment rehearsal.
5. Stage is available only after a matching successful rehearsal, a trusted SSH host key, no blockers, privileged-helper availability, and a backend-confirmed `NOT_REQUIRED` migration state. **STAGING DOES NOT ACTIVATE THE RELEASE.**
6. Activation, abort, recovery, and rollback remain bounded by the existing server state machine. Their exact case-sensitive confirmations include the deployment ID.

The deployment rehearsal prominently remains a dry run: **NO SERVER CHANGES WILL BE MADE**. A verified artifact alone never makes deployment ready. Migration-required, unknown, or blocked releases cannot be staged or activated by this interface.

## Receipts, settings, and troubleshooting

The receipt viewer presents summary, warning, blocker, artifact, server, migration, deployment-plan, and raw JSON tabs without modifying receipt files. Existing backend receipt locations remain authoritative, including `.local/deployment-preflight-receipts` and `.local/active-deployment-receipts`.

GUI-only settings live under `%LOCALAPPDATA%\EOAT_Atlas\release_tools_gui`. Only window/operator preferences such as a non-secret configuration path may be saved; secret-like setting names are rejected. If an operation fails, the dialog states that a mutating operation may need status/receipt inspection instead of asserting production is unchanged.

The GUI is an interface layer, not a replacement for the established CLIs. `python tools/release_manager.py ...` and `python tools/server_updater.py ...` remain fully supported and are the appropriate fallback for automation or detailed scripting. Future executable packaging can add these three roots as PyInstaller entry points; no production installer was created by this change.
