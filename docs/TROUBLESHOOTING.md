# Troubleshooting

## Python Not Found

Install Python, then run:

```powershell
python --version
python -m pip install -r requirements.txt
```

If Windows opens the Microsoft Store alias, disable the Python app execution alias in Windows settings.

## PySide6 Missing

Run:

```powershell
python -m pip install -r requirements.txt
```

## UNC Path Warning

CMD may warn that UNC paths are not supported. Use:

```text
%USERPROFILE%\Desktop\EOAT Command Center.cmd
```

Refresh it with:

```powershell
python create_dashboard_launcher.py
```

## Workbook Missing

Use Settings to select the correct `EOAT_Standardization_Project` root, then run Foundation Validation or Full System Audit.

## Git Missing

Git is optional. Configure the Git executable path in Settings if available.

## Reports Are Empty

Most analysis tools are honest about missing data. Add audit rows, issue log entries, KPI rows, photos, or interview notes before expecting rich summaries.

## Safe Backups

Use Settings or CLI:

```powershell
python tools/project_backup.py --project-root "EOAT_Standardization_Project" --mode workbook
python tools/project_backup.py --project-root "EOAT_Standardization_Project" --mode light
```

