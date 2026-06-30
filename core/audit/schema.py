from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from ..audit.defaults import DEFAULT_AUDIT_DEFAULTS
from ..audit_constants import (
    AIR_ARCHITECTURE_VALUES,
    AIR_CIRCUIT_ARCHITECTURE_FIELD,
    AUDIT_CONTEXT_FIELD,
    COMPATIBILITY_CONFIDENCE_FIELD,
    COMPATIBILITY_SOURCE_FIELD,
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_FIELD,
    ENTRY_TYPE_FIELD,
    EXTERNAL_PNEUMATIC_FIELDS,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
    PHYSICAL_AUDIT_VERIFIED_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from ..audit_constants import (
    ROBOT_PNEUMATIC_FIELDS as ROBOT_PNEUMATIC_FIELD_NAMES,
)
from ..audit_entries import (
    AUDIT_DROPDOWNS,
    AUDIT_FIELD_METADATA,
    LEGACY_VACUUM_CUPS_FIELD,
    NUMBER_OF_PARTS_PICKED_FIELD,
    PART_PRESENT_DETECTION_FIELD,
)
from ..audit_field_rules import (
    AUDITED_REQUIRED_FIELDS,
    COMPATIBLE_REQUIRED_FIELDS,
    FIELD_GROUPS,
    IMPORTANT_FIELDS,
    PNEUMATIC_CIRCUIT_FIELDS,
)
from ..eoat_ids import EOAT_ASSEMBLY_ID_FIELD
from ..gripper_fields import (
    CUP_COUNT_FIELD,
    GRIPPER_COUNT_FIELD,
    GRIPPER_MODEL_FIELD,
    GRIPPER_MODEL_PRESET_LABELS,
    GRIPPER_TYPE_FIELD,
)
from ..tool_fields import LEGACY_TOOL_FIELD, TOOL_FIELD
from ..workbook_schema import get_expected_headers

STORAGE_EOAT_INVENTORY = "EOAT Inventory"
STORAGE_NONE = "none"
PNEUMATIC_CIRCUITS_SECTION = "Pneumatic Circuits"
ROBOT_NOTES_FIELD = "Robot Notes"

ROBOT_PNEUMATIC_FIELDS = ROBOT_PNEUMATIC_FIELD_NAMES
ROBOT_INFO_FIELDS = (
    *ROBOT_PNEUMATIC_FIELDS,
    ROBOT_NOTES_FIELD,
)

AUDIT_SECTION_LAYOUT: dict[str, list[str]] = {
    "Audit Header": [
        "Audit ID",
        "Audit Date",
        "Auditor",
        "Plant/Area",
        "Press/Machine #",
        AUDIT_CONTEXT_FIELD,
        "Status",
        "Priority",
        "Follow-Up Needed",
    ],
    "Machine / Robot / Tool Context": [
        "Robot Type",
        "Robot Model/Controller",
        TOOL_FIELD,
        EOAT_ASSEMBLY_ID_FIELD,
        "Part Family",
        "Part Name/Description",
        "Cleanroom/Non-Cleanroom",
    ],
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
        CUP_COUNT_FIELD,
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Vacuum Generator Type",
        "Estimated EOAT Weight",
    ],
    PNEUMATIC_CIRCUITS_SECTION: [
        AIR_CIRCUIT_ARCHITECTURE_FIELD,
        "EOAT Vacuum Circuits",
        "EOAT Pressure Circuits",
        "EOAT Interchangeable Circuits",
        *ROBOT_PNEUMATIC_FIELDS,
        *EXTERNAL_PNEUMATIC_FIELDS,
        ROBOT_NOTES_FIELD,
    ],
    "Sensors and Detection": [
        "Sensors Present?",
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        PART_PRESENT_DETECTION_FIELD,
        "Electrical/Wiring Present?",
    ],
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
    "Performance / Reliability / Maintenance": [
        "Known Issues",
        "Drop/Mis-Pick History",
        "Maintenance Frequency",
        "Cycle Time Concern?",
        "Scrap/Quality Concern?",
        "Changeover Difficulty",
    ],
    "Documentation / Photos": [
        "Spare Parts Identified?",
        "Drawing/CAD Available?",
        "BOM Available?",
        "Process Binder Complete?",
        "Photos Taken?",
        "Photo Folder/Link",
    ],
    "Pilot / Final Notes": ["Pilot Candidate?", "Notes"],
}

