from __future__ import annotations

from app.pages.machine_360 import Machine360Page
from app.task_runner import TaskResult
from core.machine_360 import Machine360Action, Machine360Context
from tests.ui.helpers import table_text


def _context(machine: str = "101") -> Machine360Context:
    return Machine360Context(
        machine_number=machine,
        display_name=f"Machine {machine}",
        physical_audits=[
            {"Audit ID": f"AUD-{machine}", "Entry Type": "Audited", "Tool #": "TOOL-1", "EOAT Type": "Vacuum"}
        ],
        compatible_entries=[
            {"Audit ID": f"AUD-{machine}-COMP", "Entry Type": "Compatible", "Tool #": "TOOL-1", "EOAT Type": "Vacuum"}
        ],
        open_items=[{"title": "Review tubing"}],
        metrics={"physical_audit_count": 1, "compatible_entry_count": 1, "open_item_count": 1},
        recommended_actions=["Review open item."],
        machine_identity={"plant_area": "Plant 4", "robot_type": "Wittmann"},
        actions=[
            Machine360Action(
                "open_press_view",
                "Open Press View",
                "press_view",
                "machine",
                {"machine": machine},
                available=True,
            ),
            Machine360Action(
                "run_machine_validation",
                "Run Machine Validation",
                "machine_360",
                "machine",
                {"machine": machine},
                available=True,
                requires_expensive_validation=True,
                help_text="Runs validation only after this explicit button click.",
            ),
        ],
        last_refreshed="2026-05-29T10:00:00",
        data_sources=[{"name": "EOAT Inventory", "status": "loaded"}],
    )


class CapturingTaskManager:
    def __init__(self):
        self.requests = []
        self.callbacks = []

    def run_task(self, request, on_finished=None, button=None):
        self.requests.append(request)
        self.callbacks.append(on_finished)
        return True


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


def test_machine_360_refresh_shows_searching_immediately_without_sync_build(qapp, usability_fake_config, monkeypatch):
    manager = CapturingTaskManager()
    monkeypatch.setattr("app.pages.machine_360.get_task_manager", lambda: manager)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Machine 360 context must be built in the background task.")

    monkeypatch.setattr("app.pages.machine_360.build_machine_360_context", fail_if_called)
    page = Machine360Page(usability_fake_config)
    page.machine_edit.setText("101")

    page.refresh()

    assert page.search_status_label.text() == "Searching Machine 101..."
    assert page.search_progress.isHidden() is False
    assert page.refresh_button.isEnabled() is False
    assert len(manager.requests) == 1


def test_machine_360_completion_populates_widgets(qapp, usability_fake_config, monkeypatch):
    manager = CapturingTaskManager()
    monkeypatch.setattr("app.pages.machine_360.get_task_manager", lambda: manager)
    page = Machine360Page(usability_fake_config)
    page.machine_edit.setText("101")
    page.refresh()

    manager.callbacks[-1](
        TaskResult(
            id="machine_360_search_1",
            name="Machine 360 Search",
            ok=True,
            message="done",
            result_data={"generation": page._search_generation, "machine": "101", "context": _context("101")},
        )
    )

    assert page.search_status_label.text() == "Loaded Machine 101"
    assert page.summary_table.rowCount() > 0
    assert page.audit_table.rowCount() == 2
    assert "Recommended Actions" in page.detail_text.toPlainText()


def test_machine_360_page_displays_multiple_physical_audits_for_one_machine(qapp, usability_fake_config):
    page = Machine360Page(usability_fake_config)
    context = _context("101")
    context.physical_audits.append(
        {"Audit ID": "AUD-101-B", "Entry Type": "Audited", "Tool #": "TOOL-B", "EOAT Type": "Mechanical / Gripper"}
    )
    context.metrics["physical_audit_count"] = 2

    page._populate_context(context)

    assert page.audit_table.rowCount() == 3
    text = table_text(page.audit_table)
    assert "AUD-101" in text
    assert "AUD-101-B" in text


def test_machine_360_stale_search_result_is_ignored(qapp, usability_fake_config, monkeypatch):
    manager = CapturingTaskManager()
    monkeypatch.setattr("app.pages.machine_360.get_task_manager", lambda: manager)
    page = Machine360Page(usability_fake_config)
    page.machine_edit.setText("101")
    page.refresh()
    first_callback = manager.callbacks[-1]
    first_generation = page._search_generation
    page.machine_edit.setText("102")
    page.refresh()

    first_callback(
        TaskResult(
            id="machine_360_search_1",
            name="Machine 360 Search",
            ok=True,
            message="done",
            result_data={"generation": first_generation, "machine": "101", "context": _context("101")},
        )
    )

    assert page.context is None
    assert page.search_status_label.text() == "Searching Machine 102..."


def test_machine_360_failed_search_shows_safe_error_and_clears_busy_state(qapp, usability_fake_config, monkeypatch):
    manager = CapturingTaskManager()
    monkeypatch.setattr("app.pages.machine_360.get_task_manager", lambda: manager)
    page = Machine360Page(usability_fake_config)
    page.machine_edit.setText("101")
    page.refresh()

    manager.callbacks[-1](
        TaskResult(
            id="machine_360_search_1",
            name="Machine 360 Search",
            ok=False,
            message="failed",
            error="RuntimeError: workbook unavailable\nprivate path omitted",
        )
    )

    assert page.search_progress.isHidden() is True
    assert page.refresh_button.isEnabled() is True
    assert page.search_status_label.text().startswith("Search failed: RuntimeError: workbook unavailable")
    assert "private path omitted" in page.detail_text.toPlainText()


def test_machine_360_select_machine_starts_async_search(qapp, usability_fake_config, monkeypatch):
    manager = CapturingTaskManager()
    monkeypatch.setattr("app.pages.machine_360.get_task_manager", lambda: manager)
    page = Machine360Page(usability_fake_config)

    assert page.select_machine("101") is True
    assert page.machine_edit.text() == "101"
    assert page.search_status_label.text() == "Searching Machine 101..."
    assert len(manager.requests) == 1
