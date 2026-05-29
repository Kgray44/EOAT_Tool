# Audit Page, Machine 360, and Cylinder Default Performance Report

Date: 2026-05-29

## EOAT Audit Page

Original symptom: opening the EOAT Audit page could take about 40 seconds on real project data, and local demo measurements still showed too much synchronous work before the shell appeared.

Measured baseline captured before the fix in this worktree:

- `AuditPage` constructor on `examples/demo_project`: `6.1944s`.
- Initial Audit ID generation and audit selector loading were workbook-backed and could happen before the page shell was usable.

Measured after the fix on `examples/demo_project`:

- Cold constructor samples after moving startup log writes off the shell path: `0.7858s`, `0.6099s`, `0.5625s`.
- Audit selector starts as `Loading audit list...`.
- Compatibility source selector starts as `Loading compatibility sources...`.
- Guided Audit starts as an unbuilt placeholder: `_guided_ui_built=False`.

Moved off the UI-thread startup path:

- Audit workbook index loading for the audit selector.
- Compatibility source index loading.
- Draft recovery check.
- Annotation SQLite initialization.
- Guided Audit tabs and tables.
- Startup performance/activity log file writes.
- Robot info/save-preview work unless the user explicitly asks for preview/save behavior.

Still synchronous during shell creation:

- The visible Audit Entry shell, Section Form widgets, output panel, and one lightweight audit coach refresh. These remain synchronous because the first screen needs real editable controls immediately.

Performance logs to inspect:

- `audit_page_shell_started`
- `audit_page_shell_ready`
- `audit_page_background_indexes_started`
- `audit_page_background_indexes_ready`
- `audit_page_draft_check_started`
- `audit_page_draft_check_ready`
- `audit_page_guided_ui_built`
- `audit_page_annotation_service_initialized`

The logs are written to the project performance logs under `00_Project_Admin/Activity_Logs` and `00_Project_Admin/Performance_Logs`. Each event includes duration and relevant details such as option counts, deferred work flags, success, and error text when applicable.

## Machine 360

Original symptom: typing or searching a machine number could freeze Machine 360 for about 15-20 seconds.

Root cause: `Machine360Page.refresh()` synchronously called `build_machine_360_context(...)`, which can read workbook data, Press View groups, open items, photo evidence, guided audit plans, and robot info.

Fix:

- Searches now start a page-refresh task through the shared task runner.
- The UI immediately shows `Searching Machine <number>...` and an indeterminate progress bar.
- The Refresh button changes to `Searching...` and is disabled while the current request is running.
- Typing is debounced at 400 ms.
- Worker code returns plain data containing the request generation, machine number, and `Machine360Context`.
- Qt widgets are updated only in the completion handler on the UI thread.
- If a newer search starts first, older results are ignored using a generation id.
- Failures show `Search failed: <safe error message>` and clear the busy state.

Measured behavior:

- With the background task captured instead of executed, `Machine360Page.refresh()` returned in `0.9236s` while immediately showing `Searching Machine 101...`.
- The long workbook-backed context build is no longer performed synchronously by `refresh()`.

Machine 360 performance logs:

- `machine_360_search_started`
- `machine_360_search_finished`
- `machine_360_search_failed`

Each Machine 360 event includes machine number, generation, duration, physical audit count, compatible entry count, open item count, and whether a stale result was ignored.

## Cylinder Type Behavior

New behavior:

- New audit forms leave `Cylinder Type` blank.
- `Cylinder Type` no longer uses `Linear` as an unconditional field default.
- `# of Cylinders` is the indicator that the optional cylinder section is in use.
- When `# of Cylinders` has a meaningful value and `Cylinder Type` is blank or `N/A`, the UI and save normalization default `Cylinder Type` to `Linear`.
- When `# of Cylinders` is cleared and `Cylinder Type` was auto-filled to `Linear`, the UI clears it back to blank.
- Manual choices such as `Rotary` are preserved when the count is cleared.
- Blank count plus blank type is ignored by completion and saved as unused optional cylinder data rather than saving a default `Linear`.

Unused cylinder detection:

- The cylinder section is considered in use only when `# of Cylinders` has a meaningful non-blank, non-`N/A`, non-unknown value.
- Completion ignores both cylinder fields when the section is unused.
- Save normalization defaults `Cylinder Type` only when the count is meaningful.

