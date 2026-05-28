# Maintenance And Release Readiness

This project is local-first. Source code, tests, generic docs, sanitized templates, and synthetic demo data belong in the repository. Real project outputs belong in the private EOAT project root and should not be committed.

## Adding Pages

Add new dashboard pages through `app/page_registry.py`.

1. Create a page module under `app/pages/`.
2. Add a `PageSpec` with the page key, label, section, and factory path.
3. Use page lifecycle hooks when the page should refresh after project-root, audit, validation, report, or open-item events.
4. Keep long-running work in background tasks through `app.page_tasks.run_tool_background`.
5. Add a focused UI smoke test when the page has important actions.

## Adding Tools

Tool functions should return `core.result.ToolResult`. Include:

- `tool_id` and `tool_name`
- summary
- warnings/errors
- created or modified files
- metrics
- structured data when the UI needs tables

Do not write generated real outputs into the repository. Use the selected project root or a temp/test fixture.

## Adding Validation Rules

Use structured `ValidationFinding` records for workbook/project validation.

- Use severity levels deliberately.
- Do not guess engineering values.
- Safe repair actions must preview, require confirmation, create backups, log activity, and rerun validation.
- Robot_Info.xlsx remains limited to the small robot-side pneumatic circuit-count workbook.

## Adding Settings

Settings should be visible and reversible. User-specific paths and preferences must stay in ignored local config such as `config/local_config.json`. Commit only generic examples like `config/config.example.json`.

## Adding Report Generators

Report generators should:

- Write to the private project root.
- Avoid overwriting existing reports.
- State unavailable KPI, pilot, or evidence data honestly.
- Avoid copying real workbooks, reports, photos, logs, cache files, local configs, internal paths, customer names, mold numbers, part numbers, capacity data, downtime data, scrap data, or private operational details into repo docs.

## Backup Retention

`core.backup_manager` discovers workbook backups in project backup folders and workbook `_backups` folders.

Default retention policy:

- Keep all backups from the last 7 days.
- Keep the newest 25 backups per source workbook.
- Keep milestone backups when identifiable from the filename/path.
- Refuse cleanup when current workbook validation has blocker/error findings.
- Require cleanup preview and explicit confirmation before deleting anything.

Use the Backup Manager page to review counts, total size, source-workbook grouping, and cleanup candidates before cleanup.

## Release Readiness

Use the Release Readiness page before committing or pushing. It shows:

- test status or last-known status
- repo safety audit status
- app smoke-test availability
- staged workbook/photo/local-config/generated-output checks
- README/USAGE presence
- demo project presence
- git status and branch status

Recommended terminal checks:

```powershell
python -m pytest
python scripts/repo_safety_audit.py --staged
git status --short
git diff --cached --name-only
```

Run the full safety audit before publishing:

```powershell
python scripts/repo_safety_audit.py --root .
```

The full working-tree audit may flag ignored local/generated files. Fix those before release, or confirm the staged-file audit is clean before making a local commit.

## Optional Pre-Commit Hook

Install the local-only hook:

```powershell
python scripts/install_pre_commit_hook.py
```

The hook runs:

```powershell
python scripts/repo_safety_audit.py --staged
```

It is optional and not required for app use. It should fail closed when staged files contain obvious blockers.

## Safe Commit Checklist

- Run tests or document known failures.
- Run staged safety scan.
- Confirm no real workbooks, photos, reports, logs, caches, backups, local configs, internal paths, or operational identifiers are staged.
- Confirm generated real outputs remain in the private project root.
- Review `README.md`, `docs/USAGE.md`, and `docs/repo_sanitization_report.md`.
- Review branch and staged file list before pushing.
