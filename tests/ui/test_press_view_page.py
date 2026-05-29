from __future__ import annotations

import pytest

from app.pages.press_view import PressViewPage
from tests.ui.helpers import table_text

pytestmark = pytest.mark.usability


def test_press_view_page_loads_machine_groups(qapp, usability_fake_config):
    page = PressViewPage(usability_fake_config)
    page.show()

    assert page.cards["Press Groups"].value_label.text() == "3"
    assert "Press/Machine 101" in table_text(page.group_table)
    assert "AUD-20260518-001" in table_text(page.physical_table)


def test_press_view_normal_render_does_not_auto_resize_columns(qapp, usability_fake_config, monkeypatch):
    page = PressViewPage(usability_fake_config)

    def fail_resize():
        raise AssertionError("normal render should not auto-size columns")

    for table in [page.group_table, page.physical_table, page.compatible_table, page.linked_compatible_table]:
        monkeypatch.setattr(table, "resizeColumnsToContents", fail_resize)

    page._show_cached_groups()
    page.refresh(force=True)
