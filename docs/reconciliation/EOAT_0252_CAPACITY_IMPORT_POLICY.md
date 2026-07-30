# Root-owned policy template: `import-press-capacity`

This template is not installed or activated on production.

```yaml
operation: import-press-capacity
approved_workbook_sha256: 2254269d4eabfd3478a6404005e4efdc850e3223e3ed6882b4bdbd0d71a785e3
approved_catalog_manifest_sha256: ab45a39519b1a302d67c84d17f1cdba9c03da516e872dca657d163db19872550
approved_candidate_manifest_sha256: 997a21b5672b27d61310d8c38554ead973522c6c3b6c8b0b15a64c9e2de7d5fc
approved_release: "0.25.2"
source_schema_target: "20260729_0009"
expected_production_schema: "20260721_0008"
expected_post_migration_schema: "20260721_0008"
allowed_database_identity: eoat_atlas_prod
allowed_action: update_existing_press_capacity_only
allowed_existing_capacity: null_or_exact_candidate_expected_value
excluded_workbook_machines: [24, 64]
excluded_catalog_machines: [6, 8, 70, 72]
forbid: [machine_creation, alias_creation, relationship_creation, arbitrary_sql, arbitrary_paths, destructive_updates]
require: [verified_backup, immediate_dry_run, catalog_drift_check, immutable_receipt]
rollback: restore_verified_backup_and_record_receipt
```

Execution must fail on workbook, catalog, candidate, release, schema, machine-count, identity, row-version, existing-capacity, or writes-enabled drift, and if any excluded record enters the update set.
