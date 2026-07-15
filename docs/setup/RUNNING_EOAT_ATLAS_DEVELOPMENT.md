# Running EOAT Atlas development

From PowerShell:

```powershell
Set-Location $env:EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT
python run_atlas.py
```

The startup banner must identify the Globalized Development repository, development environment, `mysql_api` backend, API 1.3.0, MySQL 8.4.9, database `eoat_atlas_dev`, schema `20260714_0005`, disposable API cache, and disabled legacy fallback. No sign-in is required or initiated during startup.

The root `Start_*`, `Stop_*`, and `Get_*_Status.ps1` wrappers manage the same local development services. Configuration templates belong in source control; credentials remain in local environment configuration and must never be committed.
