# Canonical EOAT Atlas development repository

Canonical repository:

`KG_Nolato_Summer_2026_Globalized_Development`

Absolute path:

The authorized clone containing `EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT`.

Canonical active development branch:

`development/mysql-api-consolidated`

Normal startup:

```powershell
Set-Location $env:EOAT_ATLAS_CANONICAL_DEVELOPMENT_ROOT
python run_atlas.py
```

The default development backend is `mysql_api`. The local SQLite file is a disposable API cache and is never the shared system of record. The former `KG_Nolato_Summer_2026` repository is retained only as recovery evidence and must not be used for development or application startup.
