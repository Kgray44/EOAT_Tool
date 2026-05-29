# Overnight Baseline Report

## Duplicate Verification

- Confirmed working directory is the copied Git worktree named `EOAT_Command_Center_Overnight_Copy`.
- Confirmed the original project worktree is separate and was not used for this verification pass.
- Exact internal shared-drive UNC paths are intentionally omitted from this repository document so committed docs do not contain private internal paths.

## Git State

- Original worktree name: `KG_Nolato_Summer_2026`
- Copied worktree name: `EOAT_Command_Center_Overnight_Copy`
- Current copied branch: `feature/full-overnight-expansion`
- Current copied commit at start of Phase 0 verification: `594f81e`
- Working tree status before creating this report: clean

## Commands Run

### Full Pytest

- Command: `python -m pytest`
- Result: timed out after 30 minutes.
- Notes: No passing/failing test summary was emitted before the timeout. This matches the earlier baseline behavior in this network worktree environment, so focused verification remains the practical checkpoint strategy.

### Repository Safety Audit

- Command: `python scripts\repo_safety_audit.py --root .`
- Result: passed.
- Output summary: no blocking or warning findings.

### Dashboard Smoke Test

- Command: `python -m pytest -q tests\test_ui_smoke.py`
- Result: passed.
- Output summary: 6 passed in 39.07 seconds.

## Phase 0 Conclusion

- The copied worktree is verified as the active workspace.
- The original project folder was not modified during this pass.
- Full pytest remains too slow or blocked for this environment within a 30 minute window.
- Repo safety audit and dashboard smoke verification both passed.
