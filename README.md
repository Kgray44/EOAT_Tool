# EOAT Command Center

EOAT Command Center is a local-first toolkit for EOAT standardization, audit tracking, maintenance checklist generation, workbook validation, KPI summaries, and project handoff reporting. It was originally developed for a manufacturing automation internship project, but the repository is structured to contain only the app engine, generic documentation, sanitized templates, and synthetic demo data.

## What It Does

- Runs a PySide desktop dashboard for EOAT project workflows.
- Creates and validates an EOAT project folder structure.
- Maintains an EOAT master tracker workbook.
- Supports audit entry, photo indexing, interview notes, issue analysis, FMEA-lite analysis, KPI summaries, pilot-candidate scoring, PM checklist generation, and final handoff packaging.
- Loads real project data from a user-selected project root outside the repository.
- Ships with `examples/demo_project/` so the app can run without any private operational data.

## Install

```powershell
python -m pip install -r requirements.txt
```

## Run The App

```powershell
python run_dashboard.py
```

On a clean checkout, the default project root is `examples/demo_project/`. Use the Home or Settings page to select a different local project root. Saved project-root settings are written to ignored local config files such as `config/local_config.json`.

## Demo Data

The folder `examples/demo_project/` contains fake machines, fake press IDs, fake robot names, fake EOAT types, fake issue categories, fake KPI values, fake placeholder images, fake audit entries, and fake reference workbooks. It is safe for tests, screenshots, and GitHub examples.

## Audit Truth Rules

Audit field visibility is rule-driven. Fields hidden because they do not apply to the selected EOAT type, sensor state, wiring state, or quick-disconnect state save as `N/A` instead of keeping stale hidden values. Physical audit rows and compatibility-derived rows are counted separately in progress metrics, and Workbook Health reports applicable `N/A` warnings, stale hidden values, Hybrid completeness warnings, and semantic consistency warnings.

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
python scripts/repo_safety_audit.py
```

The audit reports `BLOCKER`, `WARNING`, and `INFO` findings. Blockers must be fixed before publishing.

Optional local pre-commit check:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/pre_commit_check.ps1
```

## Tests

```powershell
python -m pytest
```

## GitHub Publishing Checklist

- Run `python -m pytest`.
- Run `python scripts/repo_safety_audit.py`.
- Confirm `EOAT_Standardization_Project/` and any real project root are ignored or outside the repo.
- Confirm local config files are not staged.
- Confirm no real workbooks, reports, logs, photos, backups, snapshots, exports, capacity files, audit entries, customer names, mold numbers, part numbers, or internal paths are staged.
- Review `docs/repo_sanitization_report.md`.
- Review the final `git status` and staged file list before committing.

