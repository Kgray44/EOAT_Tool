# EOAT Command Center Usage

## Run With Demo Data

```powershell
python run_dashboard.py
```

The default project root is `examples/demo_project/` when no ignored local config exists. This demo root contains synthetic workbooks, reports, schedules, reference data, and placeholder photos. The app shows Demo mode on Home and Settings so synthetic data is not mistaken for real project files.

EOAT Atlas launches separately as a fast, mostly read-only search and install-support app:

```powershell
python -m app.atlas.main
```

Atlas uses the same active project root and source data as EOAT Command Center. See `docs/EOAT_ATLAS.md` for data source, refresh, warning, export, and performance details.

CLI tools can also run directly against the demo root:

```powershell
python tools/validate_project_foundation.py --project-root "examples/demo_project"
python tools/audit_progress_report.py --project-root "examples/demo_project"
python tools/issue_category_report.py --project-root "examples/demo_project"
python tools/build_kpi_dashboard.py --project-root "examples/demo_project"
```

## Run With A Real Local Project Folder

Keep real project data outside this repository. In the app, open Home or Settings, choose **Choose Real Project Folder**, and pick the private local project folder. The saved root is stored in ignored `config/local_config.json`.

The selected real project root should contain the numbered EOAT folders and this workbook:

```text
01_EOAT_Audit/EOAT_Audit_Database/EOAT_Master_Tracker.xlsx
```

If the selected root is missing folders or the workbook, Home and Settings show Missing or Invalid mode instead of silently switching back to demo data.

PowerShell example:

```powershell
Copy-Item config/config.example.json config/local_config.json
notepad config/local_config.json
```

Edit `project_root` to point to your private local project folder. Do not commit the local config file.

## Switch Project Roots

- Use Home > Choose Real Project Folder for quick switching.
- Use Settings > Choose Real Project Folder, then Save Settings, to update and persist the root.
- Switch back to demo data by selecting `examples/demo_project/`.

## Validate Workbook Health

```powershell
python tools/validate_project_foundation.py --project-root "examples/demo_project"
```

In the app, use Workbook Health or Home > Validate Project Foundation. Workbook Health distinguishes physical audit rows from compatibility entries, ignores `N/A` in fields that truly do not apply, and warns when applicable major fields are `N/A`, hidden fields contain stale values, or Hybrid EOATs are missing vacuum-side or gripper-side details.

On the EOAT Audit page, hidden non-applicable fields save as `N/A`. Hybrid EOATs keep both vacuum and gripper fields visible and use warnings instead of blocking save. `Gripper Size` is no longer part of the audit because it was too broad to be useful; use `# of Grippers`, `Gripper Type`, and `Gripper Model` for gripper capture. Old workbook columns named `Gripper Size` are ignored for compatibility.

The EOAT Audit workflow includes a `Pneumatic Circuits` tab. EOAT-side circuit counts are saved to the EOAT Master Tracker, while robot-side circuit counts are saved to `Robot_Info.xlsx` beside the master tracker and upserted by plant, machine, and robot identity. The legacy `Number of Vacuum Cups` column is migrated to `Number of Parts Picked` so the audit tracks parts picked per cycle rather than tooling components.

Photo intake uses `01_EOAT_Audit/Cell_Photos/Incoming_Photos` as the drop folder. Select an audit, assign a shot type, preview the rename, then confirm intake. Files are named as `<PlantArea>_<PressMachine>_EOAT_<date>_<ShotType>_<sequence>.<ext>`, written to Photo Index, and reflected in evidence coverage.

## Run Reports

Use the app workflow buttons or run individual tools:

```powershell
python tools/audit_progress_report.py --project-root "examples/demo_project"
python tools/documentation_gap_report.py --project-root "examples/demo_project"
python tools/fmea_lite_builder.py --project-root "examples/demo_project"
python tools/rank_pilot_candidates.py --project-root "examples/demo_project"
python tools/generate_pm_checklists.py --project-root "examples/demo_project" --generic
python tools/final_deliverable_check.py --project-root "examples/demo_project"
```

