# Photo Evidence and Gripper Presets

Phase 9 adds a local-first evidence coverage layer for audit photos plus reference-backed gripper presets.

## Photo Evidence Coverage

The core model lives in `core/photo_evidence.py`. It defines evidence categories with:

- `key`
- `label`
- `applies_when`
- `required_when`
- `recommended_when`
- `example_filename_prefix`

Supported categories:

- Overall EOAT
- Robot Connection
- EOAT-Side Pneumatic Circuits
- Sensors
- Quick Disconnects
- Tubing Routing
- Grippers
- Vacuum Cups
- Mounting Hardware
- Cable Management
- Wear / Damage
- Process Binder Reference

Coverage is calculated per audit from the EOAT Inventory row and existing Photo Index rows. It does not require photo files to exist during validation, which keeps tests and demo projects synthetic and prevents real photos from being pulled into source control.

Coverage statuses distinguish:

- `complete`
- `partial`
- `missing`
- `not applicable`
- `follow-up needed`

Validation adds structured missing-evidence findings when evidence-sensitive audit decisions are incomplete, including complete audits missing required evidence, pilot candidates without before photos, issues without supporting photos, documentation marked complete without a reference, sensors without sensor photos, and quick disconnects without quick disconnect photos.

## Phone-Friendly Intake

The Photos page now includes an Audit Photo Evidence section beside the existing intake workflow. Existing incoming-photo behavior is unchanged.

New local actions:

- Refresh evidence coverage for the Related Audit ID.
- Create an audit-specific intake folder.
- Export a markdown photo checklist.
- Copy the audit intake path.
- Open the audit intake folder.

Audit-specific intake folders are created under:

`01_EOAT_Audit/Photos/Incoming/<Audit ID>/`

This is a local folder only. No network upload is implemented.

## Gripper Presets

Default preset reference data lives in `data_templates/gripper_presets.example.json`.

The preserved default mappings are:

- Large Double Gripper -> `MHZL2-16D`
- Small Double Gripper -> `MHZL2-10S`

Projects can add local reference data at:

`00_Project_Admin/reference_data/gripper_presets.json`

Schema:

```json
{
  "presets": [
    {
      "friendly_name": "Large Double Gripper",
      "part_number": "MHZL2-16D",
      "manufacturer": "SMC",
      "default_type": "Double Pressure",
      "notes": "Verify against the physical EOAT before engineering use.",
      "active": true
    }
  ]
}
```

The Audit page displays friendly names and saves the workbook model/part number. Unknown custom values remain editable and are preserved.

## PM/BOM Hooks

Reusable PM/BOM helpers live in `core/pm_bom_coverage.py`:

- `is_spare_parts_info_missing`
- `is_bom_available`
- `is_gripper_preset_known_for_row`
- `standard_parts_opportunities`
- `missing_required_evidence_categories`
- `is_documentation_photo_evidence_missing`
- `build_pm_bom_coverage`

These helpers are intentionally conservative. They flag gaps and opportunities, but they do not guess engineering values.
