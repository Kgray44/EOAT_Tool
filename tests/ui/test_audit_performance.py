from __future__ import annotations

import time
from pathlib import Path

from app.pages.audit import AuditPage
from app.task_runner import TaskResult
from core.config import UserConfig
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


def test_audit_page_shell_does_not_read_workbook_indexes_synchronously(qapp, fake_config, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Workbook-backed audit indexes must not load during AuditPage construction.")

    monkeypatch.setattr("app.pages.audit.list_audit_options", fail_if_called)
    monkeypatch.setattr("app.pages.audit.list_audited_source_options", fail_if_called)
    monkeypatch.setattr("app.pages.audit.generate_audit_id", fail_if_called)

    page = AuditPage(fake_config)

    assert page.audit_fields["Audit ID"].text().startswith("AUD-")
    assert page.load_audit_id_combo.itemText(0) == "Loading audit list..."


def test_audit_selector_loading_placeholder_populates_from_background_result(qapp, fake_config):
    page = AuditPage(fake_config)

    assert page.load_audit_id_combo.itemText(0) == "Loading audit list..."

    page._apply_audit_indexes_task_result(
        TaskResult(
            id="audit_indexes_0",
            name="Audit Workbook Indexes",
            ok=True,
            message="done",
            result_data={
                "audit_options": [
                    {"audit_id": "AUD-BG-001", "label": "AUD-BG-001 | Machine 1 | Audited", "row": {}},
                ],
                "source_options": [],
            },
        ),
        page._audit_index_generation,
        time.perf_counter(),
    )

    assert page.load_audit_id_combo.findData("AUD-BG-001") >= 0


def test_compatibility_source_loading_placeholder_populates_from_background_result(qapp, fake_config):
    page = AuditPage(fake_config)

    assert page.compatibility_source_combo.itemText(0) == "Loading compatibility sources..."

    page._apply_audit_indexes_task_result(
        TaskResult(
            id="audit_indexes_0",
            name="Audit Workbook Indexes",
            ok=True,
            message="done",
            result_data={
                "audit_options": [],
                "source_options": [
                    {"audit_id": "AUD-SOURCE-001", "label": "AUD-SOURCE-001 | Machine 2 | Audited", "row": {}},
                ],
            },
        ),
        page._audit_index_generation,
        time.perf_counter(),
    )

    assert page.compatibility_source_combo.findData("AUD-SOURCE-001") >= 0


def test_guided_audit_ui_is_built_on_first_guided_selection(qapp, fake_config):
    page = AuditPage(fake_config)

    assert page._guided_ui_built is False
    assert page._guided_step_tables == {}

    page.audit_entry_mode_combo.setCurrentText("Guided Audit")

    assert page._guided_ui_built is True
    assert page.guided_audit_tabs.count() == 8
    assert page.audit_mode_stack.currentIndex() == 0


def test_guided_audit_selection_does_not_force_save_preview_io(qapp, fake_config, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Robot info preview IO should run only from explicit save-preview refresh.")

    monkeypatch.setattr("app.pages.audit.load_robot_info_for_audit_entry", fail_if_called)
    page = AuditPage(fake_config)

    page.audit_entry_mode_combo.setCurrentText("Guided Audit")
    page.guided_audit_tabs.setCurrentIndex(page.guided_audit_tabs.count() - 1)

    assert page._guided_step_tables["final_review_save_impact"].rowCount() > 0


def test_audit_page_constructor_defers_annotation_database_initialization(qapp, fake_config, monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Annotation database initialization must not run in AuditPage.__init__.")

    monkeypatch.setattr("core.annotations.service.initialize_annotation_database", fail_if_called)

    page = AuditPage(fake_config)

    assert page.annotation_service.initialized is False


def test_audit_page_background_annotation_initialization_marks_service_ready(qapp, fake_config):
    page = AuditPage(fake_config)

    page._start_annotation_service_initialization()

    assert page._annotation_service_ready is True
    assert page.annotation_service.initialized is True


def test_audit_page_shell_creation_under_two_seconds_on_demo_project(qapp):
    root = Path("examples/demo_project").resolve()
    page_started = time.perf_counter()

    page = AuditPage(UserConfig(project_root=str(root), debug_mode=True))

    assert page.audit_fields["Audit ID"].text().startswith("AUD-")
    assert time.perf_counter() - page_started < 2.0
