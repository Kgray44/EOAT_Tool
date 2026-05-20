# Packaging

Source-run mode is the primary supported way to use EOAT Command Center:

```powershell
python -m pip install -r requirements.txt
python run_dashboard.py
```

Optional executable packaging can be attempted with PyInstaller:

```powershell
python -m pip install pyinstaller
python scripts/build_package.py
```

The build output goes to:

```text
dist\EOAT_Command_Center
```

Smoke test the package:

```powershell
python scripts/smoke_test_package.py
```

Do not bundle EOAT project data, reports, photos, workbooks, or network folders into the executable. The app should always operate on a selected project root.

Known limitations:

- Network/UNC paths can confuse CMD launch context; use the Desktop `.cmd` launcher or run from PowerShell.
- Work computers may block unsigned executables.
- Packaging is optional and not required for daily project work.
