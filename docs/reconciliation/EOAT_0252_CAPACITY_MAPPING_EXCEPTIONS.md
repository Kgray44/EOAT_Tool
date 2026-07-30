# EOAT Atlas Plant 4 canonical capacity mapping exceptions

Date: 2026-07-30
Catalog scope: 56 active canonical `P4` records from the sanitized read-only
production API catalog.

## Unmapped workbook press sections

| Source | Parsed machine | Capacity | Reason |
| --- | ---: | ---: | --- |
| `P4 Capacity` row 86, `Press 24 - 200T - 50mm Screw` | 24 | 200 tons | `NO_CANONICAL_MACHINE_MATCH` |
| `P4 Capacity` row 246, `Press 64 -110T - 22/28mm Screw` | 64 | 110 tons | `NO_CANONICAL_MACHINE_MATCH` |

Both are `REVIEW_REQUIRED`; neither has a proposed canonical identity or
database write.

## Canonical P4 machines absent from the workbook

Machines 6, 8, 70, and 72 are active canonical `P4` records but have no
capacity-section source heading. They receive no proposed capacity action.

## Empty exception classes

| Exception class | Count |
| --- | ---: |
| Duplicate active canonical machine numbers | 0 |
| Alias collisions | 0 |
| Ambiguous mappings | 0 |
| Source-tonnage conflicts | 0 |
| Existing-capacity conflicts | 0 |
| Inactive-machine mappings | 0 |
| Rejected mappings | 0 |

The production read API did not expose governed aliases. The absence is
recorded in the catalog manifest; aliases were neither manufactured nor used.
