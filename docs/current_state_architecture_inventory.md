# EOAT Command Center Current-State Architecture Inventory

Date: 2026-05-27

Phase: 0 - Current-State Audit and Safety Baseline

This document records the current repository architecture before the next feature expansion cycle. It is intentionally descriptive only. No major behavior changes are part of Phase 0.

## Safety Boundary

The repository should contain only source code, generic documentation, sanitized templates, tests, and synthetic demo data.

Do not commit real project workbooks, generated reports, photos, logs, caches, local config, private paths, customer names, mold numbers, part numbers, capacity data, downtime data, scrap data, maintenance histories, or operational details.

`Robot_Info.xlsx` remains a small workbook for robot-side pneumatic circuit counts only:

- Robot Vacuum Circuits.
- Robot Pressure Circuits.
- Robot Interchangeable Circuits.

It may keep basic tracking fields such as Plant/Area, Machine Number, Last Audit ID, Last Updated, and Notes. It must not become a full robot master database.

## Top-Level Layout

| Path | Current role |
| --- | --- |
| `app/` | PySide6 desktop dashboard, page classes, widgets, navigation, background task runner, theme handling, and single-instance guard. |
| `core/` | Reusable business logic for workbooks, validation, reports, annotations, scheduling, audit rules, safe files, config, paths, and analysis. |
| `tools/` | Importable command-line wrappers around `core/` functions. These preserve standalone CLI workflows. |
| `scripts/` | Utility and automation scripts, including repo safety audit, scheduled summary task install/check/run scripts, package scripts, and pre-commit helper. |
| `data_templates/` | Committed sanitized JSON schema, tool registry seed, schedules, task templates, checklist templates, and issue/FMEA defaults. |
| `templates/` | Committed sanitized CSV templates. |
| `examples/demo_project/` | Synthetic demo project used by default on a clean checkout and by tests. |
| `tests/` | Unit, integration, fixture, and UI smoke/workflow tests using synthetic data. |
| `docs/` | Generic documentation, reports, QA checklists, planning material, and Phase 0 baseline docs. |
| `config/` | `config.example.json` is committed. Local config files are ignored and must stay uncommitted. |

Ignored local/generated areas include real project folders, local config, generated reports, logs, caches, workbook backups, photos, and runtime annotation databases.

## App Layer

The GUI starts through `run_dashboard.py`, calls `app.main.main()`, creates a `QApplication`, loads config, applies the theme, enforces a single-instance guard, and creates `DashboardWindow`.

`app/dashboard_ui.py` currently owns:

- Main window creation.
- Sidebar tree navigation.
- Lazy page placeholders.
- Hardcoded page factory mapping.
- Project-root and settings refresh callbacks.
- Status bar progress for background tasks.
- Annotation target navigation helpers.

`app/navigation.py` currently defines static `NAV_SECTIONS` and `NAV_ITEMS`.

`app/task_runner.py` provides `TaskRequest`, `TaskResult`, `ActiveTaskGuard`, and `BackgroundTaskManager` for Qt background tasks. It prevents duplicate task IDs and concurrent project/workbook mutations.

`app/page_tasks.py` wraps background tool execution for pages and converts results into `ToolResult` output panels.

### Current Pages

| Page file | Current purpose |
| --- | --- |
| `app/pages/home.py` | Home dashboard, quick/deep status snapshots, project root display, demo mode warning, quick actions, workflow buttons, and navigation requests. |
| `app/pages/schedule.py` | Schedule/task progress loading, task status display/update, and morning plan generation. |
| `app/pages/audit.py` | Large current audit page for audit entry, dynamic field visibility, machine lookup, load/save/update, compatibility entries, annotation field buttons, suggested annotations text, Robot Info handoff, and interview notes. |
| `app/pages/notes.py` | Notes search, edit, target linking, tags, attachments, and note export actions. |
| `app/pages/tags.py` | Tag management, tag assignments, target navigation, workbook color sync, and tag export actions. |
| `app/pages/photos.py` | Incoming photo list, naming preview, copy/move photo intake, and Photo Index writes. |
| `app/pages/audit_progress.py` | Audit progress metrics and report generation. |
| `app/pages/issue_analysis.py` | Issue log analysis and report generation. |
| `app/pages/fmea.py` | FMEA-lite analysis/reporting. Suggestion application is not a full workflow yet. |
| `app/pages/pilot_candidates.py` | Pilot candidate ranking and report generation. |
| `app/pages/kpi_dashboard.py` | KPI dashboard summary and export generation. |
| `app/pages/standards_docs.py` | Documentation gap scan and report generation. |
| `app/pages/pm_checklists.py` | Generic and selected-audit PM checklist generation. |
| `app/pages/bom_spares.py` | BOM/spare parts standardization analysis and report generation. |
| `app/pages/reports.py` | Recent reports, previews, daily summary command guidance, weekly summaries, and mentor briefs. |
| `app/pages/scheduled_reports.py` | Current scheduled report status, manual daily/weekly runs, dry runs, install/repair, uninstall, and folder/log opening. |
| `app/pages/handoff.py` | Final deliverable status, presentation assets, final summary draft, and handoff package dry-run/build. |
| `app/pages/tool_registry.py` | Tool registry table loaded from `data_templates/tool_registry_seed.json`. |
| `app/pages/workbook_health.py` | Foundation validation, workbook schema repair, Audit by Press refresh, report output display. |
| `app/pages/settings.py` | Project root, theme/debug/git config, system audit, backups, and release-hardening actions. |
| `app/pages/base.py` | Simple placeholder page class. |
| `app/pages/analysis_widgets.py` | Shared table/card helpers for analysis pages. |

