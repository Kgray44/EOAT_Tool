# Final Handoff Outputs

Phase 11 adds leadership-ready final handoff outputs while keeping generated real reports inside the selected private EOAT project root.

## Readiness Model

`core.final_handoff_readiness` evaluates the final deliverables as local evidence, not as claims of completion. Each item has:

- `key`: stable programmatic identifier.
- `label`: display name for the Final Handoff page.
- `status`: one of `ready`, `draft`, `missing`, `needs review`, or `not applicable`.
- `evidence`: private project-root paths that support the status.
- `warnings`: honest caveats, especially for KPI and pilot result claims.
- `recommended_action`: next step for the user.

Tracked deliverables:

- EOAT Database
- Standards Guidelines
- PM Checklist Package
- FMEA Output
- KPI Dashboard/Export
- Pilot Results or Pilot Candidate Packets
- Training Materials
- Documentation Gap Summary
- Open Items Carryover
- Executive Summary
- Technical Appendix
- Machine Summary Report

## Exports

Leadership summary exports create `Executive_Summary_YYYYMMDD_HHMM.md` under `06_Final_Handoff/Executive_Summary` unless the package builder supplies a package folder. The package copy uses the fixed file name `Executive_Summary.md`.

Technical appendix exports create `Technical_Appendix_YYYYMMDD_HHMM.md` under `06_Final_Handoff/Technical_Appendix` unless the package builder supplies a package folder. The package copy uses `Technical_Appendix.md`.

Open items carryover exports create `Open_Items_Carryover_YYYYMMDD_HHMM.md` under `06_Final_Handoff/Open_Items_Carryover` unless the package builder supplies a package folder. The package copy uses `Open_Items_Carryover.md`.

Readiness checklist exports create `Deliverable_Readiness_YYYYMMDD_HHMM.md` under `06_Final_Handoff/Deliverable_Readiness` unless the package builder supplies a package folder. The package copy uses `Deliverable_Readiness.md`.

Machine summary exports create `Machine_Summary_Report_YYYYMMDD_HHMM.md` under `06_Final_Handoff/Machine_Summaries` unless the package builder supplies a package folder. The package copy uses `Machine_Summary_Report.md` under `Machine_Summaries/`.

## Package Structure

Final packages are created under:

`06_Final_Handoff/Final_Handoff_Package_YYYYMMDD_HHMM/`

If that folder already exists, the builder appends a numeric suffix instead of overwriting it.

Required root files:

- `Executive_Summary.md`
- `Technical_Appendix.md`
- `Open_Items_Carryover.md`
- `Deliverable_Readiness.md`
- `Machine_Summaries/Machine_Summary_Report.md`
- `HANDOFF_INDEX.md`

Required evidence folders:

- `FMEA/`
- `KPI/`
- `PM_Checklists/`
- `Pilot_Candidates/`
- `Standards/`
- `Validation/`

The builder may also include supporting folders such as `EOAT_Database/`, `Training_Materials/`, `Presentation/`, `Executive_Backup/`, `Machine_Summaries/`, `Photo_Evidence/`, and `Reference/` when source files exist.

`HANDOFF_INDEX.md` includes a link map for the final master tracker, Robot Info workbook, FMEA, KPI dashboard, PM checklist package, BOM/spares report, standard design guidelines, work instructions, pilot report, training materials, photos/evidence, open issues, recommendations, and machine summary report. Missing items stay marked as missing or needs review; the index does not certify absent evidence as complete.

## Safety Rules

The package builder copies files and does not move originals. It does not overwrite existing package folders or fixed package root files.

Generated packages, executive summaries, technical appendices, carryover exports, and readiness exports are project artifacts. Do not commit real generated outputs, workbooks, reports, photos, logs, caches, local configs, internal paths, mold numbers, part numbers, customer names, capacity data, downtime data, scrap data, or private operational details to the repository.

The executive summary and technical appendix intentionally avoid fabricating KPI impact or pilot results. If measured before/after evidence is not present, the generated text says the data is unavailable.
