# Tool Guide

The tool registry lives in `data_templates/tool_registry_seed.json` and is loaded by `core/tool_registry.py`.

Each item includes:

- `id`
- `name`
- `category`
- `phase`
- `description`
- `input`
- `output`
- `safe_to_run_repeatedly`
- `modifies_project_files`
- `requires_workbook`
- `requires_git`
- `dashboard_page`
- `cli_module`
- `entry_point`
- `implementation_status`

Phase 5 marks setup, daily status summary, foundation validation, audit entry, photo intake, interview entry, audit progress, issue analysis, documentation gap scanning, FMEA-lite, pilot ranking, KPI dashboard reporting, PM checklists, BOM/spares, weekly summary, mentor prep, morning planner, final presentation assets, deliverable checking, final summary drafting, and final handoff packaging as implemented.

Existing integration tools:

- `project_setup`: safe dashboard wrapper around `setup_eoat_project.py --safe`
- `daily_status_summary`: existing daily report script
- `foundation_validation`: `tools/validate_project_foundation.py`
- `eoat_audit_form`: `tools/audit_entry_tool.py`
- `photo_intake`: `tools/photo_intake_tool.py`
- `interview_form`: `tools/interview_entry_tool.py`
- `audit_progress_dashboard`: `tools/audit_progress_report.py`
- `issue_analysis`: `tools/issue_category_report.py`
- `documentation_gap_scanner`: `tools/documentation_gap_report.py`
- `fmea_lite_builder`: `tools/fmea_lite_builder.py`
- `pilot_candidate_ranking`: `tools/rank_pilot_candidates.py`
- `kpi_dashboard_builder`: `tools/build_kpi_dashboard.py`
- `pm_checklist_generator`: `tools/generate_pm_checklists.py`
- `bom_spares_standardization`: `tools/bom_standardization_report.py`
- `weekly_summary`: `tools/weekly_summary_generator.py`
- `mentor_meeting_prep`: `tools/mentor_meeting_brief.py`
- `morning_planner`: `tools/morning_project_planner.py`
- `final_presentation_helper`: `tools/presentation_content_exporter.py`
- `final_deliverable_check`: `tools/final_deliverable_check.py`
- `final_project_summary`: `tools/final_project_summary.py`
- `final_handoff_builder`: `tools/final_handoff_builder.py`

Phase 4 tools are read-only for the workbook by default. They generate Markdown, CSV, DOCX checklists when requested and available, and activity log entries.

Phase 5 tools are also read-only for the workbook by default. They create timestamped presentation asset folders, final summary drafts, deliverable check reports, and copied handoff packages.

Phase 6 release tools:

- `system_audit`: `tools/system_audit.py`
- `workflow_runner`: `tools/run_workflow.py`
- `project_backup`: `tools/project_backup.py`
