# EOAT Command Center Current-State Entry Points And Workflow Map

Date: 2026-05-27

Phase: 0 - Current-State Audit and Safety Baseline

This document maps the current startup paths, standalone entry points, and major workflows before feature-expansion work begins.

## GUI Startup

Primary GUI command:

```powershell
python run_dashboard.py
```

Startup path:

1. `run_dashboard.py` imports and calls `app.main.main()`.
2. `app/main.py` creates `QApplication`, sets app name/font, loads `UserConfig`, applies the selected theme, and acquires `SingleInstanceGuard`.
3. `DashboardWindow` is created from `app/dashboard_ui.py`.
4. `DashboardWindow` builds the sidebar from `NAV_SECTIONS` in `app/navigation.py`.
5. Each page starts as a placeholder in a `QStackedWidget`.
6. Pages are lazy-loaded through the hardcoded factory mapping in `DashboardWindow._build_page_factories()`.
7. Home opens first.

Smoke-test mode:

```powershell
$env:EOAT_COMMAND_CENTER_SMOKE_TEST='1'
python run_dashboard.py
```

When the smoke-test environment variable is set, the app quits shortly after startup.

## Dashboard Launchers

Current launcher files:

- `run_dashboard.py`: direct Python app entry.
- `run_dashboard.ps1`: PowerShell launcher.
- `run_dashboard.bat`: batch launcher.
- `create_dashboard_launcher.py`: creates/updates launcher conveniences.

These launchers should remain available in future phases.

## Standalone CLI And Tool Entry Points

Most CLI wrappers live in `tools/` and call reusable `core/` functions. They preserve local-first workflows outside the GUI.

Current tool wrappers:

- `tools/audit_entry_tool.py`
- `tools/audit_progress_report.py`
- `tools/bom_standardization_report.py`
- `tools/build_kpi_dashboard.py`
- `tools/documentation_gap_report.py`
- `tools/final_deliverable_check.py`
- `tools/final_handoff_builder.py`
- `tools/final_project_summary.py`
- `tools/fmea_lite_builder.py`
- `tools/generate_pm_checklists.py`
- `tools/interview_entry_tool.py`
- `tools/issue_category_report.py`
- `tools/mentor_meeting_brief.py`
- `tools/morning_project_planner.py`
- `tools/photo_intake_tool.py`
- `tools/presentation_content_exporter.py`
- `tools/project_backup.py`
- `tools/rank_pilot_candidates.py`
- `tools/run_scheduled_summaries_test.py`
- `tools/run_workflow.py`
- `tools/system_audit.py`
- `tools/validate_project_foundation.py`
- `tools/weekly_summary_generator.py`

Other root-level script entry points:

- `setup_eoat_project.py`
- `daily_status_summary.py`
- `run_daily_status.ps1`

## App Initialization Sequence

The current app initialization sequence is:

1. Load config from ignored local config if present, otherwise default to synthetic demo project.
2. Apply theme from config.
3. Start single-instance guard.
4. Build dashboard shell.
5. Create navigation placeholders for each page.
6. Lazy-load Home.
7. Home collects a quick status snapshot using light metadata/cache checks.
8. Deep refresh and tool actions run through the background task manager.

Current quick/deep dashboard behavior:

- Quick status uses cached dashboard data where possible.
- Deep refresh recalculates workbook health, audit progress, KPI, documentation, scheduled-report status, and other heavier metrics.
- Cache currently lives under the active project root's ignored project admin cache folder.
- Performance timings currently write to an ignored local project log.

## Project Root And Demo Mode

Default project root is `examples/demo_project/`.

`core/project_root_status.py` identifies demo mode versus real project mode. Home and Settings display the active project root state and warn when the demo project is active.

Local config files are ignored and must not be committed.

## Audit Load Workflow

Current audit load flow:

1. `AuditPage` refreshes audit ID/source choices through `core.audit_compatibility.list_audit_options()`.
2. User selects or enters an Audit ID.
3. `AuditPage.load_existing_audit()` calls `core.audit_entries.load_audit_entry()`.
4. The row is normalized/repaired for legacy positional shifts where needed.
5. Robot-side pneumatic circuit values are optionally loaded from `Robot_Info.xlsx` through `core.robot_info.load_robot_info_for_audit_entry()`.
6. The UI populates form fields.
7. Field visibility is recalculated from `core.audit_field_rules`.
8. Empty Only view records the currently missing/blank fields for focused editing.
9. Annotation indicators refresh for the loaded audit fields.

