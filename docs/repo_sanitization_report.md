# Repository Sanitization Report

Date: 2026-05-20

## Scope Reviewed

The repository root was reviewed as an EOAT app/toolkit plus local project data. The app engine is primarily in `app/`, `core/`, `tools/`, `scripts/`, `tests/`, `data_templates/`, `templates/`, `examples/demo_project/`, `README.md`, and `USAGE.md`.

## Safe To Commit

- Source code in `app/`, `core/`, `tools/`, and safe utility scripts.
- Test code and fake fixtures in `tests/`.
- Generic documentation in `README.md`, `USAGE.md`, and `docs/` after review.
- Sanitized schema/config data in `data_templates/`.
- Sanitized CSV templates in `templates/`.
- Synthetic demo project data in `examples/demo_project/`.
- `config/config.example.json`.
- `.gitignore`, `pytest.ini`, and `requirements.txt`.

## Must Be Excluded

- `EOAT_Standardization_Project/`: contains real project workbooks, reference data, generated reports, backups, activity logs, snapshots, and final handoff outputs.
- `Project_Help_Documents/`: contains local project planning/source documents that should be reviewed before any publication.
- Local config files such as `config/local_config.json`, `config/user_config.json`, and `config/config.json`.
- Generated logs such as `*.log`.
- Workbook backups, zip backups, snapshots, generated reports, exports, audit photos, and operational data folders.
- Any real project root selected at runtime.

## Risky Findings

- A real local config previously existed under `config/user_config.json` and contained an internal project-root path and local executable path. It was removed from the commit candidate set and replaced by `config/config.example.json`.
- `EOAT_Standardization_Project/` appears to contain real operational/project data, including audit workbook content, generated reports, reference workbooks, backups, activity logs, validation reports, KPI/report outputs, pilot-candidate outputs, final handoff material, and snapshots.
- The nested `EOAT_Standardization_Project/.git/` directory indicates a separate local repository may exist around the real data. Do not push or publish that nested project without a separate NDA review.
- Some historical docs in `docs/` reference generated project paths. These are not operational excerpts, but the docs should still receive human review before publication.

## Files Or Areas That Appear To Contain Internal Operational Data

- `EOAT_Standardization_Project/00_Project_Admin/reference_data/`
- `EOAT_Standardization_Project/01_EOAT_Audit/EOAT_Audit_Database/`
- `EOAT_Standardization_Project/01_EOAT_Audit/Audit_Progress_Reports/`
- `EOAT_Standardization_Project/01_EOAT_Audit/Issue_Analysis_Reports/`
- `EOAT_Standardization_Project/02_KPI_Data/`
- `EOAT_Standardization_Project/03_Standards/*Reports/`
- `EOAT_Standardization_Project/04_FMEA/FMEA_Reports/`
- `EOAT_Standardization_Project/05_Pilot_Project/Candidate_Cells/`
- `EOAT_Standardization_Project/06_Final_Handoff/`
- `EOAT_Standardization_Project/00_Project_Admin/Backups/`
- `EOAT_Standardization_Project/00_Project_Admin/Activity_Logs/`
- `EOAT_Standardization_Project/00_Project_Admin/Daily_Status_Reports/`
- `EOAT_Standardization_Project/00_Project_Admin/Weekly_Status_Reports/`

No sensitive excerpts are included in this report.

## What Was Changed

- Added a root `.gitignore` that excludes real project data, local configs, generated outputs, workbooks by default, logs, backups, exports, snapshots, cache folders, virtual environments, and OS/editor junk.
- Changed default app project root to `examples/demo_project/`.
- Changed default config path to ignored `config/local_config.json`.
- Removed committed local-user executable defaults.
- Removed the sensitive local `config/user_config.json`.
- Added `config/config.example.json`.
- Added `examples/demo_project/` with synthetic data only.
- Added sanitized CSV templates under `templates/`.
- Replaced private reference workbook filenames in source defaults with generic names.
- Updated README and usage docs with the NDA boundary and clean publishing checklist.
- Added `scripts/repo_safety_audit.py`.
- Added `scripts/pre_commit_check.ps1`.
- Added tests for demo loading, config defaults, and repository safety audit behavior.

## Human Review Still Needed

- Review all `docs/` files for tone, context, and any accidental operational detail before publishing.
- Confirm whether old backup docs/files should be deleted rather than merely ignored.
- Confirm whether `Project_Help_Documents/` should remain local-only or be replaced by sanitized public planning docs.
- If a Git repository already tracked `config/user_config.json` or `EOAT_Standardization_Project/`, remove those paths from the index before any GitHub push.
- If the nested project repository under `EOAT_Standardization_Project/.git/` is no longer needed, archive or remove it outside this publication workflow.

## Current Safety Status

`python scripts/repo_safety_audit.py` completed with no findings after the sanitization changes.