Reports generated from real project data must remain in the private project root and must not be committed.

## Scheduled Daily And Weekly Summaries

Open **Scheduled Reports** in the dashboard to view task status, run a catch-up summary, install/repair the Windows Scheduled Tasks, or open the scheduled tool log.

Schedule:

- Daily Summary runs Monday through Thursday at 7:00 PM.
- Weekly Summary runs every Friday at 7:00 PM.

Install or repair the tasks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_summary_schedules.ps1
```

Uninstall the tasks without deleting reports or logs:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall_summary_schedules.ps1
```

Run manually:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_daily_summary.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_weekly_summary.ps1
```

The weekly summary is intended for a quick supervisor review, not as a raw log export. It uses the current week daily reports, recent activity log entries, task progress JSON, workbook audit metrics, open follow-ups, and the latest workbook validation JSON when one exists. The report separates reports created by the weekly run from source reports it referenced and data files that activity logs show as updated.

Open follow-ups are grouped by severity and category, so repeated missing-evidence warnings appear as counts such as `Missing evidence: Cable Management: 5 open entries` instead of repeated raw rows. Assigned action items, engineering issues, data-quality follow-ups, critical data conflicts, photos indexed, pilot candidates, and audit completion percentage are reported as separate metrics to avoid contradictory "open item" counts.

Run workbook validation before using a weekly summary for readiness or release claims:

```powershell
python tools/validate_project_foundation.py --project-root "examples/demo_project"
```

If validation JSON is missing, the weekly summary will include an actionable warning instead of claiming readiness. Known limitations: audit metrics alone do not prove production impact, generated follow-ups remain open until the source data is fixed or explicitly overridden, and estimated or subjective source values remain estimates in the summary.

Check task status from a terminal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_summary_schedules.ps1
```

Scheduled tool logs are saved under the active project root at:

```text
00_Project_Admin/logs/scheduled_tools.log
```

If reports do not run, confirm the active project root is correct, run the check script above, inspect `scheduled_tools.log`, and verify Windows Task Scheduler is allowed to run PowerShell for your user account.

## Dashboard Refresh And Cache

The Home dashboard uses cached last-known values so the app shell can appear quickly.

- **Refresh** performs cheap status checks and loads cached dashboard data.
- **Deep Refresh** recalculates workbook-backed metrics and updates the cache in the background.

Cache and timing files are stored under the active project root:

```text
00_Project_Admin/cache/dashboard_snapshot.json
00_Project_Admin/logs/performance.log
```

If the project root is temporarily unavailable, the app can still show cached values and a clear warning instead of blocking startup.

## Run The Repo Safety Audit

```powershell
python scripts/repo_safety_audit.py --staged
```

Fix every `BLOCKER` before committing. Review every `WARNING`. Public company references are allowed, but private operational data and internal paths are not.

The full working-tree scan is useful before publishing:

```powershell
python scripts/repo_safety_audit.py --root .
```

The app also includes Release Readiness and Backup Manager pages. Release Readiness shows staged-file safety checks, git status, branch status, README/USAGE presence, demo project presence, and a copyable commit checklist. Backup Manager previews workbook backup cleanup candidates before any confirmed deletion.

## Prepare A Clean Commit

```powershell
python -m pytest
python scripts/repo_safety_audit.py --staged
git status --short
git diff --stat
git diff --cached --name-only
```

Do not stage:

- Real project roots or audit database folders.
- Real workbooks, reports, logs, snapshots, backups, exports, or photos.
- Real press lists, capacity files, downtime, scrap, cycle-time, or maintenance datasets.
- Mold numbers, part numbers, customer names, internal notes, or internal shared-drive paths.
- Local config files such as `config/local_config.json` or `config/user_config.json`.

Safe commit candidates are source code, tests, generic docs, sanitized templates, `config/config.example.json`, and `examples/demo_project/`.