Current limitation: there is no dirty-form protection yet, so loading another audit can replace unsaved form state. That belongs to Phase 2.

## Audit Save Workflow

Current GUI save flow:

1. `AuditPage.save_audit()` collects the current form entry.
2. The page decides whether update is allowed based on the current loaded audit ID.
3. Save runs as a background task through `run_tool_background()`.
4. `AuditPage._save_audit_workflow()` calls `core.audit_entries.save_audit_entry_with_compatibility_autorun()`.
5. `save_audit_entry()` normalizes/defaults values and validates the entry.
6. A workbook backup is created before writing the master workbook.
7. Workbook schema migrations/repairs run where currently supported.
8. The EOAT Inventory row is added or updated.
9. Non-applicable fields save as `N/A` according to field rules.
10. Audit by Press is refreshed.
11. Linked compatible rows are synced from the physical source audit.
12. Compatibility autorun checks for required compatible rows and creates missing compatible entries where possible.
13. `AuditPage._save_audit_workflow()` updates the small `Robot_Info.xlsx` workbook through `core.robot_info.upsert_robot_info_from_audit()`.
14. Annotation tag colors for that audit are batch-synced to the workbook when applicable.
15. Activity/performance events are logged to ignored project output locations.
16. The UI refreshes audit selector and compatibility source lists.

Current safety behavior:

- Workbook writes create backups.
- Existing audit IDs require update mode.
- Non-applicable fields are cleared to `N/A`.
- Compatibility save/autorun is part of the normal save path.

Current limitation:

- There is no compatibility impact preview yet. That belongs to Phase 2.

## Compatibility Workflow

Current compatibility workflow:

1. A physical audited row is selected as the source.
2. `core.audit_compatibility.build_compatibility_candidates()` loads the source row and compares required machine/tool relationships from the press capacity data.
3. Candidates are classified as create-compatible, already audited, already compatible, or conflict/review needed.
4. User-selected candidates are passed to `core.audit_compatibility.create_compatibility_entries()`.
5. The master workbook is backed up.
6. New compatible rows are copied from the source audit, assigned new Audit IDs, marked as compatible, linked to Source Audit ID, and normalized.
7. Saving a physical audit also syncs inherited/system-managed values into linked compatible rows.

## Small Robot_Info.xlsx Workflow

Current Robot Info workflow:

1. `core.robot_info.ensure_robot_info_workbook()` creates or upgrades the workbook with the small header set.
2. `AuditPage` loads existing circuit values for the current audit key when available.
3. On audit save, `core.robot_info.upsert_robot_info_from_audit()` validates robot circuit values.
4. A Robot Info workbook backup is created before writing.
5. The row is keyed by Plant/Area, Machine Number, Robot Type, and Robot Identifier.
6. Only robot-side pneumatic circuit counts and basic tracking fields are updated.
7. `core.robot_info.validate_robot_info_workbook()` is called by foundation validation.

Important scope boundary: this workflow must remain small. Do not add a full Robot Info entity system.

## Workbook Validation Workflow

Current validation entry points:

- GUI: Workbook Health page.
- CLI: `tools/validate_project_foundation.py`.
- Core: `core.validation.run_foundation_validation()`.

Current validation flow:

1. Resolve project paths.
2. Confirm expected project folders.
3. Confirm daily/weekly/activity folders where applicable.
4. Open the master workbook with openpyxl.
5. Check expected workbook sheets and headers from schema.
6. Check Audit by Press generated view status.
7. Validate EOAT Inventory rows for duplicate Audit IDs, applicable blank/`N/A` major fields, stale hidden values, hybrid completeness warnings, semantic warnings, invalid dropdown values, invalid numeric values, missing EOAT Moves, and blank cells.
8. Validate the small Robot Info workbook.
9. Check project schedule/task progress files.
10. Check project README and toolkit usage guide.
11. Write a markdown validation report when requested.
12. Log the tool run when requested.

