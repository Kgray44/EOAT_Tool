from __future__ import annotations

from core.audit_constants import CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD, MANUAL_COMPLETION_OVERRIDE_FIELD
from core.audit_field_registry import (
    audit_field_order,
    audit_field_registry,
    audit_field_specs,
    audit_section_groups,
    audit_sections,
    fields_applicable_to_entry,
    get_audit_field_spec,
    section_for_field,
)
from core.gripper_fields import CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD


def test_audit_registry_defines_stable_unique_field_ids():
    specs = audit_field_specs()

    assert specs
    assert len({spec.field_id for spec in specs}) == len(specs)
    assert len({spec.workbook_header for spec in specs}) == len(specs)
    assert get_audit_field_spec("Press/Machine #").field_id == "press_machine"
    assert get_audit_field_spec(CYLINDER_TYPE_FIELD).default_value == "Linear"
    assert get_audit_field_spec(MANUAL_COMPLETION_OVERRIDE_FIELD).system_field is True


def test_audit_sections_and_groups_are_registry_driven():
    sections = audit_sections()
    groups = audit_section_groups()

    assert list(sections)[:3] == ["Audit Header", "Machine / Robot / Tool Context", "EOAT Type and Tooling"]
    assert section_for_field(CYLINDER_COUNT_FIELD) == "EOAT Type and Tooling"
    assert ("Cylinders", [CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD]) in groups["EOAT Type and Tooling"]
    assert audit_field_order()[:4] == ["Audit ID", "Audit Date", "Auditor", "Plant/Area"]


def test_registry_exposes_widget_options_and_applicability():
    registry = audit_field_registry()

    assert registry["Status"].widget_type == "dropdown"
    assert "Complete" in registry["Status"].options
    assert registry[CUP_COUNT_FIELD].widget_type == "integer"

    mechanical_entry = {"EOAT Type": "Mechanical / Gripper"}
    applicable = fields_applicable_to_entry(mechanical_entry, [CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD])

    assert CUP_COUNT_FIELD not in applicable
    assert GRIPPER_COUNT_FIELD in applicable

