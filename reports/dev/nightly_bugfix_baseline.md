# Nightly Bugfix Baseline

- Baseline captured: 2026-05-29 16:35 EDT
- Starting branch: `codex/audit-page-latency-fix`
- Working branch: `fix/nightly-bugfix-stabilization`
- Starting commit preserved on backup branch: `a7ed1cb532c76669f857236cabed4bc77fdd6c02`
- Backup branch: `backup/nightly-bugfix-start-20260529-1632`

## Environment

- Python: 3.14.5
- pip: 26.1.1
- pytest: 9.0.3
- Ruff: 0.8.6
- Initial pytest-timeout availability: not installed

## Baseline Results

- `python -m ruff format --check .`: failed; 271 files would be reformatted.
- `python -m ruff check .`: passed.
- `python -m pytest --collect-only -q`: 727 tests collected in 85.11s.
- `python -m pytest -q --durations=50`: timed out after 10 minutes without completing.

## Initial Isolation Findings

- `tests/core`: 120 passed in 97.76s.
- `tests/app`: 5 passed in 17.55s.
- `tests/integration`: 1 passed in 101.32s.
- Root-test isolation found failures in:
  - `tests/test_annotations_backend.py::test_info_tag_is_neutral_searchable_and_not_an_open_issue`
  - `tests/test_audit_workflow_stabilization.py::test_audit_page_compatibility_preview_can_cancel_risky_save`
  - `tests/test_cli_help.py`, which was not a single hung subprocess but a slow serial loop over many `--help` subprocesses.

## Slow Baseline Candidates

- CLI help scripts each took roughly 7 to 16 seconds when executed serially on the network-share workspace.
- Broad final-handoff, theme-switching, app-startup, open-items, and scheduled-summary tests were the slowest legitimate workflows.
