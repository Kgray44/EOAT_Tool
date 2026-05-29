from __future__ import annotations

import pytest

from app.pages.press_view import PressViewPage
from core.press_view import PressAuditEntry, PressViewGroup, build_press_view_groups, save_press_view_cache
from tests.ui.helpers import table_text

pytestmark = pytest.mark.usability


def test_press_view_page_loads_machine_groups(qapp, usability_fake_config):
    save_press_view_cache(usability_fake_config.project_root, build_press_view_groups(usability_fake_config.project_root))
    page = PressViewPage(usability_fake_config)
    page.show()

    assert page.cards["Press Groups"].value_label.text() == "3"
    assert "Press/Machine 101" in table_text(page.group_table)
    assert "AUD-20260518-001" in table_text(page.physical_table)


def test_press_view_page_displays_multiple_physical_audits_for_one_machine(qapp, usability_fake_config):
    page = PressViewPage(usability_fake_config)
    group = PressViewGroup(
        machine="101",
        display_name="Press/Machine 101",
        physical_audits=[
            PressAuditEntry(audit_id="AUD-101-A", machine="101", entry_type="Audited", tool="TOOL-A"),
            PressAuditEntry(audit_id="AUD-101-B", machine="101", entry_type="Audited", tool="TOOL-B"),
        ],
    )

    page._apply_refresh_result({"groups": [group], "source_counts": {"physical": 2}}, 0.0)
    page.group_table.selectRow(0)

    assert page.physical_table.rowCount() == 2
    assert "AUD-101-A" in table_text(page.physical_table)
    assert "AUD-101-B" in table_text(page.physical_table)


def test_press_view_normal_render_does_not_auto_resize_columns(qapp, usability_fake_config, monkeypatch):
    page = PressViewPage(usability_fake_config)
    group = PressViewGroup(machine="101", display_name="Press/Machine 101")
    save_press_view_cache(usability_fake_config.project_root, [group])

    def fail_resize():
        raise AssertionError("normal render should not auto-size columns")

    for table in [page.group_table, page.physical_table, page.compatible_table, page.linked_compatible_table]:
        monkeypatch.setattr(table, "resizeColumnsToContents", fail_resize)

    page._show_cached_groups()
    page._apply_refresh_result({"groups": [group], "source_counts": {"groups": 1}}, 0.0)
