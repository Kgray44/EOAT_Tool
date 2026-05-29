from __future__ import annotations

from core.audit.guided import (
    all_guided_audit_steps,
    guided_applicability_preview,
    guided_step_fields,
    missing_section_form_fields,
)
from core.audit.schema import audit_sections
from core.audit_field_rules import field_applies


def test_guided_steps_include_existing_fields():
    guided_fields = set(guided_step_fields())
    section_fields = {
        field
        for fields in audit_sections().values()
        for field in fields
        if field not in {"Entry Type", "Source Audit ID", "Compatibility Source"}
    }

    assert [step.title for step in all_guided_audit_steps()] == [
        "Identify machine and robot",
        "Classify EOAT",
        "Tooling details",
        "Pneumatic circuits",
        "Sensors and electrical",
        "Routing, mechanical, and reliability",
        "Documentation and photo evidence",
        "Final review and save impact",
    ]
    assert not missing_section_form_fields()
    assert section_fields <= guided_fields


def test_applicability_preview_matches_field_rules():
    entry = {"EOAT Type": "Mechanical / Gripper", "Sensors Present?": "No", "Electrical/Wiring Present?": "No"}
    preview = guided_applicability_preview(entry)

    assert preview["Gripper Model"] == field_applies(entry, "Gripper Model")
    assert preview["# of Cups"] == field_applies(entry, "# of Cups")
    assert preview["Sensor Type"] == field_applies(entry, "Sensor Type")
    assert preview["Cable Management Condition"] == field_applies(entry, "Cable Management Condition")


def test_hybrid_guided_preview_shows_vacuum_and_gripper_fields():
    preview = guided_applicability_preview({"EOAT Type": "Hybrid", "Sensors Present?": "Yes"})

    assert preview["# of Cups"] is True
    assert preview["Cup Type/Material"] is True
    assert preview["# of Grippers"] is True
    assert preview["Gripper Model"] is True


def test_miscellaneous_guided_preview_allows_broad_tooling_fields_and_cylinders():
    preview = guided_applicability_preview({"EOAT Type": "Miscellaneous"})

    assert preview["# of Grippers"] is True
    assert preview["Gripper Model"] is True
    assert preview["# of Cylinders"] is True
    assert preview["Cylinder Type"] is True
