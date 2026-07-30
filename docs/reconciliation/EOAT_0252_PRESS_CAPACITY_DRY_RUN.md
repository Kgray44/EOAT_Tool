# EOAT Atlas 0.25.2 Plant 4 press-capacity dry-run review

Date: 2026-07-30
Branch baseline: `3238cc21b9b801d48ed3253b6494f27553a5632a`
Mode: read-only source validation and non-mutating plan; no database session,
import execution, production access, relationship write, or LDAP action.

## Source identity and scope

| Input | SHA-256 | Role in this dry run |
| --- | --- | --- |
| `press_capacity.xlsx` | `2254269d4eabfd3478a6404005e4efdc850e3223e3ed6882b4bdbd0d71a785e3` | Primary Plant 4 capacity source. |
| `master_press_list.xlsx` | `c74ec1e54e4a776cb3998d183605233ec54a04dc96ac405876d122d32f757f99` | Explicit supplemental input used only where a P4 press-heading omits a tonnage. It does not prove current Atlas catalog membership or authorize an import. |

The business workbooks are deliberately not stored in the repository.  The
immutable, machine-readable receipt is generated outside the repository and
contains both digests, structure metadata, and each mapping decision.

## Workbook and field validation

`press_capacity.xlsx` has one visible sheet, `P4 Capacity`, with range
`A1:W280`: 23 columns, 279 rows after the header, 2,386 formula cells, 14
hidden rows, eight hidden columns, and no merged ranges.  Its header has
`Machine No.`, NGW part identity/description, bill-to, yearly/monthly forecast
quantities, `Cycle Time (S)`, cavitation, hour/day allocation fields, and
forecast/available-capacity calculations.  The capacity value is not a flat
column: it is encoded in 54 grouped labels such as `Press 27 - 165T - 45mm
Screw`.

This is therefore compatible with the importer's grouped-P4 layout, not the
flat `Machine No.`/`Press Tonnage` layout.  The grouped labels provide press
capacity in tons.  The supplemental sheet, `Machine Specifications`, supplies
the same unit explicitly as `U.S. Tons`.

There are 48 headings with a source tonnage and six without one: machines 37,
59, 65, 66, 69, and 71.  The supplemental source filled those six values only.
All 48 direct source values that overlap the supplemental source agree.  Press
24 is intentionally source-only, while supplemental-only machines 8, 28, 37,
59, 65, 66, 69, and 71 were not invented as primary capacity sections.

The 225 non-heading rows are workload/detail evidence, including 60
comma-separated multi-machine values.  They are neither capacity records nor
aliases for this import.  The importer retains them as provenance and never
uses them to infer relationships or a machine capacity.

## Governed dry-run outcome

| Decision class | Count | Result |
| --- | ---: | --- |
| Parsed capacity sections | 54 | All have a positive tonnage after the explicit supplemental fill. |
| Exact canonical matches | 0 | No current Plant 4 Atlas machine catalog was supplied to the source-only plan. |
| Alias mappings | 0 | No aliases or fuzzy matching are implemented or used. |
| Ambiguous capacity mappings | 0 | Multi-machine detail rows are out of capacity-mapping scope. |
| Unmapped canonical candidates | 54 | Every normalized press number is `REVIEW_REQUIRED` with `NO_CANONICAL_MACHINE_MATCH`. |
| Source-capacity conflicts | 0 | No conflicting grouped-header values. |
| Existing-capacity conflicts | 0 | No canonical existing values were available to compare. |
| Invalid rows after supplemental fill | 0 | The six incomplete headings were resolved only by the explicit supplemental input. |

The plan status is `DRY_RUN_COMPLETE`, while `safe_to_execute` is `false`.
That distinction is intentional: the parser completed, but import safety
cannot be established without an approved current Plant 4 Atlas catalog.

The proposed changes are consequently **0 inserts, 0 capacity updates, and 0
unchanged database rows**.  This importer never proposes a machine, tool,
compatibility, assignment, or other relationship insert; it can only populate
an existing machine's `press_capacity_tons` after an exact catalog match.

## Machine 27 proof and representative checks

| Source machine | Evidence | Parsed capacity | Mapping result |
| --- | --- | ---: | --- |
| 1 | `P4 Capacity` row 2 grouped heading | 35 tons | Normalized candidate; unmapped because no canonical catalog was supplied. |
| 24 | `P4 Capacity` row 86 grouped heading | 200 tons | Direct-source-only candidate; unmapped. |
| 27 | `P4 Capacity` row 99 grouped heading | 165 tons | Exact normalized number; `REVIEW_REQUIRED`, `NO_CANONICAL_MACHINE_MATCH`; no write proposed. |
| 37 | `P4 Capacity` row 147 plus supplemental `U.S. Tons` | 500 tons | Explicit missing-tonnage fill; unmapped. |
| 94 | `P4 Capacity` row 276 grouped heading | 200 tons | Normalized candidate; unmapped. |

Machine 27 is specifically present in the primary source and has a
deterministic row-level manifest entry.  It has not been treated as proof that
an Atlas machine 27 presently exists, so no capacity, tool, EOAT, or media
association was created.

## Human review required before any future execution

1. Supply or approve a current, non-production Plant 4 Atlas machine-catalog
   export containing canonical machine identifiers and existing capacities.
2. Re-run the same source hashes against that catalog.  Only exact normalized
   machine-number matches may become `SET_PRESS_CAPACITY` or `UNCHANGED`.
3. Resolve any source/catalog capacity disagreement as a conflict; do not use
   aliases, detail-row lists, or relationship inference to bypass review.
4. Obtain separately scoped execution authority.  This receipt grants none.
