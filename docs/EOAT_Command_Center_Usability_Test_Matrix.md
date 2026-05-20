# EOAT Command Center Usability Test Matrix

This matrix tracks the fake-project usability phase. Automated tests use a temp project rooted at `Fake_EOAT_Standardization_Project` with synthetic workbook rows, schedule files, photo files, reports, config, and activity logs.

| Area/Page | User Action | Test Type | Fake Data Used | Expected Result | Automated Test Name | Status | Notes |
|---|---|---|---|---|---|---|---|
| App Startup | Launch dashboard with fake config | Automated UI | Fake config and project root | Main window opens on Home, sidebar exists, fake root is active | `test_full_app_startup_uses_fake_project_and_resolves_day2` | Pass | Uses PySide6 offscreen mode |
| Home | Resolve current project day | Automated UI | Start date `2026-05-18`, frozen date `2026-05-19` | Week 1 Day 2 appears | `test_full_app_startup_uses_fake_project_and_resolves_day2` | Pass | Covers Morning Plan date regression |
| Navigation | Select every sidebar item | Automated UI | Full fake project | Each page loads and heading appears | `test_navigation_loads_every_sidebar_page_with_primary_controls` | Pass | Covers all major pages |
| Settings | Switch light/dark theme | Automated UI | Fake config | Theme changes and saves without real config mutation | `test_theme_switching_persists_and_pages_survive_dark_and_light` | Pass | Verifies buttons/tables styled |
| Home | Generate Morning Plan | Automated UI | Week 1 Day 2 schedule/progress | `Week1_Day2_Morning_Plan_2026-05-19.md` created | `test_morning_plan_user_flow_creates_week1_day2_plan` | Pass | Verifies sections and no Day 1 title |
| Home | Run Daily Start Workflow | Automated UI | Fake schedule/workbook | Workflow report, morning plan, activity log created | `test_daily_start_workflow_from_home_generates_outputs_and_activity` | Pass | Real workflow logic |
| Schedule | Mark task In Progress and Complete | Automated UI | Week 1 progress JSON | Progress JSON persists and refresh shows Complete | `test_schedule_task_status_persists_and_completed_task_leaves_main_plan` | Pass | Verifies completed task leaves main plan |
| EOAT Audit | Save complete audit entry | Automated UI | Press 104 form data | Workbook row created and success shown | `test_save_complete_and_optional_missing_audit_entries` | Pass | Workbook backup created |
| EOAT Audit | Save valid entry with optional gaps | Automated UI | Press 105 minimal valid data | Workbook row created with warnings allowed | `test_save_complete_and_optional_missing_audit_entries` | Pass | Required fields enforced |
| EOAT Audit | Save invalid required fields | Automated UI | Blank required fields | Friendly validation error, no row added | `test_invalid_audit_entry_shows_friendly_error_without_workbook_row` | Pass | No traceback |
| Photos | Refresh incoming photos | Automated UI | Generated tiny PNG/JPG files | Incoming list populates | `test_photo_intake_previews_copies_and_indexes_selected_images` | Pass | No real photos used |
| Photos | Preview rename/move | Automated UI | Selected fake images | Safe target names shown | `test_photo_intake_previews_copies_and_indexes_selected_images` | Pass | Path remains temp project |
| Photos | Confirm intake | Automated UI | Metadata for Press 101 | Images copied and Photo Index updated | `test_photo_intake_previews_copies_and_indexes_selected_images` | Pass | Activity logged |
| Photos | Empty incoming folder | Automated UI | Empty folder | Helpful empty state, no crash | `test_photo_intake_empty_incoming_folder_has_helpful_empty_state` | Pass | Also tested confirm without selection |
| Workbook Health | Run Foundation Validation | Automated UI | Fake workbook/schema | Cards update and report generated | `test_workbook_validation_generates_report_updates_cards_and_stubs_open` | Pass | Open folder is stubbed |
| Audit Progress | Refresh metrics/report | Automated UI | Fake audit/photo/interview/issue rows | Metrics > 0 and report generated | `test_audit_progress_metrics_and_report` | Pass | Real workbook analysis |
| Issues | Run Issue Analysis | Automated UI | Vacuum loss, Sensor failure, Tubing wear | Category, missing risk, FMEA suggestion tables populate | `test_issue_analysis_reports_fake_categories_and_missing_risk` | Pass | Report generated |
| FMEA-Lite | Run analysis and refresh | Automated UI | FMEA rows plus issue log | Top RPN and suggestion table populate | `test_fmea_lite_refresh_run_and_disabled_planned_button` | Pass | Planned apply button stays disabled |
| Pilot Candidates | Run ranking | Automated UI | Candidate row and inventory flags | Ranking table contains fake candidate | `test_pilot_ranking_includes_candidate_and_empty_state` | Pass | Separate no-candidate case covered |
| KPI Dashboard | Run KPI analysis | Automated UI | Downtime/drops/mis-picks/scrap rows | KPI cards and tables populate | `test_kpi_dashboard_cards_and_report` | Pass | Report generated |
| Standards Docs | Run Documentation Gap Scan | Automated UI | Complete and incomplete EOAT rows | Gap tables distinguish missing docs | `test_standards_documentation_gap_scan` | Pass | CSV/report generated |
| PM Checklists | Generate generic templates | Automated UI | Template data | Markdown checklist files created | `test_pm_checklist_generic_specific_and_invalid_friendly_fallback` | Pass | DOCX remains optional |
| PM Checklists | Generate by Audit ID | Automated UI | `AUD-20260518-001` | Press 101 checklist preview shown | `test_pm_checklist_generic_specific_and_invalid_friendly_fallback` | Pass | Invalid ID falls back with warning |
| BOM / Spare Parts | Run analysis | Automated UI | Cup/sensor/fitting/documentation fields | Common and missing-data tables populate | `test_bom_spare_parts_analysis_populates_common_and_missing_tables` | Pass | Report generated |
| Reports | Refresh folders and preview report | Automated UI | Seed and generated reports | Recent files list and preview work | `test_reports_page_refresh_preview_open_stub_and_weekly_summary` | Pass | Open selected folder stubbed |
| Reports | Generate weekly summary | Automated UI | Accepted fake dialog | Week 1 summary created | `test_reports_page_refresh_preview_open_stub_and_weekly_summary` | Pass | No external app launched |
| Tool Registry | Review and filter tools | Automated UI | Registry seed | Major tools listed and filter works | `test_tool_registry_lists_expected_major_tools_and_filters` | Pass | Disabled/planned state visible in table |
| Final Handoff | Run deliverable check | Automated UI | Fake outputs and missing deliverables | Found/Partial/Missing table populates | `test_final_handoff_deliverable_assets_summary_dry_run_and_package` | Pass | Report generated |
| Final Handoff | Generate assets, summary, dry-run package | Automated UI | Fake reports/workbook | Outputs created under fake project | `test_final_handoff_deliverable_assets_summary_dry_run_and_package` | Pass | Dry run does not copy package files |
| Final Handoff | Build package normally | Automated UI | Fake generated reports | Package folder and index created | `test_final_handoff_deliverable_assets_summary_dry_run_and_package` | Pass | Activity logged |
| Settings | Save/reload settings | Automated UI | Stubbed config path | Theme persists without real config mutation | `test_settings_save_reload_theme_audit_backups_and_open_stub` | Pass | Stubs config read/write |
| Settings | System audit and backups | Automated UI | Fake project | Audit report and backups created in fake project | `test_settings_save_reload_theme_audit_backups_and_open_stub` | Pass | Open backups stubbed |
| Error States | Missing workbook | Automated UI | Minimal fake project | Friendly failure, no crash | `test_missing_master_workbook_error_is_friendly` | Pass | No traceback wall |
| Error States | Missing schedule | Automated UI | Minimal fake project | Empty state shown | `test_missing_schedule_file_empty_state_does_not_crash` | Pass | No crash |
| Error States | Missing start date | Automated UI | Config without start date | Fallback/inference warning visible | `test_missing_project_start_date_fallback_is_visible` | Pass | Covers resolver fallback |
| Error States | Corrupted task JSON | Automated UI | Invalid JSON | Empty progress, no traceback | `test_corrupted_task_progress_json_shows_empty_progress_not_traceback` | Pass | Defensive parser behavior |
| Error States | Missing required workbook sheet | Automated UI | Workbook with `Issue Log` deleted | Validation reports missing sheet | `test_workbook_missing_required_sheet_reports_error_without_crash` | Pass | No crash |
| Error States | Tool exception | Automated UI | Synthetic raised exception | Failure shown without crashing | `test_tool_exception_is_captured_as_user_visible_failure` | Pass | Debug traceback not shown |
| Background Tasks | Duplicate project-write policy | Automated unit | Task guard requests | Unsafe concurrent writes rejected | `test_duplicate_project_writing_policy_rejects_conflicting_workbook_tasks` | Pass | Deterministic test-mode task manager |
| Background Tasks | Tool button recovery | Automated UI | Workbook validation | Button recovers after run | `test_tool_button_reports_running_and_controls_recover` | Pass | Long-running behavior still needs manual feel check |
| Full User Journey | Fake intern Day 2 workflow | Automated integration | Full fake project | End-to-end outputs created only in fake project | `test_fake_user_day2_workflow_end_to_end` | Pass | Marked `usability`, `integration`, `slow` |

## Commands

```powershell
python -m pytest tests/ui
python -m pytest tests/integration/test_fake_project_full_workflow.py
python -m pytest -m usability
python -m pytest -m "not slow"
python -m pytest
```
