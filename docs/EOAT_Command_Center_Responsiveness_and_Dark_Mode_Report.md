# EOAT Command Center Responsiveness and Dark Mode Report

Date: 2026-05-19

## Summary

This pass improved the EOAT Command Centerâ€™s responsiveness, added a real centralized light/dark theme system, and added a single-instance guard so future launches do not create multiple dashboard windows.

The work stayed within the existing PySide6 architecture. Existing tools, CLI scripts, workbook schemas, report folders, project data, and dashboard pages were preserved.

## Files Changed

- `app/task_runner.py` - Added a shared `QThreadPool`/`QRunnable` background task runner with task results, signal-based UI callbacks, active-task tracking, and workbook/project mutation guards.
- `app/page_tasks.py` - Added a small page helper for running ToolResult-producing functions in the background with consistent result-panel behavior.
- `app/single_instance.py` - Added a Qt local-server single-instance guard.
- `app/main.py` - Applies configured theme at startup and blocks second app instances with a friendly message.
- `app/dashboard_ui.py` - Added global status-bar feedback for running/completed/failed tasks and live theme application.
- `app/theme.py` - Rebuilt theme styling around central light/dark tokens covering windows, sidebar, cards, buttons, inputs, tabs, tables, previews, scrollbars, and progress bars.
- `app/pages/settings.py` - Replaced free-text theme field with a Light/Dark dropdown, live theme preview, persistence, and backgrounded system audit/backup actions.
- `app/pages/home.py` - Moved dashboard refresh and Home workflow actions to the background task runner.
- `app/pages/audit.py` - Backgrounded workbook-writing audit/interview saves with workbook lock protection.
- `app/pages/photos.py` - Backgrounded photo intake with project/workbook mutation protection.
- `app/pages/schedule.py` - Backgrounded morning-plan generation.
- `app/pages/workbook_health.py` - Backgrounded foundation validation.
- `app/pages/audit_progress.py` - Backgrounded progress report generation.
- `app/pages/issue_analysis.py` - Backgrounded issue analysis report generation.
- `app/pages/fmea.py` - Backgrounded FMEA report generation.
- `app/pages/pilot_candidates.py` - Backgrounded pilot ranking report generation.
- `app/pages/kpi_dashboard.py` - Backgrounded KPI report generation.
- `app/pages/standards_docs.py` - Backgrounded documentation gap report generation.
- `app/pages/pm_checklists.py` - Backgrounded PM checklist generation.
- `app/pages/bom_spares.py` - Backgrounded BOM/spares report generation.
- `app/pages/reports.py` - Backgrounded daily summary, weekly summary, and mentor brief generation.
- `app/pages/handoff.py` - Backgrounded final deliverable checks, presentation assets, summary generation, handoff package builds, final review workflow, and backups.
- `run_dashboard.ps1`, `run_dashboard.bat`, `create_dashboard_launcher.py` - Updated launchers to prefer the direct installed Python executable before falling back to `py.exe`.
- `%USERPROFILE%\Desktop\EOAT Command Center.cmd` - Regenerated desktop launcher with the direct Python path preference.
- `tests/test_task_runner.py` - Added background runner and duplicate/conflicting task guard tests.
- `tests/test_theme.py` - Added theme token and stylesheet tests.
- `tests/test_single_instance.py` - Added single-instance guard tests.
- `tests/test_ui_smoke.py` - Extended smoke tests to include dark mode and Settings theme dropdown.

## Background Task System

The dashboard now has a shared Qt-native background task system:

- Uses `QThreadPool` and `QRunnable`.
- Emits results back to the UI thread through Qt signals.
- Converts raw results and `ToolResult` values into a shared `TaskResult`.
- Keeps active runnable references until completion so workers are not garbage-collected early.
- Handles shutdown races cleanly, including smoke-test/app-close timing.
- Shows global status-bar messages such as `Running`, `Completed`, or `Failed`.

Long-running report, validation, backup, handoff, photo intake, and workbook-writing actions now use this background runner instead of blocking the UI thread.

## Task Locking

The task runner includes an in-process guard:

- Duplicate task IDs are rejected while already active.
- Workbook-writing tasks can request a workbook lock.
- Project-mutating tasks can request a project mutation lock.
- If a conflicting write/mutation is already running, the user gets a friendly message instead of launching a second unsafe operation.

This does not replace operating-system or Excel-level file locking, but it prevents the dashboard itself from starting conflicting workbook/project writes at the same time.

## Theme System

The theme system now defines central tokens for:

- Backgrounds
- Text colors
- Borders/dividers
- Accent/action colors
- Status colors
- Navigation states
- Input/table/report styling

Supported themes:

- `light`
- `dark`

Dark mode covers the main window, sidebar, grouped navigation, cards, labels, buttons, disabled buttons, inputs, combo boxes, spin boxes, checkboxes, tabs, tables, headers, list widgets, report previews, splitters, scrollbars, progress bars, and tooltips.

The Settings page now has a controlled theme dropdown. Changing it applies the theme live and saving persists it to `config/local_config.json`.

## Single-Instance Behavior

The app now uses `QLocalServer`/`QLocalSocket` to enforce one EOAT Command Center dashboard instance per user session.

If another guarded instance is already running, a second launch shows:

`EOAT Command Center is already running. Use the existing window instead of opening another copy.`

The launchers were also updated to prefer:

`C:\Path\To\python.exe`

before falling back to `py.exe`, reducing the chance that Windows starts the Python Manager shim plus a child Python process.

## Page Updates

Major slow actions were moved to background execution on:

- Home
- EOAT Audit
- Photos
- Schedule
- Workbook Health
- Audit Progress
- Issue Analysis
- FMEA-Lite
- Pilot Candidates
- KPI Dashboard
- Standards & Documentation
- PM Checklists
- BOM / Spare Parts
- Reports
- Final Handoff
- Settings

Navigation remains available while tasks run. The specific launched control can be disabled by the shared runner, and global status text indicates what is running.

## Error Handling

Normal UI panels show concise task failure summaries through `ToolResult`/`TaskResult`.

Detailed tracebacks are retained inside `TaskResult.traceback_for_debug_log_only` rather than dumped into normal user-facing UI. This keeps the app readable while still preserving useful debug detail.

## Testing

Commands run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests\test_single_instance.py tests\test_task_runner.py tests\test_theme.py tests\test_ui_smoke.py -q
python run_dashboard.py
python -m pytest
```

Results:

- Focused single-instance/task/theme/UI smoke tests: passed.
- Dashboard startup smoke test: passed.
- Full regression suite: 85 passed.

Full result:

```text
85 passed in 209.39s
```

## Performance Notes

- App startup still works in offscreen smoke mode.
- Page navigation smoke checks instantiate all pages successfully.
- Home refresh now runs in the background rather than synchronously blocking the UI thread.
- Long-running report/workbook/project actions show running feedback quickly and finish through signal callbacks.
- Theme switching from Settings applies immediately without restarting.

## Known Limitations

- True cancellation is not implemented. Long workbook writes should finish rather than be interrupted unsafely.
- Some page constructors still do lightweight initial reads when first opened; the most important long-running button actions are backgrounded.
- The in-process lock protects the dashboard from launching conflicting tasks, but it does not prevent another external Python process, Excel, or another user from touching the workbook.
- Existing dashboard processes launched before this guard was added will not know about the new single-instance server. Close those old windows once, then future launches will be guarded.
- A morning planner compatibility fix was made only to keep the active test suite passing; the morning planner feature remains owned by the other active chat.


