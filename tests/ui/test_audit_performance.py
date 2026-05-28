from __future__ import annotations

from app.pages.audit import AuditPage
from app.task_runner import TaskResult
from core.press_lookup import PressLookupResult


def test_audit_visibility_collects_current_form_once(qapp, fake_config, monkeypatch):
    page = AuditPage(fake_config)
    calls = {"count": 0}
    original = page._current_audit_form_values

    def counted():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(page, "_current_audit_form_values", counted)

    page._update_audit_field_visibility()

    assert calls["count"] == 1


def test_stale_machine_lookup_result_is_ignored(qapp, fake_config):
    page = AuditPage(fake_config)
    page._machine_lookup_generation = 1
    page.audit_fields["Press/Machine #"].setText("13")
    page.audit_fields["Robot Type"].setEditText("")
    result = PressLookupResult(
        machine_number=12,
        raw_machine_input="12",
        master_fields={"Robot/Picker Brand": "Wittmann", "Robot/Picker Model #": "W833"},
        master_rows_count=1,
    )
    task_result = TaskResult(
        id="audit_machine_lookup_1",
        name="Machine Lookup",
        ok=True,
        message="done",
        result_data={"generation": 1, "machine_text": "12", "action": "lookup", "result": result},
    )

    page._apply_machine_lookup_task_result(task_result)

    assert page.audit_fields["Press/Machine #"].text() == "13"
    assert page.audit_fields["Robot Type"].currentText() == ""
