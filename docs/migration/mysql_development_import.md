# MySQL Development Import

The controlled importer is `tools/migration/excel_to_mysql.py`. Executable import is restricted to `--database-profile development`; dry-run and validate-only modes remain available.

## Executed source

- Workbook: `EOAT_Standardization_Project/01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx`
- SHA-256: `207e166c3c75f4a517a47f572c84d683b3b7a194bb23b1f5649e97c5d76b7eac`
- Batch UUID: `c9416c39-09cf-47b1-bc7b-c372eb734f9a`
- Schema: `20260713_0001`
- Result: committed; source unchanged

The import creates safe assets, observed compatibility relationships, audits, documents/photos, and full batch/row/issue provenance. It does not create parts, tool-part links, installations, or storage assignments without evidence.

## Repeatability

`--reset-imported-data` removes only controlled development/imported data while preserving the schema. An already completed source checksum safely stops unless reset is explicitly requested. No `INSERT IGNORE` or conflict-hiding upsert is used.

The pre-import database backup is stored under `reports/mysql_import/pre_import_eoat_atlas_dev_20260713_172050.sql`.

## Commands

```powershell
python -m tools.migration.excel_to_mysql --source-workbook <workbook> --report-output reports/mysql_import --database-profile development --execute --import-batch-name <name>
python -m tools.migration.excel_to_mysql --source-workbook <workbook> --report-output reports/mysql_import --database-profile development --execute --reset-imported-data --import-batch-name <name>
```

