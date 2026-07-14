# EOAT Atlas Launcher

The EOAT Atlas Launcher is a small Windows-friendly starter for EOAT Atlas. It checks the install path, local launcher folders, optional shared resources, installed version metadata, and startup result before opening the app. Normal successful launch should be quiet; problems are shown as plain user-facing messages and written to logs.

## How It Finds EOAT Atlas

The launcher resolves the app in this order:

1. `--app-path` command-line override.
2. `appInstallPath` in the launcher config.
3. Installer metadata in the launcher config folder (`install_metadata.json` or `install.json`).
4. EOAT Atlas installer metadata under `%LOCALAPPDATA%\EOAT_Atlas\current_app.json`, `install_identity.json`, or `config\global_config.json`.
5. Common per-user paths such as `%LOCALAPPDATA%\EOAT Atlas\`.
6. Future IT-managed paths such as `C:\Program Files\EOAT Atlas\`.

The current expected executable name is `EOAT Atlas.exe`. The config can also point to an `appEntryPoint` for source/development testing.

## Config And Logs

Default per-user config:

```text
%APPDATA%\EOAT Atlas Launcher\launcher_config.json
```

Default logs:

```text
%LOCALAPPDATA%\EOAT_Atlas\logs\launcher.log
%LOCALAPPDATA%\EOAT_Atlas\logs\Diagnostics\
```

The default config template is committed at `launcher/default_config.json`. The per-user installer writes `current_app.json`, `current_launcher.json`, and `config\global_config.json`; the launcher can use those files without a separate prompt.

## Diagnostics And Repair

Useful commands:

```powershell
EOAT Atlas Launcher.exe --check-only
EOAT Atlas Launcher.exe --diagnostics
EOAT Atlas Launcher.exe --open-logs
EOAT Atlas Launcher.exe --repair --app-path "$env:LOCALAPPDATA\EOAT_Atlas\App\<release_id>"
```

Repair recreates missing launcher folders/config from defaults and can repoint the launcher to a moved app folder. It does not delete user data. Existing config is backed up before being overwritten.

## Version And Updates

EOAT Atlas version metadata is read from `release_metadata.json` or `version.json` near the installed app, with fallback checks under `_internal\` for PyInstaller builds. The source metadata currently lives at:

```text
release_metadata.json
```

If `updateManifestPath` or `updateManifestUrl` is configured, the launcher compares the installed version to the manifest version. There is no automatic updater yet; when a newer reliable version is detected, the launcher shows a manual-update notice and opens the installed app.

## Shared Resource Checks

`networkRequiredPaths` can contain strings or objects:

```json
[
  {
    "label": "Shared EOAT photo folder",
    "path": "\\\\server\\share\\EOAT_Photos",
    "required": false
  }
]
```

If `allowOfflineLaunch` is true, unavailable optional resources warn but do not block launch. Required resources block launch with a clear message.

## Installer Notes

The installer should:

- Install the main EOAT Atlas app folder.
- Install `EOAT Atlas Launcher.exe`.
- Write `%LOCALAPPDATA%\EOAT_Atlas\current_app.json` and `config\global_config.json`.
- Optionally write `%APPDATA%\EOAT Atlas Launcher\launcher_config.json` with `appInstallPath`.
- Place `release_metadata.json` or `version.json` beside the EOAT Atlas executable or under the packaged `_internal` folder.
- Create Start Menu entries if desired.
- Avoid requiring write access to `C:\Program Files` during normal launch.

No desktop shortcut option is required.
