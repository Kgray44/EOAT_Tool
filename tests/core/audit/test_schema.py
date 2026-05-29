from __future__ import annotations

from collections import defaultdict

from core.audit.schema import (
    STORAGE_NONE,
    all_audit_fields,
    audit_section_groups,
    dropdown_values_for,
    expected_workbook_headers,
    field_by_header,
    field_by_id,
    fields_for_section,
    fields_grouped_by_section,
)
from core.audit_constants import CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD
from core.audit_entries import LEGACY_VACUUM_CUPS_FIELD, NUMBER_OF_PARTS_PICKED_FIELD
from core.gripper_fields import (
    CUP_COUNT_FIELD,
    GRIPPER_COUNT_FIELD,
    GRIPPER_MODEL_FIELD,
    GRIPPER_SIZE_FIELD,
    GRIPPER_TYPE_FIELD,
)
from core.tool_fields import LEGACY_TOOL_FIELD, TOOL_FIELD
from core.workbook_schema import get_expected_headers


def test_registry_is_not_empty_and_core_fields_resolve():
    fields = all_audit_fields()

    assert fields
    assert field_by_id("press_machine").workbook_header == "Press/Machine #"
    assert field_by_header("Press/Machine #").field_id == "press_machine"
    assert field_by_header(TOOL_FIELD).field_id == "tool"


def test_every_field_has_identity_and_stored_fields_have_headers():
    for spec in all_audit_fields():
        assert spec.field_id
        assert spec.label
        if spec.storage_target != STORAGE_NONE:
            assert spec.workbook_header


def test_field_ids_are_unique_and_headers_are_unique_per_storage_target():
    fields = all_audit_fields()

    assert len({spec.field_id for spec in fields}) == len(fields)

    headers_by_target: dict[str, list[str]] = defaultdict(list)
    for spec in fields:
        if spec.storage_target == STORAGE_NONE:
            continue
        headers_by_target[spec.storage_target].append(spec.workbook_header)

    for headers in headers_by_target.values():
        assert len(headers) == len(set(headers))


def test_existing_eoat_inventory_workbook_headers_are_covered():
    expected = tuple(get_expected_headers("EOAT Inventory"))

    assert expected_workbook_headers() == expected
    assert {spec.workbook_header for spec in all_audit_fields() if spec.storage_target != STORAGE_NONE} >= set(expected)


def test_legacy_headers_resolve_to_current_specs():
    assert field_by_header(LEGACY_TOOL_FIELD).workbook_header == TOOL_FIELD
    assert field_by_header("EOAT Number").workbook_header == TOOL_FIELD
    assert field_by_header(LEGACY_VACUUM_CUPS_FIELD).workbook_header == NUMBER_OF_PARTS_PICKED_FIELD
    assert field_by_header("Vacuum Cup Count").workbook_header == CUP_COUNT_FIELD


def test_dropdown_values_exist_where_expected():
    assert "Complete" in dropdown_values_for("Status")
    assert "Vacuum" in dropdown_values_for("EOAT Type")
    assert "Linear" in dropdown_values_for(CYLINDER_TYPE_FIELD)
    assert "Yes" in dropdown_values_for("Fastener/Locking Hardware Present?")
    assert "No" in dropdown_values_for("Manual Completion Override")


def test_numeric_fields_are_marked():
    numeric_headers = {spec.workbook_header or spec.label for spec in all_audit_fields() if spec.numeric}

    assert NUMBER_OF_PARTS_PICKED_FIELD in numeric_headers
    assert CYLINDER_COUNT_FIELD in numeric_headers
    assert GRIPPER_COUNT_FIELD in numeric_headers
    assert CUP_COUNT_FIELD in numeric_headers
    assert "EOAT Vacuum Circuits" in numeric_headers


def test_required_and_important_fields_are_marked():
    by_header = {spec.workbook_header: spec for spec in all_audit_fields() if spec.workbook_header}

    assert by_header["Audit Date"].required_for_audited is True
    assert by_header["Press/Machine #"].required_for_audited is True
    assert by_header["Press/Machine #"].required_for_compatible is True
    assert by_header[TOOL_FIELD].required_for_compatible is True
    assert by_header["Priority"].important is True
    assert by_header["Known Issues"].important is True


def test_sections_and_groups_expose_specs():
    assert fields_for_section("Audit Header")
    grouped = fields_grouped_by_section()

    assert "Audit Header" in grouped
    assert "Audit Identity" in grouped["Audit Header"]
    assert grouped["EOAT Type and Tooling"]["Cylinder Details"][0].workbook_header == CYLINDER_COUNT_FIELD


def test_eoat_tooling_grouping_keeps_parts_picked_out_of_gripper_details():
    group_layout = audit_section_groups()["EOAT Type and Tooling"]
    groups = dict(group_layout)

    assert [group_name for group_name, _fields in group_layout] == [
        "EOAT Classification",
        "Part Handling",
        "Gripper Details",
        "Cylinder Details",
        "Vacuum / Cup Details",
        "Physical Details",
    ]
    assert groups["Part Handling"] == [NUMBER_OF_PARTS_PICKED_FIELD]
    assert NUMBER_OF_PARTS_PICKED_FIELD not in groups["Gripper Details"]
    assert groups["Gripper Details"] == [GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD, GRIPPER_SIZE_FIELD]

    grouped_specs = fields_grouped_by_section()["EOAT Type and Tooling"]
    assert grouped_specs["Part Handling"][0].workbook_header == NUMBER_OF_PARTS_PICKED_FIELD
    assert field_by_header(NUMBER_OF_PARTS_PICKED_FIELD).workbook_header == NUMBER_OF_PARTS_PICKED_FIELD
    assert expected_workbook_headers() == tuple(get_expected_headers("EOAT Inventory"))
