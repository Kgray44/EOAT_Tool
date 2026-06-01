# Nightly Bugfix Stabilization Report

- Report updated: 2026-06-01
- Starting branch: `codex/audit-page-latency-fix`
- Backup branch: `backup/nightly-bugfix-start-20260529-1632`
- Working branch: `fix/nightly-bugfix-stabilization`
- Starting/backup commit: `a7ed1cb532c76669f857236cabed4bc77fdd6c02`
- Final stabilization commit: `c15a15f66e5dba71f7deda5ef7dce20e3056f10f`
- Main merge commit: `d8bc06b9`
- Main pushed: yes, to `origin/main`

## What Was Protected

- Fetched remote refs with Git maintenance disabled after network-share repack failed with `Permission denied`.
- Created and pushed `backup/nightly-bugfix-start-20260529-1632`.
- The starting dirty worktree was committed onto the backup branch and carried into the working branch; no dirty starting files were excluded.

## Baseline

- `python -m ruff format --check .`: failed; 271 files would be reformatted.
- `python -m ruff check .`: passed.
- `python -m pytest --collect-only -q`: 727 tests collected in 85.11s.
- Initial full pytest attempt timed out under a 10-minute cap.
- Root isolation found one annotation failure, one audit-save compatibility preview regression, and a very slow serial CLI help test.

## Timeout Root Cause

The full-suite hang was caused by leaked Qt UI state between tests. A delayed `AuditPage` draft-recovery `QTimer.singleShot` from an earlier test fired while `tests/test_task_runner.py` was running a local `QEventLoop`. That stale page opened `QMessageBox.exec()` for draft recovery, blocking the test loop until `pytest-timeout` interrupted it.

Evidence from the timeout stack:

- Test at timeout: `tests/test_task_runner.py::test_background_task_success_and_failure`
- Blocking call: `app/pages/audit.py::_offer_draft_recovery -> box.exec()`
- Trigger path: delayed draft-check timer -> deterministic test task manager -> draft-recovery dialog

## Fixes Made

- Added `pytest-timeout>=2.3` to dev dependencies and configured `timeout = 300`, `timeout_method = thread`.
- Added Qt widget cleanup after each test so top-level windows and their pending timers do not leak into later tests.
- Guarded audit draft recovery so hidden/stale `AuditPage` instances do not open recovery dialogs.
- Added regression coverage for hidden audit pages not opening draft recovery.
- Restored the linked-compatibility impact confirmation path for non-completed physical audit updates, including cancel behavior.
- Fixed open-item summary inflation where open-items validation could validate its own cache and generate duplicate orphan-reference items.
- Made CLI help testing concurrent while keeping the same per-script `--help`, return-code, and `usage:` assertions.
- Deferred heavy tool imports until after CLI argument parsing so normal `--help` paths do less work.
- Applied Ruff formatting across the repository and fixed the only lint issue introduced during lazy import work.

## Final Quality Gates

- `python -m ruff format --check .`: passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q --durations=25`: 728 passed in 1603.10s (26:43).
- `python -m pytest -vv --durations=25`: 728 passed in 1491.05s (24:51).
- `python scripts/ci_smoke_check.py`: passed.
- `python -m pytest tests/test_ui_smoke.py tests/ui/test_app_startup.py -q --durations=10`: passed.

## Slowest Remaining Tests

From the final verbose run:

- 79.62s `tests/ui/test_final_handoff_workflow.py::test_final_handoff_deliverable_assets_summary_dry_run_and_package`
- 76.96s `tests/integration/test_fake_project_full_workflow.py::test_fake_user_day2_workflow_end_to_end`
- 70.11s `tests/ui/test_theme_switching.py::test_theme_switching_persists_and_pages_survive_dark_and_light`
- 58.16s `tests/ui/test_app_startup.py::test_navigation_loads_every_sidebar_page_with_primary_controls`
- 40.97s `tests/test_summary_scheduler.py::test_daily_summary_fake_time_matrix`
- 35.30s `tests/test_final_handoff.py::test_final_handoff_package_does_not_overwrite_existing_package`
- 27.91s `tests/test_cli_help.py::test_implemented_tool_cli_help`
- 25.18s `tests/test_audit_entries.py::test_migrated_tooling_columns_match_neighbor_formatting_and_validation`

These are now bounded by the 300-second per-test timeout. They are still worth future optimization because they are broad integration-style tests doing real workbook/UI/package work.

## Skips And Xfails

- No tests were skipped or marked xfail.
- No assertions were weakened to hide failures.
- No tests were removed.

## Remaining Risks

- The project lives on a network share; Git maintenance and Python/argparse subprocess startup are visibly slower than local disk.
- Ruff formatting touched many files because the baseline format state was not clean. Behavioral edits were kept focused, but the diff is large because of formatting.
- Several broad UI/final-handoff workflows remain slow but are now completing and timeout-protected.

## Branches

- Preserved local and remote backup branch: `backup/nightly-bugfix-start-20260529-1632`.
- Preserved local active worktree branch: `fix/nightly-bugfix-stabilization` at `c15a15f6`; its remote branch was deleted after merge.
- Deleted local merged branches: `codex/audit-page-latency-fix`, `codex/eoat-audit-p0-state-performance`, `feature/full-overnight-expansion`, `fix/audit-save-fast-path-and-refresh-isolation`, `fix/pre-merge-safety-and-handoff`.
- Deleted remote merged branches: `origin/codex/audit-page-latency-fix`, `origin/codex/eoat-audit-p0-state-performance`, `origin/fix/nightly-bugfix-stabilization`, `origin/fix/pre-merge-safety-and-handoff`.
- Remaining remote branches after cleanup: `origin/main`, `origin/backup/nightly-bugfix-start-20260529-1632`.
- Branches needing human review: none found; no unmerged branches remained after main was pushed.

## Commands Run
- `git status --short --branch`
- `git branch -vv`
- `git remote -v`
- `git log --oneline --decorate -20`
- `git -c gc.auto=0 -c maintenance.auto=false fetch --all --prune`
- `git switch -c backup/nightly-bugfix-start-20260529-1632`
- `git add -A`
- `git commit -m "Backup starting worktree before nightly stabilization"`
- `git push -u origin backup/nightly-bugfix-start-20260529-1632`
- `git switch -c fix/nightly-bugfix-stabilization`
- `python --version`
- `python -m pip --version`
- `python -m pip list`
- `python -m pytest --version`
- `python -m ruff --version`
- `python -m ruff format --check .`
- `python -m ruff check .`
- `python -m pytest --collect-only -q`
- `python -m pytest -q --durations=50`
- Folder and file-level pytest isolation commands under `tests/core`, `tests/app`, `tests/integration`, root tests, and `tests/ui`.
- `python -m pip install "pytest-timeout>=2.3"`
- `python -m ruff format .`
- `python -m ruff check . --fix`
- `python -m pytest -q --durations=25`
- `python scripts/ci_smoke_check.py`
- `python -m pytest tests/test_ui_smoke.py tests/ui/test_app_startup.py -q --durations=10`
- `python -m pytest -vv --durations=25`
