from __future__ import annotations

from openpyxl import load_workbook

from core.audit.relationships import (
    compatibility_entries_for_machine,
    compatibility_entries_for_source_audit,
    is_compatibility_row,
    is_physical_audit_row,
    physical_audits_for_machine,
    relationship_summary_for_machine,
    source_audit_for_compatibility_row,
)
from core.audit_constants import (
    COMPATIBILITY_SOURCE_FIELD,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from core.paths import resolve_project_paths
from core.press_view import build_press_view_groups
from core.workbook_cache import row_dicts_cached
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


def _inventory_rows(project_root):
    return row_dicts_cached(resolve_project_paths(project_root).master_workbook, "EOAT Inventory")


def test_relationships_classify_physical_and_compatibility_rows(usability_fake_project):
    rows = _inventory_rows(usability_fake_project)
    physical = next(row for row in rows if row["Audit ID"] == "AUD-20260518-001")
    compatible = {
        **physical,
        "Audit ID": "AUD-COMPAT-CLASSIFY",
        "Press/Machine #": "Press 104",
        ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
        SOURCE_AUDIT_ID_FIELD: "AUD-20260518-001",
    }

    assert is_physical_audit_row(physical) is True
    assert is_compatibility_row(physical) is False
    assert is_compatibility_row(compatible) is True
    assert is_physical_audit_row(compatible) is False


def test_relationship_functions_filter_machine_rows(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    _append_inventory_row(
        paths.master_workbook,
        {
            "Audit ID": "AUD-COMPAT-101-PHASE9",
            "Audit Date": "2026-05-19",
            "Press/Machine #": "Press 101",
            "Tool #": "TOOL-A",
            "EOAT Type": "Vacuum",
            "Status": "Compatible",
            ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
            SOURCE_AUDIT_ID_FIELD: "AUD-20260518-001",
            COMPATIBILITY_SOURCE_FIELD: "Synthetic relationship test",
        },
    )
    rows = _inventory_rows(usability_fake_project)

    physical = physical_audits_for_machine(rows, "101")
    compatible = compatibility_entries_for_machine(rows, "101")
    linked = compatibility_entries_for_source_audit(rows, "AUD-20260518-001")

    assert [row["Audit ID"] for row in physical] == ["AUD-20260518-001"]
    assert [row["Audit ID"] for row in compatible] == ["AUD-COMPAT-101-PHASE9"]
    assert any(row["Audit ID"] == "AUD-COMPAT-101-PHASE9" for row in linked)


def test_relationship_summary_counts_match_press_view(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    _append_inventory_row(
        paths.master_workbook,
        {
            "Audit ID": "AUD-COMPAT-101-PRESS-VIEW",
            "Press/Machine #": "Press 101",
            "Tool #": "TOOL-A",
            "EOAT Type": "Vacuum",
            "Status": "Compatible",
            ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
            SOURCE_AUDIT_ID_FIELD: "AUD-20260518-001",
            COMPATIBILITY_SOURCE_FIELD: "Synthetic relationship test",
        },
    )
    rows = _inventory_rows(usability_fake_project)
    relationship_summary = relationship_summary_for_machine(rows, "101")
    press_group = next(group for group in build_press_view_groups(usability_fake_project) if group.machine == "101")

    assert relationship_summary.metrics["physical_audit_count"] == len(press_group.physical_audits)
    assert relationship_summary.metrics["compatibility_entry_count"] == len(press_group.compatible_entries)
    assert relationship_summary.metrics["linked_compatibility_count"] == len(press_group.linked_compatible_entries)
    assert relationship_summary.metrics["physical_verification_excludes_compatibility"] is True


def test_source_audit_links_resolve_and_missing_metadata_warns_safely(usability_fake_project):
    rows = _inventory_rows(usability_fake_project)
    source = next(row for row in rows if row["Audit ID"] == "AUD-20260518-001")
    linked_row = {
        **source,
        "Audit ID": "AUD-COMPAT-LINKED",
        "Press/Machine #": "Press 104",
        ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
        SOURCE_AUDIT_ID_FIELD: "AUD-20260518-001",
    }
    missing_source_row = {
        **source,
        "Audit ID": "AUD-COMPAT-MISSING-SOURCE",
        "Press/Machine #": "Press 105",
        ENTRY_TYPE_FIELD: ENTRY_TYPE_COMPATIBLE,
        SOURCE_AUDIT_ID_FIELD: "",
    }

    lookup = source_audit_for_compatibility_row([*rows, linked_row], linked_row)
    missing = source_audit_for_compatibility_row([*rows, missing_source_row], missing_source_row)

    assert lookup.source_audit is not None
    assert lookup.source_audit["Audit ID"] == "AUD-20260518-001"
    assert lookup.warnings == ()
    assert missing.source_audit is None
    assert "missing_source_metadata" in missing.warning_codes
    assert "missing Source Audit ID" in missing.warnings[0]
