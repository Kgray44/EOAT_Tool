from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .audit_constants import (
    COMPATIBILITY_SOURCE_FIELD,
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_DEFAULT,
    CYLINDER_TYPE_FIELD,
    ENTRY_TYPE_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from .audit.defaults import DEFAULT_AUDIT_DEFAULTS
from .audit_entries import AUDIT_DROPDOWNS, EOAT_INTERCHANGEABLE_CIRCUITS_FIELD, NUMBER_OF_PARTS_PICKED_FIELD
from .audit_field_rules import FIELD_GROUPS, field_applies
from .gripper_fields import CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD, GRIPPER_MODEL_FIELD, GRIPPER_SIZE_FIELD, GRIPPER_TYPE_FIELD
from .tool_fields import TOOL_FIELD

PNEUMATIC_CIRCUITS_SECTION = "Pneumatic Circuits"

AUDIT_SECTION_LAYOUT: dict[str, list[str]] = {
    "Audit Header": ["Audit ID", "Audit Date", "Auditor", "Plant/Area", "Press/Machine #", "Status", "Priority", "Follow-Up Needed"],
    "Machine / Robot / Tool Context": ["Robot Type", "Robot Model/Controller", TOOL_FIELD, "Part Family", "Part Name/Description", "Cleanroom/Non-Cleanroom"],
    "EOAT Type and Tooling": [
        "EOAT Type",
        "EOAT Moves",
        "Connection Type",
        NUMBER_OF_PARTS_PICKED_FIELD,
        CYLINDER_COUNT_FIELD,
        CYLINDER_TYPE_FIELD,
        GRIPPER_COUNT_FIELD,
        GRIPPER_TYPE_FIELD,
        GRIPPER_MODEL_FIELD,
        GRIPPER_SIZE_FIELD,
        CUP_COUNT_FIELD,
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Vacuum Generator Type",
        "Estimated EOAT Weight",
    ],
    PNEUMATIC_CIRCUITS_SECTION: [
        "EOAT Vacuum Circuits",
        "EOAT Pressure Circuits",
        EOAT_INTERCHANGEABLE_CIRCUITS_FIELD,
        "Robot Vacuum Circuits",
        "Robot Pressure Circuits",
        "Robot Interchangeable Circuits",
    ],
    "Sensors and Detection": ["Sensors Present?", "Sensor Type", "Sensor Brand/Model", "Vacuum Confirmation Present?", "Part-Present Detection Present?", "Electrical/Wiring Present?"],
    "Connections / Routing / Mechanical": [
        "Quick Disconnects Present?",
        "Pneumatic Quick Disconnect Type",
        "Electrical Quick Disconnect Type",
        "Tubing Condition",
        "Tubing Routing Notes",
        "Cable Management Condition",
        "Mounting Hardware Condition",
        "EOAT Alignment Condition",
        "Fastener/Locking Hardware Present?",
    ],
    "Performance / Reliability / Maintenance": ["Known Issues", "Drop/Mis-Pick History", "Maintenance Frequency", "Cycle Time Concern?", "Scrap/Quality Concern?", "Changeover Difficulty"],
    "Documentation / Photos": ["Spare Parts Identified?", "Drawing/CAD Available?", "BOM Available?", "Process Binder Complete?", "Photos Taken?", "Photo Folder/Link"],
    "Pilot / Final Notes": ["Pilot Candidate?", "Notes"],
}

AUDIT_GROUP_LAYOUT: dict[str, list[tuple[str, list[str]]]] = {
    "Audit Header": [
        ("Audit Identity", ["Audit ID", "Audit Date", "Auditor"]),
        ("Location / Machine", ["Plant/Area", "Press/Machine #"]),
        ("Audit Status", ["Status", "Priority", "Follow-Up Needed"]),
    ],
    "Machine / Robot / Tool Context": [
        ("Robot Information", ["Robot Type", "Robot Model/Controller"]),
        ("Tool / Part Information", [TOOL_FIELD, "Part Family", "Part Name/Description"]),
        ("Production Environment", ["Cleanroom/Non-Cleanroom"]),
    ],
    "EOAT Type and Tooling": [
        ("EOAT Classification", ["EOAT Type", "EOAT Moves", "Connection Type"]),
        ("Part Pickup", [NUMBER_OF_PARTS_PICKED_FIELD, GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD, GRIPPER_SIZE_FIELD]),
        ("Cylinders", [CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD]),
        ("Vacuum / Cup Details", [CUP_COUNT_FIELD, "Cup Type/Material", "Cup Diameter/Size", "Vacuum Generator Type"]),
        ("Physical Details", ["Estimated EOAT Weight"]),
    ],
    PNEUMATIC_CIRCUITS_SECTION: [
        ("EOAT Side", ["EOAT Vacuum Circuits", "EOAT Pressure Circuits", EOAT_INTERCHANGEABLE_CIRCUITS_FIELD]),
        ("Robot Side", ["Robot Vacuum Circuits", "Robot Pressure Circuits", "Robot Interchangeable Circuits"]),
    ],
    "Sensors and Detection": [
        ("Detection Presence", ["Sensors Present?", "Vacuum Confirmation Present?", "Part-Present Detection Present?"]),
        ("Sensor Details", ["Sensor Type", "Sensor Brand/Model"]),
        ("Electrical / Wiring", ["Electrical/Wiring Present?"]),
    ],
    "Connections / Routing / Mechanical": [
        ("Quick Disconnects", ["Quick Disconnects Present?", "Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"]),
        ("Tubing / Routing", ["Tubing Condition", "Tubing Routing Notes"]),
        ("Cable Management", ["Cable Management Condition"]),
        ("Mechanical Condition", ["Mounting Hardware Condition", "EOAT Alignment Condition", "Fastener/Locking Hardware Present?"]),
    ],
    "Performance / Reliability / Maintenance": [
        ("Known Problems", ["Known Issues", "Drop/Mis-Pick History"]),
        ("Maintenance", ["Maintenance Frequency"]),
        ("Production Impact", ["Cycle Time Concern?", "Scrap/Quality Concern?"]),
        ("Changeover", ["Changeover Difficulty"]),
    ],
    "Documentation / Photos": [
        ("Documentation Status", ["Drawing/CAD Available?", "BOM Available?", "Process Binder Complete?"]),
        ("Photo Evidence", ["Photos Taken?", "Photo Folder/Link"]),
        ("Spare Parts", ["Spare Parts Identified?"]),
    ],
    "Pilot / Final Notes": [("Pilot Evaluation", ["Pilot Candidate?"]), ("Final Notes", ["Notes"])],
}

METADATA_FIELDS = [
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
    COMPATIBILITY_SOURCE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
]


@dataclass(frozen=True)
class AuditFieldSpec:
    field_id: str
    label: str
    workbook_header: str
    section: str
    group: str = ""
    widget_type: str = "text"
    options: tuple[str, ...] = ()
    default_value: str = ""
    visibility_group: str = "notes"
    required_for: tuple[str, ...] = ()
    important: bool = False
    legacy_headers: tuple[str, ...] = ()
    system_field: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_sections() -> dict[str, list[str]]:
    return {section: list(fields) for section, fields in AUDIT_SECTION_LAYOUT.items()}


def audit_section_groups() -> dict[str, list[tuple[str, list[str]]]]:
    return {section: [(group, list(fields)) for group, fields in groups] for section, groups in AUDIT_GROUP_LAYOUT.items()}


def audit_field_order(*, include_metadata: bool = False) -> list[str]:
    fields: list[str] = []
    for section_fields in AUDIT_SECTION_LAYOUT.values():
        fields.extend(section_fields)
    if include_metadata:
        fields.extend(field_name for field_name in METADATA_FIELDS if field_name not in fields)
    return fields


def audit_field_specs(*, include_metadata: bool = True) -> tuple[AuditFieldSpec, ...]:
    specs: list[AuditFieldSpec] = []
    for section, fields in AUDIT_SECTION_LAYOUT.items():
        for field_name in fields:
            specs.append(_build_spec(field_name, section=section, group=_group_for_field(section, field_name)))
    if include_metadata:
        existing = {spec.workbook_header for spec in specs}
        specs.extend(_build_spec(field_name, section="System Metadata", group="System Metadata", system_field=True) for field_name in METADATA_FIELDS if field_name not in existing)
    return tuple(specs)


def audit_field_registry(*, include_metadata: bool = True) -> dict[str, AuditFieldSpec]:
    return {spec.workbook_header: spec for spec in audit_field_specs(include_metadata=include_metadata)}


def get_audit_field_spec(field_name: str) -> AuditFieldSpec:
    normalized = str(field_name or "").strip()
    registry = audit_field_registry()
    if normalized in registry:
        return registry[normalized]
    folded = normalized.casefold()
    for header, spec in registry.items():
        if header.casefold() == folded:
            return spec
    raise KeyError(field_name)


def section_for_field(field_name: str) -> str | None:
    try:
        return get_audit_field_spec(field_name).section
    except KeyError:
        return None


def fields_for_section(section_name: str) -> list[AuditFieldSpec]:
    return [spec for spec in audit_field_specs(include_metadata=False) if spec.section == section_name]


def field_options(field_name: str) -> tuple[str, ...]:
    return get_audit_field_spec(field_name).options


def fields_applicable_to_entry(entry: dict[str, Any], fields: list[str] | None = None) -> list[str]:
    candidates = fields if fields is not None else audit_field_order()
    return [field_name for field_name in candidates if field_applies(entry, field_name)]


def _build_spec(field_name: str, *, section: str, group: str, system_field: bool = False) -> AuditFieldSpec:
    return AuditFieldSpec(
        field_id=_field_id(field_name),
        label=field_name,
        workbook_header=field_name,
        section=section,
        group=group,
        widget_type=_widget_type(field_name),
        options=_options_for(field_name),
        default_value=_default_for(field_name),
        visibility_group=FIELD_GROUPS.get(field_name, "system_metadata" if system_field else "notes"),
        required_for=_required_for(field_name),
        important=field_name in _important_fields(),
        legacy_headers=_legacy_headers(field_name),
        system_field=system_field,
    )


def _group_for_field(section: str, field_name: str) -> str:
    for group_name, fields in AUDIT_GROUP_LAYOUT.get(section, []):
        if field_name in fields:
            return group_name
    return section


def _field_id(field_name: str) -> str:
    text = str(field_name).strip().casefold()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "field"


def _widget_type(field_name: str) -> str:
    if field_name in {
        NUMBER_OF_PARTS_PICKED_FIELD,
        CYLINDER_COUNT_FIELD,
        CUP_COUNT_FIELD,
        GRIPPER_COUNT_FIELD,
        "EOAT Vacuum Circuits",
        "EOAT Pressure Circuits",
        EOAT_INTERCHANGEABLE_CIRCUITS_FIELD,
        "Robot Vacuum Circuits",
        "Robot Pressure Circuits",
        "Robot Interchangeable Circuits",
    }:
        return "integer"
    if field_name in {"Known Issues", "Drop/Mis-Pick History", "Tubing Routing Notes", "Notes", IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD}:
        return "textarea"
    if _options_for(field_name):
        return "dropdown"
    if "Date" in field_name or field_name.endswith("Timestamp"):
        return "date_text"
    return "text"


def _options_for(field_name: str) -> tuple[str, ...]:
    if field_name in AUDIT_DROPDOWNS:
        return tuple(AUDIT_DROPDOWNS[field_name])
    if field_name in {
        "Sensors Present?",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
        "Spare Parts Identified?",
        "Drawing/CAD Available?",
        "BOM Available?",
        "Process Binder Complete?",
    }:
        return tuple(AUDIT_DROPDOWNS["YesNoUnknown"])
    if field_name in {"Cycle Time Concern?", "Scrap/Quality Concern?", MANUAL_COMPLETION_OVERRIDE_FIELD}:
        return ("Yes", "No", "Unknown / Not Checked")
    return ()


def _default_for(field_name: str) -> str:
    if field_name == CYLINDER_TYPE_FIELD:
        return CYLINDER_TYPE_DEFAULT
    value = DEFAULT_AUDIT_DEFAULTS.get(field_name)
    return "" if value is None else str(value)


def _required_for(field_name: str) -> tuple[str, ...]:
    if field_name in {"Audit Date", "Auditor", "Plant/Area", "Press/Machine #", "Robot Type", "EOAT Type", "Status"}:
        return ("audited",)
    if field_name in {"Press/Machine #", TOOL_FIELD}:
        return ("compatible",)
    return ()


def _important_fields() -> set[str]:
    return {
        TOOL_FIELD,
        "Part Family",
        "EOAT Moves",
        CUP_COUNT_FIELD,
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
        "Electrical Quick Disconnect Type",
        "Tubing Condition",
        "Cable Management Condition",
        "Known Issues",
        "Photos Taken?",
        "Priority",
    }


def _legacy_headers(field_name: str) -> tuple[str, ...]:
    if field_name == TOOL_FIELD:
        return ("EOAT Number",)
    if field_name == CUP_COUNT_FIELD:
        return ("Number of Vacuum Cups", "Vacuum Cup Count")
    return ()

