# EOAT Atlas IT Allowlist Handoff

## Product

- App name: EOAT Atlas
- App version: `0.9.0-dev`
- Release ID: `eoat-atlas-0.9.0-dev-phase-2.6`
- Installer version: `0.1.0`
- Installer schema version: `1`
- App type: internal EOAT Atlas PyInstaller onedir desktop app
- Scope: minimalist/current EOAT Atlas only

## Source And Install Paths

- Source release path: `\\example.invalid\VT/Sanitized/Example\My Documents\KG_Nolato_Summer_2026_Globalized_Development\dist\EOAT Atlas`
- Intended local install root: `%LOCALAPPDATA%\EOAT_Atlas`
- Intended runtime root: `%LOCALAPPDATA%\EOAT_Atlas`
- Main app exe after install: `%LOCALAPPDATA%\EOAT_Atlas\App\eoat-atlas-0.9.0-dev-phase-2.6\EOAT Atlas.exe`
- Script installer path: `\\example.invalid\VT/Sanitized/Example\My Documents\KG_Nolato_Summer_2026_Globalized_Development\installer\Install_EOAT_Atlas.cmd`
- PowerShell implementation: `\\example.invalid\VT/Sanitized/Example\My Documents\KG_Nolato_Summer_2026_Globalized_Development\installer\Install_EOAT_Atlas.ps1`
- Optional installer exe: `\\example.invalid\VT/Sanitized/Example\My Documents\KG_Nolato_Summer_2026_Globalized_Development\installer\dist\Install EOAT Atlas.exe`
- Future launcher path placeholder: `%LOCALAPPDATA%\EOAT_Atlas\Launcher\EOAT Atlas Launcher.exe`

## SHA-256 Hashes

- Source `EOAT Atlas.exe`: `3ABA873E380ADF4D7E9D737FA66194F9BDC69FAE30B51BD60F89CB4AA70112E2`
- Optional installer exe `Install EOAT Atlas.exe`: `641D8DE0DF9DE09F5DAE76B804280E19DBFC6C5E779D8547A52192D475A77F3A`
- Launcher exe: not available in this phase

## Security And Runtime Notes

- No admin install is required.
- The installer uses per-user LocalAppData paths only.
- The installer does not request elevation.
- The installer does not install to Program Files.
- The installer does not write HKLM registry keys.
- The installer does not create services.
- The installer does not modify PATH.
- The installer does not create all-users shortcuts.
- Production workbook writes are disabled by config: `production_writes_enabled=false`, `write_mode=disabled`.
- EOAT Atlas uses LocalAppData for SQLite cache, pending updates, event outbox, logs, thumbnails, identity, and config.
- Network workbook paths are used for Deep Refresh and future controlled sync only.
- The installer does not launch EOAT Atlas during install.

## Endpoint Security Status

SentinelOne is reported to block opening the packaged EOAT Atlas app executable on the current endpoint. No bypass or workaround was attempted.

The optional installer exe was built and dry-run verified on July 10, 2026. If endpoint security blocks the installer exe on another machine, use the script installer path and provide the hash above for IT review.
