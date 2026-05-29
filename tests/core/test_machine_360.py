from __future__ import annotations

from openpyxl import load_workbook

from core.audit_constants import COMPATIBILITY_SOURCE_FIELD, ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD, SOURCE_AUDIT_ID_FIELD
from core.machine_360 import build_machine_360_context
from core.paths import resolve_project_paths
from core.workbook_schema import get_expected_headers


def _append_inventory_row(workbook_path, values):
    workbook = load_workbook(workbook_path)
    try:
        ws = workbook["EOAT Inventory"]
        headers = get_expected_headers("EOAT Inventory")
        ws.append([values.get(header, "") for header in headers])
        workbook.save(workbook_path)
    finally:
        workbook.close()


def test_machine_360_context_builds_from_demo_data(usability_fake_project):
    context = build_machine_360_context(usability_fake_project, "101")

    assert context.machine_number == "101"
    assert context.metrics["physical_audit_count"] == 1
    assert context.machine_identity["robot_type"]
    assert context.tooling_summary["tools"] == ["TOOL-A"]
    assert context.risk_fmea["highest_rpn"] == 224
    assert context.kpi_signals["downtime_minutes"] == 42
    assert context.pm_status["items"]
    assert any(source["name"] == "EOAT Inventory" and source["status"] == "loaded" for source in context.data_sources)


def test_machine_360_separates_physical_and_compatibility_rows(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    _append_inventory_row(
        paths.master_workbook,
        {
            "Audit ID": "AUD-COMPAT-101",
            "Audit Date": "2026-05-19",
            "Press/Machine #": "Press 101",
            "Tool #": "TOOL-A",
            "EOAT Type": "Vacuum",
            "Status": "Compatible",
            ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
            SOURCE_AUDIT_ID_FIELD: "AUD-20260518-001",
            COMPATIBILITY_SOURCE_FIELD: "Synthetic compatibility test",
        },
    )

    context = build_machine_360_context(usability_fake_project, "101")

    assert context.metrics["physical_audit_count"] == 1
    assert context.metrics["compatible_entry_count"] == 1
    assert {row["Audit ID"] for row in context.physical_audits} == {"AUD-20260518-001"}
    assert {row["Audit ID"] for row in context.compatible_entries} == {"AUD-COMPAT-101"}
    assert context.compatibility_summary["physical_audits_counted_separately"] is True


def test_machine_360_missing_optional_sources_do_not_crash(minimal_fake_project):
    context = build_machine_360_context(minimal_fake_project, "999")

    assert context.machine_number == "999"
    assert context.metrics["physical_audit_count"] == 0
    assert context.warnings
    assert context.actions
    assert any(source["status"] in {"missing", "missing_optional"} for source in context.data_sources)


def test_machine_360_action_payloads_target_correct_pages(usability_fake_project):
    context = build_machine_360_context(usability_fake_project, "101")
    actions = {action.action_id: action for action in context.actions}

    assert actions["open_audit"].target_page == "audit"
    assert actions["open_audit"].payload["audit_id"] == "AUD-20260518-001"
    assert actions["open_press_view"].target_page == "press_view"
    assert actions["add_note"].target_page == "notes"
    assert actions["add_tag"].target_page == "tags"
    assert actions["create_follow_up"].target_page == "open_items"
    assert actions["run_machine_validation"].target_page == "workbook_health"
    assert actions["run_machine_validation"].requires_expensive_validation is True
    assert actions["generate_pm_checklist"].target_page == "pm_checklists"
    assert actions["generate_work_instruction_draft"].available is False


def test_machine_360_uses_cached_open_items_without_validation(monkeypatch, usability_fake_project):
    called = {"snapshot": 0}

    def fake_cached_open_items(project_root):
        called["snapshot"] += 1
        return [], None, "No cached snapshot in test."

    monkeypatch.setattr("core.project_data_service.load_cached_open_items", fake_cached_open_items)

    context = build_machine_360_context(usability_fake_project, "101")

    assert called["snapshot"] == 1
    assert context.metrics["open_item_count"] >= 1
    assert any(source["name"] == "Open items snapshot" for source in context.data_sources)
