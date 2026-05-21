# EOAT Command Center Usage

## Run With Demo Data

```powershell
python run_dashboard.py
```

The default project root is `examples/demo_project/` when no ignored local config exists. This demo root contains synthetic workbooks, reports, schedules, reference data, and placeholder photos.

CLI tools can also run directly against the demo root:

```powershell
python tools/validate_project_foundation.py --project-root "examples/demo_project"
python tools/audit_progress_report.py --project-root "examples/demo_project"
python tools/issue_category_report.py --project-root "examples/demo_project"
python tools/build_kpi_dashboard.py --project-root "examples/demo_project"
```

## Run With A Real Local Project Folder

Keep real project data outside this repository. In the app, open Home or Settings, choose **Select Project Root**, and pick the private local project folder. The saved root is stored in an ignored local config file.

PowerShell example:

```powershell
Copy-Item config/config.example.json config/local_config.json
notepad config/local_config.json
```

Edit `project_root` to point to your private local project folder. Do not commit the local config file.

## Switch Project Roots

- Use Home > Select Project Root for quick switching.
- Use Settings > Project root > Browse to update and save the root.
- Switch back to demo data by selecting `examples/demo_project/`.

## Validate Workbook Health

```powershell
python tools/validate_project_foundation.py --project-root "examples/demo_project"
```

In the app, use Workbook Health or Home > Validate Project Foundation. Workbook Health distinguishes physical audit rows from compatibility entries, ignores `N/A` in fields that truly do not apply, and warns when applicable major fields are `N/A`, hidden fields contain stale values, or Hybrid EOATs are missing vacuum-side or gripper-side details.

On the EOAT Audit page, hidden non-applicable fields save as `N/A`. Hybrid EOATs keep both vacuum and gripper fields visible and use warnings instead of blocking save.

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

## Run The Repo Safety Audit

```powershell
python scripts/repo_safety_audit.py
```

Fix every `BLOCKER` before committing. Review every `WARNING`. Public company references are allowed, but private operational data and internal paths are not.

## Prepare A Clean Commit

```powershell
python -m pytest
python scripts/repo_safety_audit.py
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

