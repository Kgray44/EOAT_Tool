from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from core.audit.schema import audit_sections
from core.audit_field_rules import field_applies


@dataclass(frozen=True)
class GuidedAuditStep:
    id: str
    title: str
    fields: tuple[str, ...]
    section_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


GUIDED_AUDIT_STEPS: tuple[GuidedAuditStep, ...] = (
    GuidedAuditStep(
        id="identify_machine_robot",
        title="Identify machine and robot",
        fields=(
            "Audit ID",
            "Audit Date",
            "Auditor",
            "Plant/Area",
            "Press/Machine #",
            "Robot Type",
            "Robot Model/Controller",
            "Cleanroom/Non-Cleanroom",
        ),
        section_hint="Audit Header",
    ),
    GuidedAuditStep(
        id="classify_eoat",
        title="Classify EOAT",
        fields=(
            "EOAT Type",
            "EOAT Moves",
            "Connection Type",
            "Number of Parts Picked",
            "# of Cylinders",
            "Cylinder Type",
        ),
        section_hint="EOAT Type and Tooling",
    ),
    GuidedAuditStep(
        id="tooling_details",
        title="Tooling details",
        fields=(
            "Tool #",
            "Part Family",
            "Part Name/Description",
            "# of Cups",
            "Cup Type/Material",
            "Cup Diameter/Size",
            "Vacuum Generator Type",
            "# of Grippers",
            "Gripper Type",
            "Gripper Model",
            "Estimated EOAT Weight",
        ),
        section_hint="EOAT Type and Tooling",
    ),
    GuidedAuditStep(
        id="pneumatic_circuits",
        title="Pneumatic circuits",
        fields=(
            "Air Circuit Architecture",
            "EOAT Vacuum Circuits",
            "EOAT Pressure Circuits",
            "EOAT Interchangeable Circuits",
            "Robot Vacuum Circuits",
            "Robot Pressure Circuits",
            "Robot Interchangeable Circuits",
            "External Vacuum Circuits",
            "External Pressure Circuits",
            "External Interchangeable Circuits",
            "Robot Notes",
        ),
        section_hint="Pneumatic Circuits",
    ),
    GuidedAuditStep(
        id="sensors_electrical",
        title="Sensors and electrical",
        fields=(
            "Sensors Present?",
            "Sensor Type",
            "Sensor Brand/Model",
            "Vacuum Confirmation Present?",
            "Part-Present Detection Present?",
            "Electrical/Wiring Present?",
            "Electrical Quick Disconnect Type",
        ),
        section_hint="Sensors and Detection",
    ),
    GuidedAuditStep(
        id="routing_mechanical_reliability",
        title="Routing, mechanical, and reliability",
        fields=(
            "Quick Disconnects Present?",
            "Pneumatic Quick Disconnect Type",
            "Tubing Condition",
            "Tubing Routing Notes",
            "Cable Management Condition",
            "Mounting Hardware Condition",
            "EOAT Alignment Condition",
            "Fastener/Locking Hardware Present?",
            "Known Issues",
            "Drop/Mis-Pick History",
            "Maintenance Frequency",
            "Cycle Time Concern?",
            "Scrap/Quality Concern?",
            "Changeover Difficulty",
        ),
        section_hint="Connections / Routing / Mechanical",
    ),
    GuidedAuditStep(
        id="documentation_photo_evidence",
        title="Documentation and photo evidence",
        fields=(
            "Spare Parts Identified?",
            "Drawing/CAD Available?",
            "BOM Available?",
            "Process Binder Complete?",
            "Photos Taken?",
            "Photo Folder/Link",
        ),
        section_hint="Documentation / Photos",
    ),
    GuidedAuditStep(
        id="final_review_save_impact",
        title="Final review and save impact",
        fields=("Status", "Priority", "Follow-Up Needed", "Pilot Candidate?", "Notes"),
        section_hint="Pilot / Final Notes",
    ),
)

ALWAYS_GUIDED_APPLICABLE_FIELDS = {"# of Cylinders", "Cylinder Type"}


def all_guided_audit_steps() -> tuple[GuidedAuditStep, ...]:
    return GUIDED_AUDIT_STEPS


def guided_step_fields() -> tuple[str, ...]:
    fields: list[str] = []
    seen: set[str] = set()
    for step in GUIDED_AUDIT_STEPS:
        for field in step.fields:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    return tuple(fields)


def missing_section_form_fields() -> tuple[str, ...]:
    guided = set(guided_step_fields())
    missing = [
        field
        for fields in audit_sections().values()
        for field in fields
        if field not in guided and field not in {"Source Audit ID", "Compatibility Source", "Entry Type"}
    ]
    return tuple(missing)


def guided_applicability_preview(entry: Mapping[str, Any]) -> dict[str, bool]:
    current = {str(key): "" if value is None else str(value) for key, value in entry.items()}
    return {
        field: True if field in ALWAYS_GUIDED_APPLICABLE_FIELDS else field_applies(current, field)
        for field in guided_step_fields()
    }


__all__ = [
    "ALWAYS_GUIDED_APPLICABLE_FIELDS",
    "GUIDED_AUDIT_STEPS",
    "GuidedAuditStep",
    "all_guided_audit_steps",
    "guided_applicability_preview",
    "guided_step_fields",
    "missing_section_form_fields",
]
