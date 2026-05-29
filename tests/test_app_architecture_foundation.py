from __future__ import annotations

from PySide6.QtWidgets import QWidget

from app.dashboard_ui import DashboardWindow
from app.event_bus import EVENT_SETTINGS_CHANGED, EventBus, get_event_bus
from app.navigation import NAV_ITEMS, NAV_SECTIONS
from app.page_registry import PAGE_SPECS, create_page, get_page_spec, load_page_factory, page_specs_by_section


def test_page_registry_defines_existing_navigation():
    keys = [spec.key for spec in PAGE_SPECS]

    assert len(keys) == len(set(keys))
    assert keys == [item.page_key for item in NAV_ITEMS]
    assert [section.label for section in NAV_SECTIONS] == ["Overview", "Capture", "Analysis", "Standards", "Output", "System"]
    assert [section for section, _specs in page_specs_by_section()] == [section.label for section in NAV_SECTIONS]
    assert get_page_spec("home").factory_path == "app.pages.home:HomePage"
    assert not get_page_spec("tool_registry").requires_config


def test_page_registry_loads_factories_and_creates_configless_page(qapp):
    for spec in PAGE_SPECS:
        assert callable(load_page_factory(spec))

    page = create_page(get_page_spec("tool_registry"))
    assert page is not None


def test_event_bus_dispatches_specific_and_global_handlers():
    bus = EventBus()
    seen: list[tuple[str, str]] = []
    unsubscribe_specific = bus.subscribe("ExampleEvent", lambda event: seen.append(("specific", event.event_type)))
    bus.subscribe("*", lambda event: seen.append(("global", event.event_type)))

    event = bus.emit("ExampleEvent", {"answer": 42}, source="test")

    assert event.payload["answer"] == 42
    assert event.source == "test"
    assert seen == [("specific", "ExampleEvent"), ("global", "ExampleEvent")]
    assert bus.subscriber_count("ExampleEvent") == 1
    assert set(bus.subscribed_event_types()) == {"*", "ExampleEvent"}

    unsubscribe_specific()
    bus.emit("ExampleEvent")
    assert seen[-1] == ("global", "ExampleEvent")
    assert bus.subscriber_count() == 1


def test_dashboard_lifecycle_helpers_tolerate_absent_and_present_hooks():
    class NoHooks:
        pass

    class Hooked:
        def __init__(self):
            self.calls: list[str] = []

        def on_show(self):
            self.calls.append("show")
            return "shown"

        def can_close(self):
            return False, "Not yet"

    hooked = Hooked()

    assert DashboardWindow._call_optional_page_hook(NoHooks(), "on_show") is None
    assert DashboardWindow._call_optional_page_hook(hooked, "on_show") == "shown"
    assert hooked.calls == ["show"]
    assert DashboardWindow._page_can_close(NoHooks()) == (True, "")
    assert DashboardWindow._page_can_close(hooked) == (False, "Not yet")


def test_dashboard_calls_show_and_hide_hooks_when_switching_pages(qapp, fake_config):
    calls: list[str] = []

    class HookPage(QWidget):
        def __init__(self, name: str):
            super().__init__()
            self.name = name

        def on_show(self):
            calls.append(f"{self.name}:show")

        def on_hide(self):
            calls.append(f"{self.name}:hide")

    get_event_bus().clear()
    window = DashboardWindow(fake_config)
    window.page_factories["schedule"] = lambda: HookPage("schedule")
    window.page_factories["audit"] = lambda: HookPage("audit")

    assert window._show_page("schedule")
    assert window._show_page("audit")

    assert calls == ["schedule:show", "schedule:hide", "audit:show"]
    window.close()
    get_event_bus().clear()


def test_dashboard_dispatches_events_to_listening_loaded_pages(qapp, fake_config):
    get_event_bus().clear()
    window = DashboardWindow(fake_config)
    home = window.pages["home"]
    calls: list[str] = []
    home.refresh_status = lambda: calls.append("home-refresh")

    get_event_bus().emit(EVENT_SETTINGS_CHANGED, {"theme": "light"}, source="settings")

    assert calls == ["home-refresh"]
    window.close()
    get_event_bus().clear()
