# EOAT Profile Audit Provenance

## Verified loss points

| Boundary | Finding | Repair |
|---|---|---|
| Master Tracker to importer | `execute_import` used the first spreadsheet row for an EOAT's normalized profile values. | Select the newest physical-audit row; derived compatibility rows cannot become profile authority. |
| MySQL audit history | Tracker fields are retained in `audit_records.details_json`, but no typed physical-observation read model existed. | `audit_profiles.py` projects the newest physical audit with audit ID, date, machine, tool, verification, and configuration. |
| Historical location | The `20260717_0007` observation schema existed but had no ORM model, importer/backfill, or API resolver. | Map the tables and add a dry-run-first idempotent backfill. Observations are never installations. |
| API profile | Audit-only configuration fields were exposed only as untyped JSON and omitted from the web profile. | Add `latest_physical_audit` to EOAT, Machine, and Tool contracts. |
| Web profile | EOAT configuration did not display audit provenance and current location was the only location context. | Show a separate historical-audit section and label it as non-current. |

## EOAT field mapping

| Profile display | Master Tracker field | MySQL authority | API property | Web display |
|---|---|---|---|---|
| Description | `Part Name/Description` | `eoats.description` when safely promoted; always retained in `audit_records.details_json` | `description` | Overview |
| Revision | no audited source field | `eoats.revision` | `revision` | Overview |
| Type / connection / cleanroom | `EOAT Type`, `Connection Type`, `Cleanroom/Non-Cleanroom` | lookup-backed `eoats` columns | `eoat_type`, `connection_type`, `cleanroom_classification` | Overview |
| Parts, cups, grippers | `Number of Parts Picked`, `# of Cups`, `# of Grippers` | nullable `eoats` columns plus immutable audit JSON | normalized properties and historical configuration | Overview/configuration and historical configuration |
| Cup material/size, generator, circuits | tracker configuration fields | audit JSON (size/generator/circuits); material additionally nullable on `eoats` | `latest_physical_audit.configuration` | Historical configuration |
| Sensors and disconnects | tracker boolean/type fields | nullable `eoats` booleans plus immutable audit JSON | normalized properties and historical configuration | Configuration and historical configuration |
| Current machine/storage | explicit lifecycle records only | `eoat_installations`, `eoat_storage_assignments` | `current_location_detail` | Current location and assignment |
| Last physically observed machine/tool/date/audit/verification | audited tracker row | `audit_records` and `eoat_location_observations` | `latest_physical_audit` | Last physical audit |

`Unknown` remains null or absent when the tracker does not establish a value.  `False` and `0` are preserved as known values, not converted to unknown through truthiness checks.
