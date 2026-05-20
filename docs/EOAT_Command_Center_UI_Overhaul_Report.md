# EOAT Command Center UI Overhaul Report

Date: 2026-05-18

## Summary

This UI pass reorganized the EOAT Command Center into a calmer engineering dashboard without rebuilding the app or removing existing tools. The main problems addressed were the narrow sidebar, the overwhelming Home page button grid, oversized report preview areas, weak empty states, and inconsistent page hierarchy.

The app now opens at a shorter default size, uses grouped navigation, lazy-loads pages, and presents Home as a project cockpit with workflow cards instead of a wall of equal-priority buttons.

## Files Changed

- `app/dashboard_ui.py` - Replaced the flat sidebar with grouped navigation, widened the sidebar, kept lazy page loading, and set a shorter default window size.
- `app/navigation.py` - Added navigation sections for Overview, Capture, Analysis, Standards, Output, and System.
- `app/ui_constants.py` - Added shared layout constants for window size, sidebar width, margins, spacing, and preview sizing.
- `app/theme.py` - Refined the light/dark styles for a cleaner internal engineering dashboard look.
- `app/main.py` - Set a consistent Segoe UI application font.
- `app/pages/home.py` - Redesigned Home into a cockpit with project health, today's work, data progress, workflow cards, recommendations, and compact activity.
- `app/pages/photos.py` - Added a practical empty state with step-by-step photo intake instructions.
- `app/pages/schedule.py` - Made task text the lead table column, added a stronger missing-schedule message, and reduced preview dominance.
- `app/pages/issue_analysis.py` - Moved cramped side-by-side tables into tabs and reduced report preview height.
- `app/pages/fmea.py` - Added a workflow guide and clarified the planned apply-suggestions action.
- `app/pages/workbook_health.py` - Added validation status cards and a clearer report empty state.
- `app/pages/pm_checklists.py` - Grouped target, scope, and output controls and improved preview empty state.
- `app/pages/reports.py` - Added clearer folder/preview labeling and a helpful preview placeholder.
- `app/pages/handoff.py` - Added scrolling for the control side and reduced final report preview dominance.
- `app/pages/settings.py` - Grouped settings into Project Configuration, Git / External Tools, UI Preferences, and System Checks / Backups.
- `app/pages/tool_registry.py` - Added a search/filter box for the admin registry table.
- `app/widgets/status_card.py` - Standardized object names and styling hooks.
- `app/widgets/report_viewer.py` - Added consistent report viewer styling hooks and default empty state.
- `app/widgets/workflow_card.py` - Added reusable workflow card widget for grouped Home actions.
- `tests/test_ui_smoke.py` - Added UI smoke tests for app window creation, navigation, Home workflow actions, and Settings handlers.

## Navigation Changes

The sidebar is now wider and organized into logical workflow sections:

- Overview: Home, Schedule
- Capture: EOAT Audit, Photos, Audit Progress
- Analysis: Issues, FMEA-Lite, Pilot Candidates, KPI Dashboard
- Standards: Standards Docs, PM Checklists, BOM / Spare Parts
- Output: Reports, Final Handoff
- System: Tool Registry, Workbook Health, Settings

The active page remains visually highlighted, while section headers are subdued so the sidebar reads like a structured tool map instead of a long undifferentiated list.

## Home Page Changes

Home now acts as the project cockpit. It includes:

- Compact header with app name and project root.
- Today's Work cards for schedule/task status and morning plan.
- Project Health cards for root, workbook, Git, validation, registry, and activity.
- Data Progress cards for audits, photos, interviews, issues, documentation gaps, KPI rows, and pilot candidates.
- Primary workflow cards:
  - Capture Data
  - Validate & Clean
  - Analyze
  - Standardize
  - Report & Handoff
  - Admin Tools
- Recommended Next Actions based on available project state.
- Compact Recent Activity panel.

Existing Home actions remain accessible, but they are now grouped by workflow and visual priority.

## Page Layout Changes

- Schedule now emphasizes task descriptions over task IDs and has clearer missing-schedule guidance.
- Photos now explains exactly how to use the Incoming Photos folder when it is empty.
- Workbook Health now has status cards before the result panel.
- Issue Analysis uses tabs for dense summary tables.
- FMEA-Lite has a clearer analysis workflow strip and labels planned write-back behavior honestly.
- PM Checklists groups generation controls into target/scope/output areas.
- Reports labels folder selection, recent files, and preview states more clearly.
- Final Handoff uses internal scrolling for many controls and keeps previews secondary.
- Settings is grouped into configuration, external tools, preferences, and safety checks.
- Tool Registry remains an admin page, now with search/filtering.

## Functionality Preservation

No business logic was removed. Existing command-line tools, dashboard actions, workbook paths, report folders, activity logging, backups, workflows, and project data remain intact. Planned/disabled behavior remains labeled as planned rather than made to look broken.

The dashboard still exposes the major actions from Phase 0 through Phase 6, including setup/validation, audit entry, photo intake, interviews, progress, analysis reports, PM/BOM reports, weekly/mentor/morning reports, final handoff tools, workflows, system audit, settings, and backups.

## Testing

Commands run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python run_dashboard.py
python -m pytest tests\test_ui_smoke.py -q
python -m pytest
```

Results:

- Dashboard offscreen startup: passed.
- All navigation pages instantiated successfully at 1280x760.
- UI smoke tests: 4 passed.
- Full test suite: 69 passed.

## Known Limitations

- This was a controlled UI refactor, not a complete design-system rebuild.
- Some tool-specific pages could still receive deeper polish later, especially complex forms and dense report tables.
- The app still uses native PySide widgets rather than custom graphics-heavy components, which is intentional for reliability on a work computer and network path.
- Report previews are reduced and clarified, but not all are fully collapsible yet.
- Charts and rich visual previews remain tool-dependent and data-dependent.
