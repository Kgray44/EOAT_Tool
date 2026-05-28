# Page Registry And Event Bus

Date: 2026-05-27

Phase: 1 - App Architecture Foundation

This note explains the lightweight app architecture plumbing added for page registration, lazy loading, page lifecycle hooks, and app-wide events.

## Page Registry

Dashboard pages are registered in `app/page_registry.py`.

Each page uses a `PageSpec`:

```python
PageSpec(
    key="open_items",
    label="Open Items",
    section="Capture",
    factory_path="app.pages.open_items:OpenItemsPage",
    requires_config=True,
    refresh_on_show=True,
    listens_to=("AnnotationChanged", "AuditSaved"),
    description="Unified unresolved work board.",
)
```

Fields:

- `key`: stable page identifier used by navigation and command targets.
- `label`: sidebar label.
- `section`: sidebar group.
- `factory_path`: import path in `module:ClassName` form.
- `requires_config`: pass the shared app config into the page constructor.
- `refresh_on_show`: call the first available refresh method when the page is revisited.
- `listens_to`: app event names that should be routed to the loaded page.
- `description`: short developer-facing purpose.

`app/navigation.py` now derives `NAV_SECTIONS` and `NAV_ITEMS` from the registry. Existing imports of `NAV_ITEMS` and `NAV_SECTIONS` still work.

## Adding A Page

1. Create the page class under `app/pages/`.
2. Add a `PageSpec` to `PAGE_SPECS` in `app/page_registry.py`.
3. Choose an existing section or add a new section by using a new `section` name.
4. Add tests for registry presence and page load behavior.

Most pages should accept the shared `config` object:

```python
class OpenItemsPage(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
```

Pages without config can set `requires_config=False`.

## Lazy Loading

`DashboardWindow` still lazy-loads pages. At startup it creates sidebar entries and placeholder labels. A page class is imported and instantiated only when the page is first shown.

Missing or invalid page factory paths should fail clearly during page creation.

## Lifecycle Hooks

Pages may implement any of these optional methods:

```python
def on_show(self) -> None: ...
def on_hide(self) -> None: ...
def on_project_root_changed(self, config) -> None: ...
def on_event(self, event) -> None: ...
def can_close(self) -> tuple[bool, str]: ...
```

All hooks are optional. Pages that do not implement them continue to work.

Current dashboard behavior:

- `on_show()` is called after a page becomes current.
- `on_hide()` is called before leaving a loaded page.
- `on_project_root_changed(config)` is called for loaded pages when the project root changes.
- `on_event(event)` is called for loaded pages whose `PageSpec.listens_to` includes the event type.
- `can_close()` is checked before navigating away from the current page and before closing the app.

If `can_close()` returns `(False, "message")`, navigation or close is blocked and the message is shown.

For compatibility with existing pages, `refresh_on_show=True` calls the first available method from:

1. `refresh_status`
2. `refresh_metrics`
3. `refresh`
4. `refresh_data`

## Event Bus

The app-level event bus lives in `app/event_bus.py`.

Core objects:

- `AppEvent`
- `EventBus`
- `get_event_bus()`

Common event constants include:

- `AuditSaved`
- `AuditLoaded`
- `AnnotationChanged`
- `TagChanged`
- `TagColorSynced`
- `RobotInfoUpdated`
- `CompatibilityRegenerated`
- `WorkbookValidated`
- `ReportGenerated`
- `DashboardCacheInvalidated`
- `ProjectRootChanged`
- `SettingsChanged`
- `ScheduledReportRan`
- `OpenItemsChanged`

Emit an event:

```python
from app.event_bus import EVENT_AUDIT_SAVED, get_event_bus

get_event_bus().emit(
    EVENT_AUDIT_SAVED,
    {"audit_id": audit_id},
    source="audit",
)
```

Subscribe directly:

```python
from app.event_bus import EVENT_AUDIT_SAVED, get_event_bus

unsubscribe = get_event_bus().subscribe(EVENT_AUDIT_SAVED, handle_audit_saved)
```

The dashboard subscribes to all events and routes them to loaded pages based on `PageSpec.listens_to`.

## Current Event Wiring

Phase 1 wires only safe, obvious events:

- Home project-root selection emits `ProjectRootChanged`.
- Settings save/reload emits `SettingsChanged`; if the project root changed, the dashboard also emits `ProjectRootChanged`.
- Successful audit save emits `AuditSaved`.
- Workbook Health validation completion emits `WorkbookValidated`.

Future phases can add more event emits after the related workflow is stable and tested.

## Rules For Future Work

- Keep business logic in `core/`, not in the registry or dashboard shell.
- Keep page constructors lightweight because they run on first navigation.
- Use `listens_to` for page refresh routing instead of directly reaching across pages.
- Do not emit events with private data intended for committed files. Runtime payloads may contain local paths, but docs/tests should stay sanitized.
- Preserve existing CLI tools; the event bus is app plumbing, not a replacement for standalone commands.
