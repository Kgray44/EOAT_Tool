# EOAT Command Center Usability Test Report

## Summary

This phase added a fake-project usability harness for the EOAT Command Center. The tests drive the PySide6 UI across every major page and major workflow using synthetic EOAT workbook data, fake schedules, fake photos, fake reports, fake config, and stubbed external open actions.

Overall result: Pass.

## Test Environment

- OS assumption: Windows local desktop / network-share workspace.
- Python observed: Python 3.14 runtime from the local user environment.
- UI framework: PySide6.
- App entry point inspected: `app/main.py`.
- Main window inspected: `app/dashboard_ui.py`, `DashboardWindow`.
- Navigation inspected: `app/navigation.py`, `NAV_SECTIONS` and `NAV_ITEMS`.
- Background runner inspected: `app/task_runner.py`.
- Theme inspected: `app/theme.py` and Settings theme flow.
- Config inspected: `core/config.py`.
- Project paths inspected: `core/paths.py`.
- Workbook schema inspected: `data_templates/workbook_schema.json`.
- Existing tests inspected: root `tests/` suite, including prior smoke/unit tests.

Commands run:

```powershell
python -m pytest tests/ui -q
python -m pytest tests/integration/test_fake_project_full_workflow.py -q
python -m pytest tests/ui tests/integration/test_fake_project_full_workflow.py -q
python -m pytest -q
```

Final full regression result:

```text
118 passed in 225.73s (0:03:45)
```

## Fake Project Fixture

The reusable fixture lives under `tests/fixtures/`:

- `fake_project.py`
- `fake_workbook.py`
- `fake_images.py`
- `fake_config.py`

The populated usability project is created under a temp directory named `Fake_EOAT_Standardization_Project`. It includes the app's actual expected folder layout:

- `00_Project_Admin`
- `01_EOAT_Audit`
- `02_KPI_Data`
- `03_Standards`
- `04_FMEA`
- `05_Pilot_Project`
- `06_Final_Handoff`
- incoming/cell photo folders, reports, backups, validation, and handoff folders

The fake workbook includes all expected sheets and headers plus realistic synthetic data:

- Press 101 Wittmann vacuum EOAT with vacuum loss, part drops, tubing wear, pilot-candidate data, and complete documentation.
- Press 102 Engel Viper gripper EOAT with sensor failure and missing documentation.
- Press 103 hybrid EOAT with mostly complete documentation.
- Issue Log rows for Vacuum loss, Sensor failure, and Tubing wear.
- KPI rows with downtime, drops, mis-picks, scrap, cycle time, and maintenance events.
- FMEA rows including high RPN and missing risk-data cases.
- Pilot Candidate, Interview Notes, Action Items, and Photo Index rows.

The fixture also creates:

- Week 1 and Week 2 schedule/progress JSON.
- A start date of `2026-05-18`, making `2026-05-19` resolve to Week 1 Day 2.
- Fake valid PNG/JPG files in `Incoming_Photos`.
- Seed daily, weekly, validation, and issue report files.
- Fake config pointing only to the temp project.

Legacy unit tests still use the original empty `fake_project` fixture. The richer project is scoped to the usability and integration tests so existing unit-test assumptions remain intact.

## Automated Test Coverage

Pages tested:

- Home
- Schedule
- EOAT Audit
- Photos
- Workbook Health
- Audit Progress
- Issues
- FMEA-Lite
- Pilot Candidates
- KPI Dashboard
- Standards Docs
- PM Checklists
- BOM / Spare Parts
- Reports
- Tool Registry
- Final Handoff
- Settings

Workflows tested:

- Startup with fake config.
- Full sidebar navigation.
- Light/dark theme switching and persistence stubbing.
- Morning Plan generation for Week 1 Day 2.
- Daily Start Workflow.
- Schedule task status changes.
- Audit entry save, optional missing fields, and invalid required fields.
- Photo intake preview, copy/index, and empty-folder state.
- Workbook validation.
- Audit progress report.
- Issue analysis.
- FMEA-lite analysis and disabled planned action.
- Pilot candidate ranking and no-candidate state.
- KPI dashboard/report.
- Documentation gap scan.
- PM checklist generation.
- BOM/spare-parts analysis.
- Reports preview/open stub/weekly summary.
- Tool registry filtering.
- Final deliverable check, presentation assets, final summary, dry-run and real fake-project handoff package.
- Settings system audit and backups.
- End-to-end fake Day 2 workflow.

Error states tested:

- Missing master workbook.
- Missing schedule files.
- Missing project start date.
- Corrupted task progress JSON.
- Workbook missing required sheet.
- Empty incoming photo folder.
- Invalid audit entry.
- Invalid PM checklist target.
- Synthetic tool exception.

Background/responsiveness tested:

- Task guard rejects conflicting project-writing/workbook-writing tasks.
- UI button recovers after tool execution.
- Tests use a deterministic synchronous task manager to avoid PySide worker-thread instability in automated offscreen runs. The production background task manager remains unchanged.

## Test Results

New usability suite:

```text
python -m pytest tests/ui -q
32 passed
```

End-to-end fake Day 2 workflow:

```text
python -m pytest tests/integration/test_fake_project_full_workflow.py -q
1 passed
```

Combined usability/integration:

```text
python -m pytest tests/ui tests/integration/test_fake_project_full_workflow.py -q
33 passed
```

Full regression:

```text
python -m pytest -q
118 passed in 225.73s (0:03:45)
```

## Usability Findings

Severity: Low

Area: Photo Intake

What happened: When Confirm Intake was clicked with no selected photos, the page refreshed the incoming-photo empty state after the failed tool result, hiding the more direct "No photos selected" error.

Expected behavior: Keep the failure message visible after a failed intake action.

Suggested fix: Refresh the incoming list only after successful intake.

Status: Fixed in `app/pages/photos.py`.

## Regression Risk

- The fake project fixture is intentionally broad and catches more cross-tool behavior than the older unit tests.
- The deterministic UI task manager means automated tests do not fully judge visual busy-state timing; manual QA should still watch perceived responsiveness.
- Dialog behavior is stubbed or auto-accepted where needed, so manual QA should still confirm dialogs are clear and safe.
- External file/folder opening is stubbed in tests and should be smoke-checked manually in a safe fake project.

## Known Limitations

- No pixel-perfect screenshot comparison is included.
- No real Excel launch is tested.
- No real network-share dependency is tested, by design.
- No cloud APIs or internet access are used.
- UI tests run offscreen, so final visual polish still needs the manual QA pass.
- The full app is tested with synthetic data, not production internship files.

## Next Recommended Fixes

1. Add optional screenshot-based manual evidence for light/dark mode and narrow window sizes.
2. Add a small visual regression smoke test if the app later adopts `pytest-qt` or a stable screenshot runner.
3. Expand fake fixture variations for read-only files if Windows file-lock simulation becomes reliable enough.
4. Consider adding object names to primary buttons and tables to make UI tests less dependent on visible text.
5. Keep the fake-project fixture updated whenever the workbook schema or navigation adds a new major feature.
