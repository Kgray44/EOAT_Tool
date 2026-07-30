# EOAT Atlas Plant 4 canonical capacity mapping review

Date: 2026-07-30
Mode: source and catalog read-only dry run. No import was executed.

## Inputs and compatibility

The primary source remains `press_capacity.xlsx`, SHA-256
`2254269d4eabfd3478a6404005e4efdc850e3223e3ed6882b4bdbd0d71a785e3`.
It provides 54 grouped press headings; 48 give a direct source tonnage and six
are supplied by the explicitly listed `master_press_list.xlsx` supplement.
The canonical catalog receipt and its hashes are recorded in
[the catalog receipt](EOAT_0252_CANONICAL_CATALOG_RECEIPT.md).

The mapping planner is database-free. It reads the source through the existing
governed importer, reads the sanitized catalog manifest, and cannot create a
database session, mutate a workbook, create a machine, or create an EOAT,
tool, assignment, compatibility, or relationship record.

## Mapping outcome

| Classification / action | Count |
| --- | ---: |
| Source press sections | 54 |
| Exact canonical machine number | 52 |
| Exact governed alias | 0 |
| Deterministic normalized number | 0 |
| Contextual plant/section match | 0 |
| Ambiguous | 0 |
| Unmapped | 2 |
| Source-capacity conflict | 0 |
| Existing-capacity conflict | 0 |
| Inactive-machine mapping | 0 |
| Future insert | 0 |
| Future update | 52 |
| Future unchanged | 0 |
| Rejected | 0 |
| Review required | 2 |

All 52 selected canonical records are active `P4` records with an existing
capacity of null. Their future action is therefore `UPDATE` of the existing
machine capacity field only. The two exceptions remain review-required; they
are not converted into inserts or inferred aliases.

The immutable machine-readable catalog-aware dry-run manifest is held in the
governed external evidence location. Its file digest is
`d4aea35afd50c0737e2780c9f82e72a0ea3a0033a6bef2ba9c427b656623c254`.
It contains one row-level decision per source heading, including source row,
heading, parsed capacity, tonnage source, canonical API identity, plant/area,
existing and proposed capacity, unit, action, and reason.

## Machine 27 acceptance proof

| Requirement | Evidence |
| --- | --- |
| Workbook provenance | `P4 Capacity`, row 99, `Press 27 - 165T - 45mm Screw` |
| Parsed capacity / unit | 165 `US_TONS` from the primary capacity workbook |
| Canonical record | `GET /api/v1/machines/27?plant_code=P4` |
| Context | canonical plant `P4`, area `Plant 4`, active record |
| Mapping method | `EXACT_CANONICAL_MACHINE_NUMBER` |
| Existing / proposed capacity | null / 165 tons |
| Future action | `UPDATE` only; no insert and no execution |
| Duplicate source or catalog match | None; one source section and one active canonical record |
| Future API / web presentation | `MachineProfile.press_capacity_tons` from `GET /api/v1/machines/27?plant_code=P4`; shown by Machine Profile Overview as **Press capacity (tons)** |

Machine 27 is data-derived from the two inputs; it is not a hard-coded runtime
special case.

## Safety result

This review creates no production mutation. It records a future plan that may
only populate `machines.press_capacity_tons` after separately scoped execution
authority and fresh conflict checks. The validation source and actual catalog
were never treated as authority to create any entity or relationship.

See the complete exception lists in
[the capacity mapping exception report](EOAT_0252_CAPACITY_MAPPING_EXCEPTIONS.md).
