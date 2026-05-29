# Architecture Notes

The app is a local-first PySide desktop dashboard backed by workbook and project-folder services. The current architecture favors small services with explicit file boundaries over hidden global state.

## Main Surfaces

- `app/page_registry.py` owns page keys, labels, factories, refresh behavior, and event subscriptions.
- `app/feature_registry.py` derives feature metadata from pages and tool registry data.
- `app/command_registry.py` builds dashboard commands with safety metadata, context hints, recent command support, and confirmation requirements for file-writing actions.
- `app/search_routes.py` centralizes dashboard navigation from search results.
- `app/event_bus.py` publishes app events and isolates handler failures so one broken subscriber does not stop others.
- `core/project_data_service.py` and related core modules provide shared workbook/project context.
- `scripts/repo_safety_audit.py` is the release gate for private data and generated-output boundaries.

## File-Writing Policy

The repository should contain source, tests, templates, docs, and sanitized demo artifacts. Runtime outputs belong under the selected project root and should stay out of Git. Any code that writes to a workbook should use existing safe-file, backup, migration, or explicit confirmation helpers.

## Registry Pattern

Page, feature, command, and tool registries are intentionally checked in CI. When adding a page:

1. Add a `PageSpec`.
2. Let `FeatureRegistry` derive feature/search/command metadata where possible.
3. Add command actions only when they are safe, explicit, and have a disabled reason when unavailable.
4. Add event listeners to the page spec instead of manually wiring page refreshes across the dashboard.
5. Add tests for registry validity and navigation/search routes.

## Event Pattern

Event handlers should be lightweight. Heavy work should be deferred to page refresh methods or background task helpers. The event bus records and logs handler exceptions, but handlers should still catch known recoverable issues and show user-facing status where appropriate.

## Release Checks

The release path is:

```powershell
python -m pytest
python scripts/ci_smoke_check.py --root . --dashboard-smoke
python scripts/repo_safety_audit.py --root .
```

Optional linting uses the Ruff config in `pyproject.toml` when Ruff is installed.
