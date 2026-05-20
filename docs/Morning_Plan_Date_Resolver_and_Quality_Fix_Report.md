# Morning Plan Date Resolver and Quality Fix Report

## Summary

- Fixed Morning Plan Week/Day resolution so date-based generation uses the project calendar instead of stale UI defaults.
- Added project calendar config fields, with this project set to start on 2026-05-18.
- Improved Morning Plan content so it uses scheduled tasks, carryover, blockers, open actions, project phase, and available project-state metrics.
- Removed blank/generic plan output patterns and added a compact Plan Sources section.

## Root Cause

The Home page generated morning plans with `day=1` hard-coded and selected the first available schedule week. The planner itself only accepted explicit Week/Day values, so it had no way to resolve 2026-05-19 from the project calendar. A second quality bug came from task-progress parsing: the project progress file uses `task_text` and `task_id`, but the extractor did not read `task_text`, which caused blank scheduled task descriptions.

## Files Changed

- `core/schedule.py` - added `ProjectDay`, date parsing, project-start-date inference, and deterministic workday-based resolver.
- `core/config.py` - added project calendar fields: `project_start_date`, `workdays`, `skip_weekends`, and `holidays`.
- `config/local_config.json` - set this project's `project_start_date` to `2026-05-18`.
- `core/task_progress.py` - fixed task extraction for `task_text`.
- `core/morning_planner.py` - rebuilt the planner around resolved project day, real task selection, carryover, phase-aware actions, and source reporting.
- `app/pages/home.py` - displays resolved current project day and generates morning plans from the project calendar by default.
- `app/pages/schedule.py` - added manual Week/Day override checkbox, resolved-day preview, mismatch warning, and button label preview.
- `tests/test_schedule.py` - added resolver tests.
- `tests/test_morning_planner.py` - added filename, content, task-selection, and CLI regression tests.
- `tests/test_ui_smoke.py` - added Schedule page resolved-day UI smoke coverage.

## Date Resolver

The resolver counts configured project workdays from `project_start_date` through the target date, inclusive. With `project_start_date = 2026-05-18` and weekends skipped:

- 2026-05-18 resolves to Week 1 Day 1.
- 2026-05-19 resolves to Week 1 Day 2.
- 2026-05-22 resolves to Week 1 Day 5.
- 2026-05-25 resolves to Week 2 Day 1.

Manual override is explicit. When enabled, the selected Week/Day is used and the resolver source is `manual override`. Otherwise, the UI and generator use `project calendar`. If the start date is missing, the resolver attempts to infer it from Week 1 Day 1 reports and otherwise returns a warning fallback.

## Morning Plan Improvements

The plan now includes:

- Header with resolved source and project phase.
- Specific Primary Focus based on scheduled/carryover tasks.
- First 15 Minutes checklist.
- Practical main work blocks.
- Scheduled Tasks using unresolved tasks for the resolved Week/Day.
- Carryover / Blockers from previous unfinished or blocked work.
- Open Action Items when available.
- Recommended Next Actions based on audit, photo, issue, validation, and action-item state.
- Phase-aware Questions to Ask Today.
- End-of-Day Checklist.
- Plan Sources for debugging date, schedule, progress, prior report, and latest tool-run inputs.

Blank optional stretch bullets are no longer emitted. Completed/skipped tasks are not listed as main scheduled work.

## Dashboard/UI Changes

Home now shows `Resolved Project Day` and its Morning Plan button previews the resolved Week/Day. Schedule keeps the Week/Day selectors but separates them from automatic date resolution with `Use selected Week/Day override`. If selected controls differ from the automatically resolved project day, Schedule displays a warning telling the user to enable manual override to use selected values.

## Tests

Commands run:

- `python -m pytest tests\test_schedule.py tests\test_morning_planner.py tests\test_ui_smoke.py tests\test_workflows.py -q`
- `python -m compileall core app tools`

Results:

- Targeted tests: 17 passed.
- Compile check: passed.

Manual verification:

- Generated actual plan: `EOAT_Standardization_Project\00_Project_Admin\Daily_Status_Reports\Morning_Plans\Week1_Day2_Morning_Plan_2026-05-19.md`
- Verified the resolver returns Week 1 Day 2 for 2026-05-19 with start date 2026-05-18.

## Known Limitations

- Holiday support exists in the resolver, but no holidays are configured yet.
- Plan Sources reports the latest tool run available before the plan body is written; the current planner run is logged after generation.
- Weekend behavior currently uses the most recent configured workday and emits a warning.

