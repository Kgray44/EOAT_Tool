# EOAT Atlas 0.25.2 Plant 4 capacity exception reconciliation

Immutable inputs: workbook `2254269d4eabfd3478a6404005e4efdc850e3223e3ed6882b4bdbd0d71a785e3`, catalog `ab45a39519b1a302d67c84d17f1cdba9c03da516e872dca657d163db19872550`, prior dry run `d4aea35afd50c0737e2780c9f82e72a0ea3a0033a6bef2ba9c427b656623c254`, and reconciliation evidence `cd144e09283606b2d365a166ea0d08dc944cc351d503a28b467a6179eca798ec`.

## Proven facts

Production was healthy at `0.24.1`, schema `20260721_0008`, with writes disabled. Its complete machine list has 56 P4 records and no exact machine 24 or 64. The API exposes no governed aliases and no machine history for 6, 8, 70, or 72. No retirement, replacement, relocation, or alias conclusion follows from those absences.

| Record | Disposition |
| --- | --- |
| Press 24 | Workbook row 86, 200 tons, 50 mm screw; no canonical, cross-plant, alias, or master-list record. `UNRESOLVED_REVIEW_REQUIRED`. |
| Press 64 | Workbook row 246, 110 tons; master list has two 110-ton Machine 64 rows but no production record or alias. `UNRESOLVED_REVIEW_REQUIRED`. |
| Machine 6 | Active P4, null capacity; absent from workbook and master list. `NO_APPROVED_CAPACITY_SOURCE`. |
| Machine 8 | Active P4, null capacity; master list has a separate 50-ton record, but its prior scope was supplemental. `CAPACITY_AVAILABLE_FROM_OTHER_APPROVED_SOURCE`, excluded pending scope confirmation. |
| Machine 70 | Active P4, null capacity; absent from workbook and master list. `NO_APPROVED_CAPACITY_SOURCE`. |
| Machine 72 | Active P4, null capacity; absent from workbook and master list. `NO_APPROVED_CAPACITY_SOURCE`. |

## Candidate-pair results

No renumbering/replacement pair is supported. 24→8 and 64→8 are contradicted by Machine 8's distinct 50-ton master-list value. Every other pair among {24,64} × {6,8,70,72} is `INSUFFICIENT_EVIDENCE`: there is no alias, history, manufacturer/model, replacement, or tool/EOAT history proof. Counts, area, and tonnage were not used as identity proof.

The 52 exact active canonical matches can be prepared independently. All six discrepancies remain excluded; no entity, alias, or relationship may be created to resolve them.