Current limitation: findings are not yet a structured validation finding model. That belongs to a later phase.

## Notes, Tags, And Annotation Workflow

Current annotation storage:

- SQLite database under the active project root's ignored project data folder.

Current annotation workflow:

1. `AnnotationService` initializes the database and seeds default tags.
2. Notes can be created, searched, updated, archived, linked to targets, linked to tags, and exported.
3. Tags can be created, searched, updated, archived, assigned to targets, removed, and exported.
4. Targets represent audit fields, project items, reports, or other entities.
5. Audit field tag buttons create or find audit-field targets.
6. Workbook color sync writes the highest-priority active tag color to matching audit workbook cells.
7. Current suggested annotations are generated by simple rules in `core/annotations/suggestions.py`.
8. The Audit page currently displays suggestions as text and tells the user to use field tag buttons to apply them manually.

Current limitation: there is no full suggested annotation apply/ignore table and no unified Open Items board yet. Those belong to Phase 4.

## Scheduled Report Workflow

Current scheduled summary files:

- `scripts/install_summary_schedules.ps1`
- `scripts/check_summary_schedules.ps1`
- `scripts/uninstall_summary_schedules.ps1`
- `scripts/run_daily_summary.ps1`
- `scripts/run_weekly_summary.ps1`

Current core behavior:

1. `core.scheduled_reports.evaluate_summary_schedule()` decides whether daily or weekly automation should run.
2. Daily summaries are expected Monday through Thursday at 7:00 PM local scheduler time.
3. Weekly summaries are expected Friday at 7:00 PM local scheduler time.
4. Existing same-date reports are detected and skipped to avoid overwrites.
5. Dry-run reports go under a test reports folder in the active project root.
6. Attempts are logged to the scheduled tools log.
7. GUI Scheduled Reports page can refresh status, run manual now, run dry-runs, install/repair tasks, uninstall tasks, and open logs/folders.

Current limitations:

- Calendar preview is not implemented yet.
- Catch-up workflow is not implemented yet.
- Task Scheduler preflight is limited compared with the roadmap target.
- Smarter report context is still basic.

## Report And Handoff Workflows

Reports page:

1. Discovers recent report folders/files through `core.reports`.
2. Previews readable report formats.
3. Provides weekly summary and mentor brief generation dialogs.
4. Shows daily summary command guidance.

Final Handoff page:

1. Runs final deliverable check.
2. Exports presentation assets.
3. Generates final summary draft.
4. Builds or dry-runs copied handoff package.
5. Does not move originals.

## Photo Workflow

Current photo workflow:

1. Photos page lists files in the incoming photo folder.
2. User selects a tool, photo type, and action.
3. `core.photo_indexing` copies or moves supported image files into the matching tool/photo-type folder, creating only that destination folder when needed.
4. Photo Index workbook rows are written.

Current limitation: photo evidence coverage by audit/category is not implemented yet. That belongs to Phase 9.

## Demo Project Behavior

The synthetic demo project is safe for tests, local screenshots, and GitHub examples. It includes fake workbooks, fake schedules, fake reports, fake placeholder photos, and synthetic app runtime outputs.

Future phases must preserve:

- Default startup on demo project.
- Visible demo mode warning.
- Existing demo workbooks and tests.
- No requirement for real project data to run the app.

## Safety And Release Workflow

Current safety controls:

- `.gitignore` excludes local config, real project folders, workbooks by default, generated outputs, logs, caches, photos, backups, and runtime databases.
- `scripts/repo_safety_audit.py` scans for unsafe files/content.
- `scripts/pre_commit_check.ps1` provides a local safety check entry point.
- README documents the NDA boundary and publishing checklist.

Current local risk:

- Ignored local/generated artifacts exist in the working tree and cause the broad safety audit to fail.
- Tracked files scan clean, but developers must avoid force-adding ignored artifacts.

## Phase 0 Conclusion

The current project is ready for documentation-only Phase 0 work. Source changes for later phases should proceed one phase at a time, with particular care around the Audit page, hardcoded navigation/page creation, workbook writes, scheduled report outputs, and local data safety.
