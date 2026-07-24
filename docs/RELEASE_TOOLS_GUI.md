# EOAT Atlas Release Tools GUI — Phase 1

Run the GUI from the repository root:

```powershell
python tools\release_tools_gui.py
```

The application is a separate PySide6 shell with Packager and Updater pages.  Its adapter layer imports the existing `deployment.release_manager` and `deployment.server_updater` functions directly; the CLI entry points in `tools\release_manager.py` and `tools\server_updater.py` remain unchanged.

Phase 1 permits only status, validation, isolated package dry-run, server configuration validation, release inspection, read-only server inspection, and dry-run preflight.  Configuration selection is restricted to a JSON file beneath the checkout's `config` directory and rejects secret-shaped fields.  The UI stores only sanitized receipts under `.local\release-tools-gui-receipts`.

It deliberately has no controls for version bumps, commits, tags, pushes, GitHub Release publication, upload, staging, activation, migration, rollback, abort or recovery mutation, helper installation, host configuration, restarts, symlink changes, or token rotation.  A running engine call is not force-cancelled; only an operation that has not begun can be cancelled safely.

## Validation

```powershell
python -m pytest tests\test_release_tools_gui.py -q
python -m ruff check release_tools_gui tools\release_tools_gui.py tests\test_release_tools_gui.py
python -m compileall -q release_tools_gui tools\release_tools_gui.py
```

## Packaged executable plan (not executed in Phase 1)

1. Add `release_tools_gui.app:main` to a dedicated PyInstaller spec and bundle the existing release-engine Python modules.
2. Build from an exact committed source revision in a local path, never from a UNC runtime location.
3. Run the same offscreen GUI tests plus a fresh Windows smoke launch of the frozen executable.
4. Verify that no local configuration, receipt history, Git credentials, SSH keys, cache, or token is bundled.
5. Publish only after a later, explicitly authorized release phase; Phase 1 creates no executable, tag, or GitHub Release.
