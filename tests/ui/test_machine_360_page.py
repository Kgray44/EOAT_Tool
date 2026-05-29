from __future__ import annotations

from app.pages.machine_360 import Machine360Page


def test_machine_360_page_loads_context(qapp, usability_fake_config):
    page = Machine360Page(usability_fake_config)
    page.show()

    assert page.select_machine("101") is True
    assert page.summary_table.rowCount() > 0
    assert page.audit_table.rowCount() > 0
    assert "Recommended Actions" in page.detail_text.toPlainText()
    assert "Machine Identity" in page.detail_text.toPlainText()


def test_machine_360_page_exposes_action_payloads(qapp, usability_fake_config):
    page = Machine360Page(usability_fake_config)
    page.show()

    assert page.select_machine("101") is True
    payload = page.action_payload("open_press_view")

    assert payload["target_page"] == "press_view"
    assert payload["payload"]["machine"] == "101"
    assert page.action_buttons["run_machine_validation"].toolTip()
