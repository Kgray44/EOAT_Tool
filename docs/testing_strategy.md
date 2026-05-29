# Testing Strategy

The EOAT Command Center test strategy is built around local-first safety: synthetic project data is used for automated tests, real project roots stay outside the repository, and any file-writing workflow must be explicit.

## Test Layers

1. Unit tests validate core services such as audit schema, completion, validation, reporting, search, PM due logic, photo evidence, risk, FMEA, pilot scoring, and import/QR helpers.
2. UI smoke tests verify that the dashboard shell and primary pages can be created without touching real project data.
3. Workflow tests use sanitized fake projects to exercise save, report, validation, annotation, search, and navigation behavior.
4. CI smoke checks verify page registry integrity, command/feature registry consistency, tool registry completeness, default demo project mode, and an offscreen dashboard launch.
5. Repository safety audits scan committed files for private paths, local configs, generated outputs, operational workbooks, photos, logs, caches, and backups.

## Local Commands

Run the full automated suite:

```powershell
python -m pytest
```

Run release safety checks:

```powershell
python scripts/repo_safety_audit.py --root .
python scripts/ci_smoke_check.py --root . --dashboard-smoke
```

Run Ruff if it is installed:

```powershell
python -m ruff check .
```

## CI Expectations

The GitHub Actions workflow installs `requirements.txt`, runs the optional Ruff gate when Ruff is available, performs registry/demo/dashboard smoke checks, runs `pytest`, and then runs the repository safety audit. The safety audit is intentionally repeated after tests so generated artifacts cannot quietly become part of the repository state.

## Data Safety Rules

- Automated tests must use fake projects or the sanitized demo project only.
- Real workbooks, photos, generated reports, logs, caches, backups, local configs, and private operational exports must not be committed.
- Workbook-writing code must use existing backup/migration safety paths.
- A failing risky test area should be fixed or isolated before unrelated release work is shipped.