### Current Widgets

| Widget file | Current purpose |
| --- | --- |
| `app/widgets/status_card.py` | Small status card display. |
| `app/widgets/report_viewer.py` | Text/report preview widget. |
| `app/widgets/tool_run_panel.py` | Tool result display surface. |
| `app/widgets/task_table.py` | Task table helper. |
| `app/widgets/workflow_card.py` | Workflow action card. |
| `app/widgets/chart_panel.py` | Chart container. |
| `app/widgets/file_picker.py` | File/folder picker helpers. |
| `app/widgets/note_editor.py` | Shared note editing form. |
| `app/widgets/tag_picker.py` | Tag selection widget. |
| `app/widgets/field_tag_button.py` | Audit field tag/note button and dialogs. |
| `app/widgets/annotation_target_picker.py` | Annotation target picker widget. |
| `app/widgets/annotation_target_navigator.py` | Opens annotation targets in the right app page/context. |
| `app/widgets/open_items_panel.py` | Existing compact open-items style summary panel, not the full future Open Items board. |

## Core Layer

### Foundations

| Module | Current purpose |
| --- | --- |
| `core/constants.py` | App name, toolkit root, default demo project root, config paths, expected project folders, workbook names. |
| `core/config.py` | `UserConfig`, config load/save, local config fallback handling. |
| `core/paths.py` | Central project path resolver for master workbook, Robot Info workbook, reports, logs, cache, annotations database, and numbered project folders. |
| `core/result.py` | `ToolResult` dataclass and markdown rendering. |
| `core/safe_files.py` | Directory creation, timestamped names, backup, safe text write, and safe copy helpers. |
| `core/workbook_io.py` | Openpyxl row/header helpers. |
| `core/workbook_schema.py` | Loads workbook schema from `data_templates/workbook_schema.json`. |
| `core/logging.py` | Activity/tool run logging to project output locations. |
| `core/performance.py` | Current text performance logging. |
| `core/openers.py` | Open file/folder helpers. |
| `core/git_activity.py` | Git status helpers for dashboard/system checks. |

### Audit And Workbook Modules

| Module | Current purpose |
| --- | --- |
| `core/audit_entries.py` | Audit ID generation, normalization, defaulting, field validation, schema migration/repair, workbook save/update, compatibility autorun, action item creation, and Audit by Press refresh. |
| `core/audit_field_rules.py` | EOAT applicability rules, non-applicable reasons, field groups, hidden/stale logic, hybrid warnings, semantic warnings, and required-field lists. |
| `core/audit_compatibility.py` | Compatibility source options, required relationship loading from capacity data, compatibility candidate building, compatible row creation, and linked compatible row sync. |
| `core/audit_by_press.py` | Generated workbook sheet that groups EOAT inventory rows by press/machine. |
| `core/audit_constants.py` | Entry Type and compatibility metadata constants. |
| `core/robot_info.py` | Small Robot Info workbook creation/load/upsert/validation for robot-side pneumatic circuit counts and basic tracking fields. |
| `core/press_lookup.py` | Master press list and capacity lookup helpers for machine/audit autofill. |
| `core/gripper_fields.py` | Current gripper friendly-name to workbook model mapping. |
| `core/action_items.py` | Workbook-backed action item creation. |
| `core/validation.py` | Foundation validation, workbook/schema checks, audit truth-rule warnings, Robot Info validation, schedule checks, and markdown report writing. |

### Annotation Modules

| Module | Current purpose |
| --- | --- |
| `core/annotations/database.py` | Annotation SQLite path, connection, initialization, and default tag seeding. |
| `core/annotations/migrations.py` | Annotation schema creation and migration versioning. |
| `core/annotations/models.py` | Annotation dataclasses. |
| `core/annotations/service.py` | Main notes, tags, targets, assignments, suggestions, exports, summaries, and workbook color sync service. |
| `core/annotations/suggestions.py` | Current simple suggested-annotation rules. |
| `core/annotations/targets.py` | Target ID normalization/display helpers. |
| `core/annotations/tag_colors.py` | Default tag definitions, color priority, Excel fill mapping. |
| `core/annotations/exports.py` | Markdown/Excel note and tag exports. |

### Planning, Reports, And Analysis Modules