## Tests Added Or Updated

- Audit startup does not synchronously read workbook-backed audit indexes.
- Audit selector and compatibility selector show loading placeholders and populate from background results.
- Guided Audit UI is built on first Guided Audit selection.
- Annotation database initialization is deferred.
- Demo AuditPage shell creation is asserted under 2 seconds.
- Machine 360 refresh/search shows a busy indicator immediately.
- Machine 360 does not build context synchronously in refresh.
- Machine 360 completion populates widgets, stale results are ignored, failures show a safe error, and `select_machine()` starts async loading.
- Gripper presets are cached by project/file signature.
- Repo safety audit uses Python 3.10-compatible walking and scans docs/demo content more strictly.
- Cylinder Type starts blank, auto-fills only when cylinder count is used, clears auto-filled values when count is cleared, preserves manual `Rotary`, and saves unused cylinder sections without default `Linear`.

## Commands Run

Passing focused checks already run during implementation:

- `python -m py_compile app/pages/audit.py app/pages/machine_360.py core/annotations/service.py core/gripper_presets.py scripts/repo_safety_audit.py`
- `python -m pytest tests/ui/test_audit_performance.py -q` -> `10 passed`
- `python -m pytest tests/ui/test_machine_360_page.py -q` -> `7 passed`
- `python -m pytest tests/core/audit/test_completion.py tests/test_audit_coach.py tests/test_audit_entries.py::test_generate_audit_id_and_add_row tests/test_audit_entries.py::test_cylinder_fields_save_load_and_old_workbooks_migrate_safely tests/test_audit_field_registry.py tests/ui/test_audit_lookup.py::test_connection_type_and_eoat_type_dropdown_options tests/ui/test_audit_lookup.py::test_cylinder_details_group_is_always_visible tests/ui/test_audit_lookup.py::test_cylinder_type_defaults_only_when_cylinder_count_is_used tests/ui/test_audit_lookup.py::test_manual_cylinder_type_is_preserved_when_count_is_cleared tests/ui/test_audit_entry_workflow.py::test_save_complete_and_optional_missing_audit_entries tests/test_audit_workflow_stabilization.py::test_new_audit_defaults_and_generated_ids_are_clean -q` -> `39 passed`

Final verification commands run:

- `python -m pip install -r requirements.txt` -> passed, requirements already satisfied.
- `python -m pip install -r requirements-dev.txt` -> passed, `ruff==0.8.6` already satisfied.
- `python -m ruff check .` -> initially found three fixable lint issues; after removing unused imports and updating one quoted annotation, rerun passed with `All checks passed!`.
- `python scripts/ci_smoke_check.py --root . --dashboard-smoke` -> passed with `CI smoke checks passed.`
- `python -m pytest tests/ui/test_machine_360_page.py -q` -> `8 passed in 32.59s`.
- The requested audit-target command referenced files not present in this repo: `tests/ui/test_audit_page.py`, `tests/ui/test_audit_completion.py`, and `tests/core/test_audit_entries.py`. The equivalent repo files were run instead:
  `python -m pytest tests/ui/test_audit_performance.py tests/core/audit/test_completion.py tests/test_audit_completion.py tests/test_audit_entries.py -q` -> `62 passed in 179.40s`.
- `python -m pytest tests/app tests/core tests/integration -q --maxfail=1 --durations=25` -> `124 passed in 210.34s`; slowest test was `tests/integration/test_fake_project_full_workflow.py::test_fake_user_day2_workflow_end_to_end` at `71.18s`.
- `python -m pytest tests/ui/test_page_performance_lifecycle.py tests/ui/test_open_items_workflow.py tests/ui/test_press_view_page.py tests/test_press_view.py tests/test_scheduled_reports.py -q --maxfail=1 --durations=25` -> `31 passed in 116.25s`; slowest test was `tests/ui/test_open_items_workflow.py::test_open_items_page_opens_audit_field_target` at `11.32s`.
- `python scripts/repo_safety_audit.py --root .` -> passed with no blocking or warning findings.

Full-suite note:

- A prior monolithic `python -m pytest` run timed out after 90 minutes and left pytest child processes behind. Per follow-up instruction, stale pytest children were stopped and the full silent monolith was not repeated. Verification was completed with targeted and chunked commands using `--maxfail=1` and duration reporting where appropriate.
