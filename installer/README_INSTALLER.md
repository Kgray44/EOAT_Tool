# EOAT Atlas Installer

Use `Install_EOAT_Atlas.cmd` first. It is the primary supported installer path for this phase because endpoint security may block PyInstaller-built executables until IT allowlists them.

## What It Installs

The installer copies the complete EOAT Atlas PyInstaller onedir release from:

`..\dist\EOAT Atlas`

into the current user's LocalAppData:

`%LOCALAPPDATA%\EOAT_Atlas\App\<release_id>\`

Runtime data stays under:

`%LOCALAPPDATA%\EOAT_Atlas\`

The installer creates or updates:

- `install_identity.json`
- `install_receipt.json`
- `current_app.json`
- `current_launcher.json`
- `config\global_config.json`
- required runtime folders: `data`, `pending`, `events`, `sync`, `staging`, `backups`, `logs`, `thumbnails`, and `temp`
- the current user's Desktop shortcut: `EOAT Atlas.lnk`

No admin rights are required. The installer does not install to Program Files, does not write HKLM registry keys, does not create services, does not modify PATH, and does not create all-users shortcuts.

## Shortcut Behavior

The installer always creates or updates the current user's Desktop shortcut. There is no prompt and no checkbox.

Current phase:

- Launcher is not installed yet.
- Shortcut points directly to the installed `EOAT Atlas.exe`.

Future launcher phase:

- Configure `launcher_source_path`.
- Set `install_launcher` to `auto_if_available` or `required`.
- When the launcher installs successfully, the same shortcut points to `EOAT Atlas Launcher.exe`.

## Preserved Runtime Data

The installer does not delete user/runtime data, including:

- `data\local_cache.db`
- `settings.json`
- `config\global_config.json`
- `install_identity.json`
- pending update files
- event files
- logs
- thumbnails
- user settings

If the same release is repaired or reinstalled, only the app version folder is replaced after staging verification. Existing runtime data remains in place.

## Running The Installer

Double-click:

`Install_EOAT_Atlas.cmd`

Command line dry run:

```powershell
.\Install_EOAT_Atlas.cmd -DryRun
```

Validate source only:

```powershell
.\Install_EOAT_Atlas.cmd -ValidateOnly
```

Validate an installed copy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Validate_EOAT_Atlas_Install.ps1
```

Logs are written to:

`%LOCALAPPDATA%\EOAT_Atlas\logs\installer_<timestamp>.log`

## SentinelOne / Endpoint Security

The installer does not attempt to bypass, disable, trick, or work around SentinelOne. The installer also does not launch EOAT Atlas as part of the normal install because endpoint security may block the packaged app executable.

If SentinelOne blocks EOAT Atlas or the optional installer exe, report it to IT with `IT_ALLOWLIST_HANDOFF.md` and the listed SHA-256 hashes. Use the `.cmd` installer path while the exe path is pending allowlisting.

## Optional Exe Wrapper

`Build_Installer_Exe.ps1` builds:

`dist\Install EOAT Atlas.exe`

The exe wrapper uses the same PowerShell installer logic and an `asInvoker` manifest. It does not request elevation and does not bundle stale app versions. Keep the exe with the installer folder so it can find `Install_EOAT_Atlas.ps1` and `installer_config.json`.

## Do Not Delete

Do not delete `%LOCALAPPDATA%\EOAT_Atlas\data`, `pending`, `events`, `logs`, `thumbnails`, `install_identity.json`, or `config\global_config.json` during support unless a future recovery procedure explicitly says to do so.
