from __future__ import annotations

from app.widgets.open_items_panel import OpenItemsPanel
from core.open_items import save_cached_open_items_summary


def test_open_items_panel_constructor_does_not_generate_summary(qapp, fake_config, monkeypatch):
    import core.open_items as open_items_core

    def fail(*_args, **_kwargs):
        raise AssertionError("constructor must not generate open items")

    monkeypatch.setattr(open_items_core, "open_items_summary", fail)

    panel = OpenItemsPanel(fake_config)

    assert "Loading" in panel.buttons["total_open_items"].text()


def test_open_items_panel_constructor_displays_cached_summary(qapp, fake_config, monkeypatch):
    import core.open_items as open_items_core

    save_cached_open_items_summary(fake_config.project_root, {"total_open_items": 7, "critical_open_items": 2})

    def fail(*_args, **_kwargs):
        raise AssertionError("constructor must use cache only")

    monkeypatch.setattr(open_items_core, "open_items_summary", fail)

    panel = OpenItemsPanel(fake_config)

    assert panel.buttons["total_open_items"].text() == "Total Open: 7"
    assert panel.buttons["critical_open_items"].text() == "Critical: 2"


def test_open_items_panel_async_refresh_saves_cache(qapp, fake_config, monkeypatch):
    import core.open_items as open_items_core

    monkeypatch.setattr(open_items_core, "open_items_summary", lambda _root: {"total_open_items": 4})
    panel = OpenItemsPanel(fake_config)

    assert panel.refresh_async() is True

    assert panel.buttons["total_open_items"].text() == "Total Open: 4"
    cached, _generated_at = open_items_core.load_cached_open_items_summary(fake_config.project_root)
    assert cached["total_open_items"] == 4
