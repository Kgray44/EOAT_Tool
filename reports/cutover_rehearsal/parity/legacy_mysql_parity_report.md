# Legacy-to-MySQL Data Parity

## Counts

| Dataset | Legacy expected | MySQL |
|---|---:|---:|
| eoats | 57 | 57 |
| machines | 56 | 56 |
| tools | 65 | 65 |
| eoat_machine_compatibility | 87 | 87 |
| eoat_tool_compatibility | 65 | 65 |
| tool_machine_compatibility | 88 | 88 |
| audits | 102 | 102 |
| documents | - | 158 |
| photos | - | 158 |
| parts | - | 0 |
| installations | - | 0 |

## Identifier, value, and relationship differences

| Classification | Entity | Identifier | Field | Explanation |
|---|---|---|---|---|
| SOURCE_CONFLICT | EOAT | CL-EOAT-0052 | Cleanroom/Non-Cleanroom | Conflicting source values are retained; normalized value must remain unknown unless explicitly resolved. |
| EXPECTED_DEFERRED_AMBIGUITY | SQLiteAnnotations | C:\Users\kgray\AppData\Local\EOAT Atlas Staging\rehearsals\4f26cee2-7849-48ba-b437-f8a2a5bb485e\frozen_source\project_data\annotations.sqlite | permanent_annotation_records | Permanent legacy annotations remain in the legacy SQLite authority during this read-only phase. |
