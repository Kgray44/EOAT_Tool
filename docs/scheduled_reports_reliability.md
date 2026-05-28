# Scheduled Reports Reliability

Phase 7 keeps the existing daily and weekly report scripts intact while adding safer inspection and catch-up workflows in the app.

## Calendar Preview

`core.scheduled_reports.preview_summary_schedule(project_root, start_date=None, days=14, timezone_name="America/New_York")` returns one row per date with:

- date and weekday
- expected automation type (`daily_summary`, `weekly_summary`, or blank)
- scheduled time
- status: `not scheduled`, `already exists`, `due`, `future`, `missed`, or `skipped`
- existing report path when a matching report already exists
- decision reason
- resolved project week/day where applicable

The Scheduled Reports page can show 14 or 30 days. Monday-Thursday rows are daily summaries, Friday rows are weekly summaries, and weekends are marked not scheduled.

## Catch-Up Summaries

Catch-up generation uses `run_catch_up_summaries(...)`, which delegates to the same daily and weekly generation functions used by manual runs. That preserves duplicate detection and report naming:

- existing reports are not overwritten
- daily catch-up resolves the correct target date, week, and day
- weekly catch-up resolves the correct target Friday/week
- catch-up runs are logged in `scheduled_tools.log` and the activity log
- skipped dates are reported instead of silently ignored

## Preflight Diagnostics

`run_scheduler_preflight(project_root)` checks:

- Windows platform
- PowerShell availability
- Task Scheduler command availability
- daily and weekly scheduled task status
- scheduled report scripts
- Python executable
- project root
- output folder writability
- scheduled log readability

Checks are reported as `PASS`, `WARNING`, or `ERROR`. Warnings are used for missing local scheduler tooling so the page remains useful on non-Windows development/test machines.

## Report Context

`core.report_context` gathers local project signals for smarter summaries:

- activity log entries
- schedule/task progress
- open items summary
- validation finding JSON when available
- recent daily/weekly reports
- changed/generated files already recorded by tool results

The context builder does not invent engineering values and does not require the dashboard to be open. Daily reports receive CLI-safe context items through existing command-line flags. Weekly reports include open-item and validation sections when real data exists.

## Safety Notes

- Scheduled scripts are preserved.
- Manual daily/weekly commands remain available.
- Existing reports are not overwritten by scheduled, dry-run, or catch-up paths.
- Generated reports, logs, cache files, and local configs remain local project outputs and should not be committed.
- `Robot_Info.xlsx` remains limited to the small robot-side pneumatic circuit-count behavior.
