# EOAT Command Center

EOAT Command Center is a local-first toolkit for EOAT standardization, audit tracking, maintenance checklist generation, workbook validation, KPI summaries, and project handoff reporting. It was originally developed for a manufacturing automation internship project, but the repository is structured to contain only the app engine, generic documentation, sanitized templates, and synthetic demo data.

## What It Does

- Runs a PySide desktop dashboard for EOAT project workflows.
- Creates and validates an EOAT project folder structure.
- Maintains an EOAT master tracker workbook.
- Tracks EOAT-side pneumatic circuit data in the master tracker and robot-side circuit data separately in `Robot_Info.xlsx`.
- Supports audit entry, photo indexing, interview notes, issue analysis, FMEA-lite analysis, KPI summaries, pilot-candidate scoring, PM checklist generation, and final handoff packaging.
- Gripper audits use `# of Grippers`, `Gripper Type`, and `Gripper Model`; the old broad `Gripper Size` column is treated as legacy-only when present in older workbooks.
- Loads real project data from a user-selected project root outside the repository.
- Ships with `examples/demo_project/` so the app can run without any private operational data.

## Install

```powershell
python -m pip install -r requirements.txt
```

For local development and CI-equivalent linting, also install the pinned dev tools:

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check .
```

## Run The App

```powershell
python run_dashboard.py
```

On a clean checkout, the default project root is `examples/demo_project/`. The app labels this as Demo mode and shows a warning that the data is synthetic. Use **Home > Choose Real Project Folder** or **Settings > Choose Real Project Folder** to select your private EOAT project root. Saved project-root settings are written to ignored local config files such as `config/local_config.json`.

## EOAT Atlas Companion App

EOAT Atlas is a separate read-only companion app for fast EOAT search, compatibility lookup, photo browsing, standards navigation, and install recommendations.

```powershell
python -m app.atlas.main
```

The equivalent convenience launcher is `python run_atlas.py`.

Use EOAT Command Center for audit/admin/editing/schema repair/photo intake/report generation. Use EOAT Atlas when you want to answer “What EOAT do I need?” quickly from the existing project data. Details are in `docs/EOAT_ATLAS.md`.

## Demo Data

The folder `examples/demo_project/` contains fake machines, fake press IDs, fake robot names, fake EOAT types, fake issue categories, fake KPI values, fake placeholder images, fake audit entries, and fake reference workbooks. It is safe for tests, screenshots, and GitHub examples.

The Home and Settings pages display the active project root, data mode, and master workbook path. If Demo mode is active, the app warns: "Demo project is active. This is synthetic sample data, not your real EOAT project."

## Audit Truth Rules

Audit field visibility is rule-driven. Fields hidden because they do not apply to the selected EOAT type, sensor state, wiring state, or quick-disconnect state save as `N/A` instead of keeping stale hidden values. Physical audit rows and compatibility-derived rows are counted separately in progress metrics, and Workbook Health reports applicable `N/A` warnings, stale hidden values, Hybrid completeness warnings, and semantic consistency warnings.

## Scheduled Summaries

The app can install Windows Task Scheduler jobs so summaries run even when the dashboard is closed:

- Daily summary: Monday-Thursday at 7:00 PM local machine time.
- Weekly summary: Friday at 7:00 PM local machine time.

Install or repair the tasks from **Scheduled Reports > Install/Repair Scheduled Tasks**, or run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_summary_schedules.ps1
```

Manual runs are also safe:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_daily_summary.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_weekly_summary.ps1
```

Weekly summaries are supervisor-facing Markdown reports. The generator summarizes daily reports, activity logs, workbook audit metrics, task progress, open follow-ups, and workbook validation output when available. It groups repeated follow-ups by severity and category, separates assigned action items from generated data-quality follow-ups, and avoids dumping raw activity logs into the final report. Run workbook validation before relying on a weekly summary for readiness or release claims; if validation JSON is missing, the report calls that out as a limitation.

Scheduled runs log to `00_Project_Admin/logs/scheduled_tools.log` inside the active project root. Existing same-day reports are detected and not overwritten.

## Performance And Refresh

The dashboard now opens with cached last-known data first, then lets you choose between:

- **Refresh**: quick cache/status refresh with cheap file checks.
- **Deep Refresh**: background recalculation of workbook health, audit progress, KPI, documentation, and other heavier dashboard metrics.

Dashboard cache lives at `00_Project_Admin/cache/dashboard_snapshot.json`. Performance timings are written to `00_Project_Admin/logs/performance.log`.

## Data Safety / NDA Boundary

This repository should contain source code, generic docs, sanitized templates, tests, and synthetic demo data only.

Real operational data must stay outside the repo. Do not commit real audit workbooks, real photos, real generated reports, capacity files, downtime data, scrap data, cycle-time data, mold numbers, part numbers, customer names, maintenance histories, employee-only notes, internal shared-drive paths, pilot rankings based on real plant issues, or anything that reveals plant operations, equipment relationships, production constraints, recurring failures, maintenance weaknesses, or process-specific details.

Public company context is allowed when it is already public and not combined with internal operational data.

## Local Config

Use `config/config.example.json` as the committed example. Keep real settings in ignored files:

- `config/local_config.json`
- `config/user_config.json`
- `config/config.json`

Example:

```json
{
  "project_root": "D:/local/private/eoat_project",
  "debug_mode": false,
  "theme": "light",
  "git_executable": "git",
  "project_start_date": "2026-05-18",
  "workdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
  "skip_weekends": true,
  "holidays": []
}
```

## Safety Audit

Run before committing:

```powershell
python scripts/repo_safety_audit.py --staged
```

The audit reports `BLOCKER`, `WARNING`, and `INFO` findings. Blockers must be fixed before publishing.

Optional local pre-commit check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pre_commit_check.ps1
```

Optional local hook installer:

```powershell
python scripts/install_pre_commit_hook.py
```

Use the app's **Release Readiness** page for staged-file checks, git status, safety-audit status, README/USAGE checks, and the safe commit checklist. Use **Backup Manager** to preview old workbook backup cleanup before deleting anything.

## Tests

```powershell
python -m pytest
```

## GitHub Publishing Checklist

- Run `python -m pytest`.
- Run `python scripts/repo_safety_audit.py --staged`.
- Run the full audit `python scripts/repo_safety_audit.py --root .` before publishing.
- Confirm `EOAT_Standardization_Project/` and any real project root are ignored or outside the repo.
- Confirm local config files are not staged.
- Confirm no real workbooks, reports, logs, photos, backups, snapshots, exports, capacity files, audit entries, customer names, mold numbers, part numbers, or internal paths are staged.
- Review `docs/repo_sanitization_report.md`.
- Review the final `git status` and staged file list before committing.