AUDIT_GROUP_LAYOUT: dict[str, list[tuple[str, list[str]]]] = {
    "Audit Header": [
        ("Audit Identity", ["Audit ID", "Audit Date", "Auditor"]),
        ("Location / Context", ["Plant/Area", "Press/Machine #", AUDIT_CONTEXT_FIELD]),
        ("Audit Status", ["Status", "Priority", "Follow-Up Needed"]),
    ],
    "Machine / Robot / Tool Context": [
        ("Robot Information", ["Robot Type", "Robot Model/Controller"]),
        ("Tool / Part Information", [TOOL_FIELD, EOAT_ASSEMBLY_ID_FIELD, "Part Family", "Part Name/Description"]),
        ("Production Environment", ["Cleanroom/Non-Cleanroom"]),
    ],
    "EOAT Type and Tooling": [
        ("EOAT Classification", ["EOAT Type", "EOAT Moves", "Connection Type"]),
        ("Part Handling", [NUMBER_OF_PARTS_PICKED_FIELD]),
        ("Gripper Details", [GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD]),
        ("Cylinder Details", [CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD]),
        ("Vacuum / Cup Details", [CUP_COUNT_FIELD, "Cup Type/Material", "Cup Diameter/Size", "Vacuum Generator Type"]),
        ("Physical Details", ["Estimated EOAT Weight"]),
    ],
    PNEUMATIC_CIRCUITS_SECTION: [
        ("Air Circuit Architecture", [AIR_CIRCUIT_ARCHITECTURE_FIELD]),
        ("EOAT Total / Tool-Side Circuits", ["EOAT Vacuum Circuits", "EOAT Pressure Circuits", "EOAT Interchangeable Circuits"]),
        ("Robot-Supplied Circuits", list(ROBOT_PNEUMATIC_FIELDS)),
        ("External Peripheral IO Circuits", list(EXTERNAL_PNEUMATIC_FIELDS)),
        ("Air Circuit Notes", [ROBOT_NOTES_FIELD]),
    ],
    "Sensors and Detection": [
        ("Detection Presence", ["Sensors Present?", "Vacuum Confirmation Present?", PART_PRESENT_DETECTION_FIELD]),
        ("Sensor Details", ["Sensor Type", "Sensor Brand/Model"]),
        ("Electrical / Wiring", ["Electrical/Wiring Present?"]),
    ],
    "Connections / Routing / Mechanical": [
        (
            "Quick Disconnects",
            ["Quick Disconnects Present?", "Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"],
        ),
        ("Tubing / Routing", ["Tubing Condition", "Tubing Routing Notes"]),
        ("Cable Management", ["Cable Management Condition"]),
        (
            "Mechanical Condition",
            ["Mounting Hardware Condition", "EOAT Alignment Condition", "Fastener/Locking Hardware Present?"],
        ),
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
    "System Metadata": [
        (
            "Completion Metadata",
            [
                MANUAL_COMPLETION_OVERRIDE_FIELD,
                MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
                MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
                IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
            ],
        ),
        (
            "Compatibility Metadata",
            [
                ENTRY_TYPE_FIELD,
                SOURCE_AUDIT_ID_FIELD,
                COMPATIBILITY_SOURCE_FIELD,
                PHYSICAL_AUDIT_VERIFIED_FIELD,
                COMPATIBILITY_CONFIDENCE_FIELD,
            ],
        ),
    ],
}

SYSTEM_METADATA_FIELDS = [
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    ENTRY_TYPE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
    COMPATIBILITY_SOURCE_FIELD,
    PHYSICAL_AUDIT_VERIFIED_FIELD,
    COMPATIBILITY_CONFIDENCE_FIELD,
]

_TEXTAREA_FIELDS = {
    "Known Issues",
    "Drop/Mis-Pick History",
    "Tubing Routing Notes",
    "Notes",
    "Part Name/Description",
    ROBOT_NOTES_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
}
_NUMERIC_FIELDS = {
    NUMBER_OF_PARTS_PICKED_FIELD,
    CYLINDER_COUNT_FIELD,
    CUP_COUNT_FIELD,
    GRIPPER_COUNT_FIELD,
    *PNEUMATIC_CIRCUIT_FIELDS,
    *ROBOT_PNEUMATIC_FIELDS,
}
_YES_NO_UNKNOWN_FIELDS = {
    "Sensors Present?",
    "Cycle Time Concern?",
    "Scrap/Quality Concern?",
    "Drawing/CAD Available?",
    "BOM Available?",
}
_YES_NO_UNKNOWN_NA_FIELDS = {"Vacuum Confirmation Present?", PART_PRESENT_DETECTION_FIELD}
_YES_NO_PARTIAL_UNKNOWN_FIELDS = {
    "Fastener/Locking Hardware Present?",
    "Spare Parts Identified?",
    "Process Binder Complete?",
}
_EDITABLE_DROPDOWNS = {"Robot Type", GRIPPER_MODEL_FIELD}
_NO_BLANK_DROPDOWNS = {"Plant/Area", "Connection Type", AUDIT_CONTEXT_FIELD, ENTRY_TYPE_FIELD}


@dataclass(frozen=True)
class AuditFieldSpec:
    field_id: str
    label: str
    workbook_header: str
    section: str
    group: str
    widget_type: str = "text"
    storage_target: str = STORAGE_EOAT_INVENTORY
    dropdown_values: tuple[str, ...] = ()
    editable_dropdown: bool = False
    include_blank: bool = True
    default: str = ""
    numeric: bool = False
    required_for_audited: bool = False
    required_for_compatible: bool = False
    important: bool = False
    visibility_rule: str = "always"
    progress_policy: str = "optional"
    optional_group: str = ""
    legacy_headers: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    help_text: str = ""

    @property
    def options(self) -> tuple[str, ...]:
        return self.dropdown_values

    @property
    def default_value(self) -> str:
        return self.default

    @property
    def required_for(self) -> tuple[str, ...]:
        values: list[str] = []
        if self.required_for_audited:
            values.append("audited")
        if self.required_for_compatible:
            values.append("compatible")
        return tuple(values)

    @property
    def visibility_group(self) -> str:
        return self.optional_group or FIELD_GROUPS.get(self.label, "notes")

    @property
    def system_field(self) -> bool:
        return self.section == "System Metadata" or "system_metadata" in self.tags

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def all_audit_fields() -> tuple[AuditFieldSpec, ...]:
    specs: list[AuditFieldSpec] = []
    seen_labels: set[str] = set()
    for section, labels in AUDIT_SECTION_LAYOUT.items():
        for label in labels:
            specs.append(_build_spec(label, section=section, group=_group_for_field(section, label)))
            seen_labels.add(label)
    for label in SYSTEM_METADATA_FIELDS:
        if label not in seen_labels:
            specs.append(
                _build_spec(label, section="System Metadata", group=_group_for_field("System Metadata", label))
            )
            seen_labels.add(label)

    expected = get_expected_headers(STORAGE_EOAT_INVENTORY)
    known_headers = {spec.workbook_header for spec in specs if spec.storage_target != STORAGE_NONE}
    for header in expected:
        if header not in known_headers:
            specs.append(_build_spec(header, section="Unsectioned", group="Unsectioned"))
    return tuple(specs)


def field_by_id(field_id: str) -> AuditFieldSpec:
    normalized = str(field_id or "").strip().casefold()
    for spec in all_audit_fields():
        if spec.field_id.casefold() == normalized:
            return spec
    raise KeyError(field_id)


def field_by_header(header: str) -> AuditFieldSpec:
    normalized = str(header or "").strip()
    folded = normalized.casefold()
    for spec in all_audit_fields():
        headers = [spec.workbook_header, *spec.legacy_headers]
        if any(candidate and candidate.casefold() == folded for candidate in headers):
            return spec
    raise KeyError(header)


def fields_for_section(section: str) -> tuple[AuditFieldSpec, ...]:
    return tuple(spec for spec in all_audit_fields() if spec.section == section)


def fields_grouped_by_section() -> dict[str, dict[str, tuple[AuditFieldSpec, ...]]]:
    grouped: dict[str, dict[str, list[AuditFieldSpec]]] = {}
    for spec in all_audit_fields():
        grouped.setdefault(spec.section, {}).setdefault(spec.group, []).append(spec)
    return {section: {group: tuple(fields) for group, fields in groups.items()} for section, groups in grouped.items()}


def expected_workbook_headers() -> tuple[str, ...]:
    by_header = {
        spec.workbook_header: spec
        for spec in all_audit_fields()
        if spec.storage_target == STORAGE_EOAT_INVENTORY and spec.workbook_header
    }
    return tuple(header for header in get_expected_headers(STORAGE_EOAT_INVENTORY) if header in by_header)


def dropdown_values_for(field_or_header: str) -> tuple[str, ...]:
    return field_by_header(field_or_header).dropdown_values


def audit_sections() -> dict[str, list[str]]:
    return {section: list(fields) for section, fields in AUDIT_SECTION_LAYOUT.items()}


def audit_section_groups() -> dict[str, list[tuple[str, list[str]]]]:
    return {
        section: [(group, list(fields)) for group, fields in groups]
        for section, groups in AUDIT_GROUP_LAYOUT.items()
        if section != "System Metadata"
    }


def _build_spec(label: str, *, section: str, group: str) -> AuditFieldSpec:
    storage_target = STORAGE_NONE if label in ROBOT_INFO_FIELDS else STORAGE_EOAT_INVENTORY
    workbook_header = "" if storage_target == STORAGE_NONE else label
    dropdown_values = _dropdown_values(label)
    required_for_audited = label in AUDITED_REQUIRED_FIELDS
    required_for_compatible = label in COMPATIBLE_REQUIRED_FIELDS
    important = label in IMPORTANT_FIELDS
    tags = _tags_for(label, section, storage_target, required_for_audited, required_for_compatible, important)
    return AuditFieldSpec(
        field_id=_field_id(label),
        label=label,
        workbook_header=workbook_header,
        section=section,
        group=group,
        widget_type=_widget_type(label, dropdown_values),
        storage_target=storage_target,
        dropdown_values=dropdown_values,
        editable_dropdown=label in _EDITABLE_DROPDOWNS,
        include_blank=label not in _NO_BLANK_DROPDOWNS,
        default=_default_for(label),
        numeric=label in _NUMERIC_FIELDS,
        required_for_audited=required_for_audited,
        required_for_compatible=required_for_compatible,
        important=important,
        visibility_rule=_visibility_rule(label),
        progress_policy=_progress_policy(
            section, storage_target, required_for_audited, required_for_compatible, important
        ),
        optional_group=FIELD_GROUPS.get(label, "system_metadata" if section == "System Metadata" else ""),
        legacy_headers=_legacy_headers(label),
        tags=tags,
        help_text=_help_text(label, storage_target),
    )


def _group_for_field(section: str, label: str) -> str:
    for group_name, fields in AUDIT_GROUP_LAYOUT.get(section, []):
        if label in fields:
            return group_name
    return section


def _field_id(label: str) -> str:
    explicit = {
        "Press/Machine #": "press_machine",
        TOOL_FIELD: "tool",
        EOAT_ASSEMBLY_ID_FIELD: "eoat_assembly_id",
        NUMBER_OF_PARTS_PICKED_FIELD: "parts_picked_count",
        CYLINDER_COUNT_FIELD: "cylinder_count",
        GRIPPER_COUNT_FIELD: "gripper_count",
        CUP_COUNT_FIELD: "cup_count",
    }
    if label in explicit:
        return explicit[label]
    text = str(label).strip().casefold()
    text = text.replace("#", " number ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text or "field"


def _dropdown_values(label: str) -> tuple[str, ...]:
    if label == AIR_CIRCUIT_ARCHITECTURE_FIELD:
        return tuple(AIR_ARCHITECTURE_VALUES)
    if label == GRIPPER_MODEL_FIELD:
        return tuple(GRIPPER_MODEL_PRESET_LABELS)
    if label in AUDIT_DROPDOWNS:
        return tuple(AUDIT_DROPDOWNS[label])
    if label in _YES_NO_UNKNOWN_FIELDS:
        return tuple(AUDIT_DROPDOWNS["YesNoUnknown"])
    if label in _YES_NO_UNKNOWN_NA_FIELDS:
        return tuple(AUDIT_DROPDOWNS["YesNoUnknownNA"])
    if label in _YES_NO_PARTIAL_UNKNOWN_FIELDS:
        return tuple(AUDIT_DROPDOWNS["YesNoPartialUnknown"])
    if label == MANUAL_COMPLETION_OVERRIDE_FIELD:
        return ("Yes", "No")
    return ()


def _widget_type(label: str, dropdown_values: tuple[str, ...]) -> str:
    if label in _TEXTAREA_FIELDS:
        return "textarea"
    if label in _NUMERIC_FIELDS:
        return "integer"
    if dropdown_values:
        return "dropdown"
    if "Date" in label or label.endswith("Timestamp"):
        return "date_text"
    return "text"


def _default_for(label: str) -> str:
    metadata = AUDIT_FIELD_METADATA.get(label)
    if metadata is not None and metadata.default is not None:
        return str(metadata.default)
    value = DEFAULT_AUDIT_DEFAULTS.get(label)
    return "" if value is None else str(value)


def _visibility_rule(label: str) -> str:
    if label in ROBOT_INFO_FIELDS:
        return "ui_only:robot_pneumatic_circuits"
    group = FIELD_GROUPS.get(label, "")
    if group:
        return f"field_group:{group}"
    return "always"


def _progress_policy(section: str, storage_target: str, audited: bool, compatible: bool, important: bool) -> str:
    if storage_target == STORAGE_NONE:
        return "ui_only"
    if section == "System Metadata":
        return "metadata"
    if audited or compatible:
        return "required"
    if important:
        return "important"
    return "optional"


def _legacy_headers(label: str) -> tuple[str, ...]:
    legacy: dict[str, tuple[str, ...]] = {
        TOOL_FIELD: (LEGACY_TOOL_FIELD, "EOAT Number"),
        NUMBER_OF_PARTS_PICKED_FIELD: (LEGACY_VACUUM_CUPS_FIELD,),
        CUP_COUNT_FIELD: ("Vacuum Cup Count",),
        "EOAT Vacuum Circuits": ("Vacuum Zones",),
    }
    return legacy.get(label, ())


def _tags_for(
    label: str, section: str, storage_target: str, audited: bool, compatible: bool, important: bool
) -> tuple[str, ...]:
    tags: set[str] = set()
    metadata = AUDIT_FIELD_METADATA.get(label)
    if metadata is not None:
        tags.update(metadata.tags)
    if field_group := FIELD_GROUPS.get(label):
        tags.add(field_group)
    if storage_target == STORAGE_NONE:
        tags.add("ui_only")
    if section == "System Metadata":
        tags.add("system_metadata")
    if audited:
        tags.add("required_for_audited")
    if compatible:
        tags.add("required_for_compatible")
    if important:
        tags.add("important")
    if label in _NUMERIC_FIELDS:
        tags.add("numeric")
    return tuple(sorted(tags))


def _help_text(label: str, storage_target: str) -> str:
    if label == AIR_CIRCUIT_ARCHITECTURE_FIELD:
        return (
            "Defines where EOAT air circuits are supplied from. Robot Only means all air is supplied by robot "
            "pneumatic outputs. External Peripheral Only means air is supplied externally and controlled through "
            "peripheral IO. Mixed Robot + External Peripheral means both robot-supplied and external peripheral "
            "IO-controlled air are used."
        )
    if label == "External Pressure Circuits":
        return (
            "Number of pressure circuits supplied externally and controlled through peripheral IO. Do not include "
            "robot-supplied pressure circuits here."
        )
    if label == "Robot Pressure Circuits":
        return (
            "Number of pressure circuits supplied directly from the robot pneumatic outputs. Do not include "
            "externally supplied peripheral IO-controlled circuits here."
        )
    if storage_target == STORAGE_NONE:
        return f"{label} is shown in the audit UI for context and is not currently written to EOAT Inventory."
    if label in AUDITED_REQUIRED_FIELDS:
        return f"{label} is required for audited EOAT rows."
    if label in COMPATIBLE_REQUIRED_FIELDS:
        return f"{label} is required for compatible EOAT rows."
    if label in IMPORTANT_FIELDS:
        return f"{label} is important for audit completion and reporting."
    return f"Capture {label} for the EOAT Inventory when available."


__all__ = [
    "AUDIT_GROUP_LAYOUT",
    "AUDIT_SECTION_LAYOUT",
    "AuditFieldSpec",
    "PNEUMATIC_CIRCUITS_SECTION",
    "ROBOT_INFO_FIELDS",
    "ROBOT_NOTES_FIELD",
    "ROBOT_PNEUMATIC_FIELDS",
    "EXTERNAL_PNEUMATIC_FIELDS",
    "STORAGE_EOAT_INVENTORY",
    "STORAGE_NONE",
    "SYSTEM_METADATA_FIELDS",
    "all_audit_fields",
    "audit_section_groups",
    "audit_sections",
    "dropdown_values_for",
    "expected_workbook_headers",
    "field_by_header",
    "field_by_id",
    "fields_for_section",
    "fields_grouped_by_section",
]
