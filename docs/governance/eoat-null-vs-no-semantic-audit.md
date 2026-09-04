# EOAT null-versus-no semantic audit

Date: 2026-09-04

Candidate base: `ed9f1a6c10f2f34cebf81052cc61a29ab0444c20`
Production data access: read-only; no production rows, schema, runtime configuration, or write state changed.

## Authority and rule boundary

The audit workbook is the authority for audit-context semantics.  Its schema
deliberately auto-sets a field to `N/A` when it does not apply; `N/A` is not a
generic spelling of an unknown value.  In particular:

- a `Vacuum` EOAT hides and auto-sets gripper fields to `N/A`;
- a `Mechanical / Gripper` EOAT hides and auto-sets vacuum-cup fields to
  `N/A`;
- `Sensors Present? = No` makes sensor-detail fields non-applicable; and
- `Vacuum Confirmation Present?` is non-applicable for an exclusive
  Mechanical / Gripper EOAT.

The source schema leaves both sides applicable for Hybrid and Miscellaneous
EOATs.  Their blanks therefore remain unknown.  It also preserves explicit
child values rather than overwriting an inconsistent source row: that row is
for review, not silent normalization.

The production audited-source value distribution contains `N/A`, not an empty
string, for the affected hardware fields: grippers 27 rows, part-present
sensor 47 rows, vacuum-confirmation sensor 55 rows, and vacuum cups 21 rows.
Thus this candidate does **not** interpret a bare source blank as absence.
It derives absence only from the above stronger type/parent facts.

## Production population at audit time

Production contains 62 EOAT rows.  The following counts were read from
`eoat_atlas_prod` on 2026-09-04.  All listed columns are nullable in MySQL;
the existing non-negative checks already allow zero counts.

| Field / MySQL representation | Current behavior and authoritative convention | NULL production values | Safe canonical false / zero | Remain unknown or manual review | Representative evidence |
| --- | --- | ---: | ---: | ---: | --- |
| `number_of_grippers` / `int NULL` | `N/A` is produced when the exclusive source type is `Vacuum`; that taxonomy proves no grippers. Hybrid/Miscellaneous retain an applicable count. | 23 | 20 → `0` (all Vacuum) | 3 (1 Hybrid, 2 Miscellaneous) | `CL-EOAT-0047`: source `N/A`, Vacuum, canonical NULL; `P4-EOAT-0003` is the same pattern. |
| `number_of_vacuum_cups` / `int NULL` | `N/A` is produced when the exclusive source type is `Mechanical / Gripper`; that taxonomy proves no cups. Hybrid, Miscellaneous, and a Vacuum record with no measured cup count remain unknown. | 21 | 16 → `0` (all Mechanical / Gripper) | 5 (2 Hybrid, 2 Miscellaneous, 1 Vacuum) | `P4-EOAT-0001`: source `N/A`, Mechanical / Gripper. |
| `sensors_present` / `tinyint(1) NULL` | Direct Yes/No source parent. | 0 | 0 | 0 | 43 false, 19 true. `CL-EOAT-0047` is false. |
| `part_present_sensor_present` / `tinyint(1) NULL` | With parent `Sensors Present? = No`, source marks child `N/A`; the parent proves absence. Explicit child values remain authoritative. | 43 | 43 → `false` | 0 | `CL-EOAT-0047`: parent `No`, child `N/A`. |
| `vacuum_confirmation_sensor_present` / `tinyint(1) NULL` | Parent false proves absence for 43 rows. The other 8 are exclusive Mechanical / Gripper with the field non-applicable, hence no vacuum-confirmation sensor. | 51 | 51 → `false` (43 parent-derived + 8 type-derived) | 0 | `CL-EOAT-0047`: parent `No`, child `N/A`; `P4-EOAT-0001`: Mechanical / Gripper, child `N/A`. |
| `vacuum_present` / `tinyint(1) NULL` | There is no direct source field. The current API can infer `true` from verified cups/generator/circuits, but that is not a safe `NULL → false` rule. | 51 | 0 | 51 canonical NULLs stay unchanged; only the existing evidence-based read projection may show true. | `CL-EOAT-0047` is shown as present from its verified cups/circuits. |
| `quick_disconnect_present` / `tinyint(1) NULL` | Direct Yes/No source parent. | 0 | 0 | 0 | No candidate backfill. |
| `revision` / `varchar(64) NULL` | Descriptive specification: absence means not captured. | 62 | 0 | 62 unknown | Keep `Unknown / unavailable`. |
| `frame_material` / `varchar(160) NULL` | Descriptive specification: absence means not captured. | 62 | 0 | 62 unknown | Keep `Unknown / unavailable`. |

There is no canonical EOAT MySQL column for the audit-only circuit/component
counts.  They remain typed values in `audit_records.details_json` and are not
eligible for a database backfill in this candidate.  Zero values such as
`EOAT Pressure Circuits = 0` are already preserved by the audit parser.

`current_location` and storage are not a nullable `eoats` column.  The
location resolver supplies lifecycle context, and the profile intentionally
renders `Not applicable while installed` for storage when the resolved state
is `INSTALLED`.

## Candidate behavior

The candidate adds a small semantic normalizer at the audit/API read boundary
and uses it again after canonical-plus-verified-audit resolution.  This gives
the profile a consistent result even when a canonical parent is false and the
child is still NULL.  It does not write data, change a MySQL type, or turn an
unqualified blank into a value.

For `CL-EOAT-0047` the resulting profile semantics are:

- Vacuum cups: `32`
- Grippers: `0`
- Sensors present: `No`
- Part-present sensor: `No`
- Vacuum-confirmation sensor: `No`
- Storage location while installed: `Not applicable while installed`

## Deferred, idempotent data-backfill plan

No production migration or update is included or authorized by this audit.
After review, a separately governed data-only release may execute these
idempotent updates inside one transaction, after re-running the exact counts
above and preserving an affected-row receipt:

```sql
UPDATE eoats e
JOIN eoat_types t ON t.id = e.eoat_type_id
SET e.number_of_grippers = 0
WHERE t.display_name = 'Vacuum' AND e.number_of_grippers IS NULL;

UPDATE eoats e
JOIN eoat_types t ON t.id = e.eoat_type_id
SET e.number_of_vacuum_cups = 0
WHERE t.display_name = 'Mechanical / Gripper' AND e.number_of_vacuum_cups IS NULL;

UPDATE eoats
SET part_present_sensor_present = FALSE
WHERE sensors_present = FALSE AND part_present_sensor_present IS NULL;

UPDATE eoats e
JOIN eoat_types t ON t.id = e.eoat_type_id
SET vacuum_confirmation_sensor_present = FALSE
WHERE e.vacuum_confirmation_sensor_present IS NULL
  AND (e.sensors_present = FALSE OR t.display_name = 'Mechanical / Gripper');
```

Each predicate includes `IS NULL`, so a successful run is idempotent.  The
release must stop for review if its preflight counts differ from 20, 16, 43,
and 51 respectively.  It must not modify `vacuum_present`, Hybrid,
Miscellaneous, unmeasured Vacuum cup counts, revision, frame material, or any
other descriptive blank.
