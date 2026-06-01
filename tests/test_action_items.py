from __future__ import annotations

from core.action_items import add_action_item, generate_action_id


def test_add_action_item(fake_project):
    action_id = generate_action_id(fake_project, "2026-05-18")
    result = add_action_item(fake_project, "Check vacuum tubing", related_cell_press="Press 12")

    assert action_id.startswith("ACT-20260518-")
    assert result.success is True
    assert result.metrics["action_id"].startswith("ACT-")
