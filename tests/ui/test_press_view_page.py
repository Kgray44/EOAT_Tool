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