| Module | Current purpose |
| --- | --- |
| `core/schedule.py` | Project date/week/day resolution and schedule file loading. |
| `core/task_progress.py` | Task progress JSON load/update helpers. |
| `core/morning_context.py` | Context gathering for morning plan generation. |
| `core/morning_planner.py` | Morning plan markdown generation. |
| `core/scheduled_reports.py` | Daily/weekly summary scheduling decisions, duplicate prevention, dry-run report folders, status discovery, manual runs, and scheduled task script wrappers. |
| `core/weekly_summary.py` | Weekly summary markdown generation from schedule/daily reports/workbook metrics. |
| `core/reports.py` | Report folder discovery and preview reading. |
| `core/analysis_common.py` | Shared report and table helpers for analysis modules. |
| `core/audit_progress.py` | Audit progress metrics and reports. |
| `core/issue_analysis.py` | Issue log analysis. |
| `core/documentation_gaps.py` | Documentation gap scanning. |
| `core/fmea_analysis.py` | FMEA-lite analysis. |
| `core/pilot_scoring.py` | Pilot candidate scoring. |
| `core/kpi_analysis.py` | KPI summary/reporting. |
| `core/pm_checklists.py` | PM checklist generation. |
| `core/bom_standardization.py` | BOM/spare parts standardization reporting. |
| `core/mentor_brief.py` | Mentor meeting brief generation. |
| `core/final_common.py` | Shared final output helpers. |
| `core/presentation_export.py` | Final presentation asset export. |
| `core/deliverable_check.py` | Final deliverable readiness scan. |
| `core/final_summary.py` | Final summary draft generation. |
| `core/final_handoff.py` | Final handoff package copy/build logic. |
| `core/docx_writer.py` | Optional DOCX writer shim. |
| `core/charting.py` | Charting placeholder/shim. |

### System And Tooling Modules

| Module | Current purpose |
| --- | --- |
| `core/tool_registry.py` | Loads tool registry metadata from JSON seed. |
| `core/tool_runner.py` | Runs Python scripts as tools. |
| `core/workflows.py` | High-level daily/weekly/final workflow runner. |
| `core/system_audit.py` | Import/file/CLI/foundation validation checks. |
| `core/project_setup.py` | Safe wrapper around setup script. |
| `core/project_backup.py` | Workbook/light project backup helpers. |
| `core/project_root_status.py` | Demo/real project root detection and validation. |
| `core/snapshots.py` | Empty placeholder module. |
| `core/models.py` | Minimal shared model placeholder. |
| `core/tool_fields.py` | Current tool field name constants and legacy alias. |

## Tools

`tools/` exposes standalone wrappers for existing workflows. Current wrappers include audit entry, interview entry, photo intake, validation, audit progress, issue analysis, documentation gaps, FMEA-lite, pilot ranking, KPI dashboard, PM checklists, BOM/spares, weekly summary, mentor brief, morning planner, final deliverable check, final project summary, final handoff, presentation export, system audit, workflow runner, project backup, and scheduled-summary tests.

CLI tools must remain supported during future phases.

## Scripts

| Script | Current purpose |
| --- | --- |
| `scripts/repo_safety_audit.py` | Scans repository files for unsafe paths, real data files, local configs, generated outputs, and suspicious content. |
| `scripts/pre_commit_check.ps1` | Local pre-commit helper for the safety audit. |
| `scripts/install_summary_schedules.ps1` | Installs/repairs Windows Task Scheduler tasks for daily/weekly summaries. |
| `scripts/check_summary_schedules.ps1` | Checks installed scheduled summary tasks. |
| `scripts/uninstall_summary_schedules.ps1` | Removes scheduled summary tasks. |
| `scripts/run_daily_summary.ps1` | Runs due daily summary automation from Task Scheduler or manually. |
| `scripts/run_weekly_summary.ps1` | Runs due weekly summary automation from Task Scheduler or manually. |
| `scripts/build_package.py` | Packaging helper. |
| `scripts/smoke_test_package.py` | Package smoke-test helper. |

## Templates And Demo Data

`data_templates/` contains committed generic JSON templates and schema data. `templates/` contains committed generic CSV templates.

`examples/demo_project/` is the default project root for a clean checkout. It contains synthetic workbooks, fake schedules, fake reports, placeholder photos, and demo annotation/runtime outputs. Some demo runtime folders are ignored after local smoke tests.

## Test Layout

| Path | Current purpose |
| --- | --- |
| `tests/*.py` | Main unit and workflow tests for core modules, CLI help, repo safety, config, scheduled reports, annotations, validation, audit behavior, Robot Info, and UI smoke. |
| `tests/fixtures/` | Synthetic project/workbook/config/image fixture helpers. |
| `tests/integration/` | Fake project full-workflow integration coverage. |
| `tests/ui/` | PySide UI workflow and smoke tests. These are more expensive and may require a suitable GUI/offscreen environment. |

## Current Architecture Risks

- `app/pages/audit.py` is a large mixed-responsibility page and is the main future refactor target.
- Navigation and page factory logic are hardcoded in `app/navigation.py` and `app/dashboard_ui.py`.
- Lifecycle hooks and app-level event bus do not yet exist.
- Validation warnings are currently mostly human-readable strings, not structured UI records.
- Full pytest can be slow on the current workspace; focused subsets are more practical for quick baseline signal.
- Local ignored artifacts currently exist and cause the broad repo safety audit to fail, even though the tracked tree scan is clean.
