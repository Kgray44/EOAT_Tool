# Packaging EOAT Command Center

EOAT Command Center can be launched from source or built into a Windows folder-style executable with PyInstaller.
The supported packaged format is currently `--onedir`; one-file builds can be explored after the onedir build is stable.

## Prerequisites

- Windows 10 or newer.
- Python 3.10+ available as `python` or `py`.
- Access to this project checkout.
- Project dependencies from `requirements.txt` and developer tools from `requirements-dev.txt`.

## Source Launch

Use this command as the canonical source entry point:

```powershell
python -m app.main
```

For automated startup smoke checks, use:

```powershell
$env:EOAT_COMMAND_CENTER_SMOKE_TEST = "1"
python -m app.main
Remove-Item Env:\EOAT_COMMAND_CENTER_SMOKE_TEST
```

## Build From Scratch

From the repository root:

```powershell
.\build_tools\build_exe.ps1
```

The script will:

- clean `build/` and `dist/`
- create or activate `.venv`
- install project requirements, Ruff, pytest helpers, and PyInstaller
- run `python -m ruff check .`
- run `python -m pytest`
- build with `python -m PyInstaller --noconfirm --clean .\EOAT_Command_Center.spec`

For a packaging-debug build when tests were already run separately:

```powershell
.\build_tools\build_exe.ps1 -SkipTests
```

## Output

The executable is created at:

```text
dist/EOAT Command Center/EOAT Command Center.exe
```

The build is windowed, so double-clicking the executable should not open a console window.

## Bundled Resources

The PyInstaller spec includes:

- `data_templates/`
- `templates/`
- `config/config.example.json`
- Markdown documentation under `docs/`
- PySide6 and Qt runtime dependencies
- dynamic imports from `app`, `core`, and `tools`

The app uses `core.resources.resource_path()` for bundled read-only resources. In a frozen build, local settings are stored under the user's app data folder instead of inside `dist/EOAT Command Center`.

## User Data

Do not place real EOAT project data inside the executable folder. Writable files should go to:

- the selected EOAT project root
- `%LOCALAPPDATA%\EOAT Command Center\config`
- another user-selected or configured output folder

This includes logs, reports, backups, generated workbooks, exported documents, selected project path config, app settings, and user-created data.

## Test The Packaged App

After building:

```powershell
python scripts/smoke_test_package.py
```

The smoke helper launches the windowed executable with a smoke flag and requires it to exit with code 0 within the timeout. A hung process, PyInstaller error dialog, or nonzero exit fails the smoke check. It does not replace manual double-click testing.

Then manually verify:

- double-click `dist/EOAT Command Center/EOAT Command Center.exe`
- select or open the EOAT project root
- confirm Home, Audit, Photos, Workbook Health, and Settings load
- confirm bundled templates and workbook schema-backed features work
- confirm reports, logs, workbook backups, and photo intake outputs write to the selected project root
- confirm `config/local_config.json` is not written inside the executable folder

## Troubleshooting

Missing imports:
Add hidden imports to `EOAT_Command_Center.spec`. Dynamic page imports are already covered by `collect_submodules("app")`.

Missing PySide6 or Qt plugins:
Keep `collect_all("PySide6")` in the spec. Rebuild with `--clean`.

Missing templates or assets:
Add the folder or file to the `datas` list in `EOAT_Command_Center.spec`.

App opens then instantly closes:
Run from PowerShell once to inspect errors, or temporarily build without `console=False` while debugging.

App cannot write files:
Check that the selected project root is writable. Packaged settings belong in `%LOCALAPPDATA%\EOAT Command Center`, not in the bundled app folder.

Helper-script workflows:
Some legacy workflows still launch Python scripts using `sys.executable`. In a frozen build, verify those workflows manually before relying on them for production scheduling.

## One-File Build Later

A one-file executable can be tested later by changing the PyInstaller build to `--onefile` or adjusting the spec. One-file builds start more slowly because bundled files are extracted at launch, so onedir remains preferred for debugging and internal deployment.

## Future Installer

An installer such as Inno Setup can wrap the onedir output later and add Start Menu and desktop shortcuts.
