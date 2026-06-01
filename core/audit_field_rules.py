from __future__ import annotations

from typing import Any

from .audit_constants import (
    AUTOFILLED_COMPATIBILITY_METADATA_FIELDS,
    COMPATIBILITY_SOURCE_FIELD,
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_DEFAULT,
    CYLINDER_TYPE_FIELD,
    ENTRY_TYPE_AUDITED,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    SOURCE_AUDIT_ID_FIELD,
)
from .gripper_fields import (
    CUP_COUNT_FIELD,
    GRIPPER_COUNT_FIELD,
    GRIPPER_MODEL_FIELD,
    GRIPPER_SIZE_FIELD,
    GRIPPER_TYPE_FIELD,
)
from .tool_fields import TOOL_FIELD

NA_VALUE = "N/A"

EOAT_TYPE_VACUUM = "Vacuum"
EOAT_TYPE_GRIPPER = "Mechanical / Gripper"
EOAT_TYPE_HYBRID = "Hybrid"
EOAT_TYPE_UNKNOWN = "Unknown / Needs Review"
EOAT_TYPE_MISC = "Miscellaneous"
EOAT_TYPE_BLANK = "Blank/unknown"

VACUUM_TOOLING_FIELDS = {
    CUP_COUNT_FIELD,
    "Cup Type/Material",
    "Cup Diameter/Size",
    "Vacuum Generator Type",
}
PNEUMATIC_CIRCUIT_FIELDS = {
    "EOAT Vacuum Circuits",
    "EOAT Pressure Circuits",
    "EOAT Interchangeable Circuits",
    "Robot Vacuum Circuits",
    "Robot Pressure Circuits",
    "Robot Interchangeable Circuits",
}
GRIPPER_TOOLING_FIELDS = {GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD, GRIPPER_SIZE_FIELD}
SENSOR_DETAIL_FIELDS = {
    "Sensor Type",
    "Sensor Brand/Model",
    "Vacuum Confirmation Present?",
    "Part-Present Detection Present?",
}
ELECTRICAL_WIRING_PRESENT_FIELD = "Electrical/Wiring Present?"
ELECTRICAL_DETAIL_FIELDS = {"Electrical Quick Disconnect Type", "Cable Management Condition"}
QUICK_DISCONNECT_DETAIL_FIELDS = {"Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"}

FIELD_GROUPS = {
    "Audit ID": "header",
    "Audit Date": "header",
    "Auditor": "header",
    "Entry Type": "header",
    "Plant/Area": "machine_context",
    "Press/Machine #": "machine_context",
    TOOL_FIELD: "machine_context",
    "Robot Type": "machine_context",
    "Robot Model/Controller": "machine_context",
    "Part Family": "machine_context",
    "Part Name/Description": "machine_context",
    "Cleanroom/Non-Cleanroom": "machine_context",
    "EOAT Type": "machine_context",
    "EOAT Moves": "machine_context",
    "Connection Type": "tool_mounting_connection",
    "Number of Parts Picked": "tooling",
    CYLINDER_COUNT_FIELD: "cylinder_tooling",
    CYLINDER_TYPE_FIELD: "cylinder_tooling",
    CUP_COUNT_FIELD: "vacuum_tooling",
    "Cup Type/Material": "vacuum_tooling",
    "Cup Diameter/Size": "vacuum_tooling",
    "Vacuum Generator Type": "vacuum_tooling",
    GRIPPER_COUNT_FIELD: "gripper_tooling",
    GRIPPER_TYPE_FIELD: "gripper_tooling",
    GRIPPER_MODEL_FIELD: "gripper_tooling",
    GRIPPER_SIZE_FIELD: "gripper_tooling",
    "Sensors Present?": "sensor",
    "Sensor Type": "sensor",
    "Sensor Brand/Model": "sensor",
    "Vacuum Confirmation Present?": "sensor",
    "Part-Present Detection Present?": "sensor",
    ELECTRICAL_WIRING_PRESENT_FIELD: "electrical",
    "Quick Disconnects Present?": "quick_disconnect",
    "Pneumatic Quick Disconnect Type": "pneumatic",
    "EOAT Vacuum Circuits": "pneumatic_circuit",
    "EOAT Pressure Circuits": "pneumatic_circuit",
    "EOAT Interchangeable Circuits": "pneumatic_circuit",
    "Robot Vacuum Circuits": "pneumatic_circuit",
    "Robot Pressure Circuits": "pneumatic_circuit",
    "Robot Interchangeable Circuits": "pneumatic_circuit",
    "Robot Notes": "pneumatic_circuit",
    "Electrical Quick Disconnect Type": "electrical",
    "Tubing Condition": "pneumatic",
    "Tubing Routing Notes": "routing",
    "Cable Management Condition": "routing",
    "Mounting Hardware Condition": "mechanical_condition",
    "EOAT Alignment Condition": "mechanical_condition",
    "Fastener/Locking Hardware Present?": "mechanical_condition",
    "Estimated EOAT Weight": "mechanical_condition",
    "Known Issues": "reliability",
    "Drop/Mis-Pick History": "reliability",
    "Maintenance Frequency": "reliability",
    "Cycle Time Concern?": "reliability",
    "Scrap/Quality Concern?": "reliability",
    "Changeover Difficulty": "reliability",
    "Spare Parts Identified?": "documentation",
    "Drawing/CAD Available?": "documentation",
    "BOM Available?": "documentation",
    "Process Binder Complete?": "documentation",
    "Photos Taken?": "photo",
    "Photo Folder/Link": "photo",
    "Status": "pilot",
    "Priority": "pilot",
    "Pilot Candidate?": "pilot",
    "Follow-Up Needed": "pilot",
    SOURCE_AUDIT_ID_FIELD: "compatibility",
    COMPATIBILITY_SOURCE_FIELD: "compatibility",
    "Notes": "notes",
}

AUDITED_REQUIRED_FIELDS = [
    "Audit Date",
    "Auditor",
    "Plant/Area",
    "Press/Machine #",
    "Robot Type",
    "EOAT Type",
    "Status",
]
COMPATIBLE_REQUIRED_FIELDS = ["Press/Machine #", TOOL_FIELD]
IMPORTANT_FIELDS = [
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
]

MATERIAL_LIKE_VALUES = ("silicone", "rubber", "nitrile", "urethane", "polyurethane", "viton", "foam")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _value(entry_or_value: dict[str, Any] | Any, field_name: str) -> str:
    if isinstance(entry_or_value, dict):
        return normalize_text(entry_or_value.get(field_name))
    return normalize_text(entry_or_value)


def _is_no(value: Any) -> bool:
    return normalize_text(value).casefold() == "no"


def is_na_value(value: Any) -> bool:
    return normalize_text(value).upper() in {NA_VALUE, "NA", "NOT APPLICABLE"}


def is_meaningful_value(value: Any) -> bool:
    text = normalize_text(value)
    return (
        bool(text)
        and not is_na_value(text)
        and text.casefold() not in {"unknown / not checked", "unknown", "not checked"}
    )


def normalized_eoat_type(entry_or_value: dict[str, Any] | Any) -> str:
    text = _value(entry_or_value, "EOAT Type").casefold()
    if not text or is_na_value(text):
        return EOAT_TYPE_BLANK
    if text == "vacuum":
        return EOAT_TYPE_VACUUM
    if "hybrid" in text:
        return EOAT_TYPE_HYBRID
    if "mechanical" in text or "gripper" in text:
        return EOAT_TYPE_GRIPPER
    if text.startswith("unknown") or "needs review" in text:
        return EOAT_TYPE_UNKNOWN
    if "misc" in text or "custom" in text or "other" in text:
        return EOAT_TYPE_MISC
    return EOAT_TYPE_MISC


def eoat_type_uses_vacuum(entry_or_value: dict[str, Any] | Any) -> bool:
    return normalized_eoat_type(entry_or_value) in {EOAT_TYPE_VACUUM, EOAT_TYPE_HYBRID}


def eoat_type_uses_gripper(entry_or_value: dict[str, Any] | Any) -> bool:
    return normalized_eoat_type(entry_or_value) in {EOAT_TYPE_GRIPPER, EOAT_TYPE_HYBRID, EOAT_TYPE_MISC}


def is_unknown_or_review_eoat_type(entry_or_value: dict[str, Any] | Any) -> bool:
    return normalized_eoat_type(entry_or_value) in {EOAT_TYPE_UNKNOWN, EOAT_TYPE_BLANK}


def _broad_tooling_type(entry: dict[str, Any]) -> bool:
    return normalized_eoat_type(entry) in {EOAT_TYPE_UNKNOWN, EOAT_TYPE_MISC, EOAT_TYPE_BLANK}


def field_group(field_name: str) -> str:
    return FIELD_GROUPS.get(field_name, "notes")


def _entry_type(entry: dict[str, Any]) -> str:
    return normalize_text(entry.get(ENTRY_TYPE_FIELD)).casefold()


def field_applies(entry: dict[str, Any], field_name: str) -> bool:
    if _entry_type(entry) == ENTRY_TYPE_COMPATIBLE.casefold() and field_name in {"Audit Date", "Auditor"}:
        return False
    if field_name in VACUUM_TOOLING_FIELDS and not (_broad_tooling_type(entry) or eoat_type_uses_vacuum(entry)):
        return False
    if field_name in GRIPPER_TOOLING_FIELDS and not eoat_type_uses_gripper(entry):
        return False
    if field_name in SENSOR_DETAIL_FIELDS:
        if _is_no(entry.get("Sensors Present?")):
            return False
        if field_name == "Vacuum Confirmation Present?" and not (
            _broad_tooling_type(entry) or eoat_type_uses_vacuum(entry)
        ):
            return False
    if field_name in ELECTRICAL_DETAIL_FIELDS:
        if ELECTRICAL_WIRING_PRESENT_FIELD not in entry:
            return is_meaningful_value(entry.get(field_name))
        if _is_no(entry.get(ELECTRICAL_WIRING_PRESENT_FIELD)):
            return False
    if field_name in QUICK_DISCONNECT_DETAIL_FIELDS and _is_no(entry.get("Quick Disconnects Present?")):
        return False
    return True


def cylinder_section_in_use(entry: dict[str, Any]) -> bool:
    return is_meaningful_value(entry.get(CYLINDER_COUNT_FIELD))


def normalize_cylinder_fields(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(entry)
    if cylinder_section_in_use(normalized):
        cylinder_type = normalize_text(normalized.get(CYLINDER_TYPE_FIELD))
        if not cylinder_type or is_na_value(cylinder_type):
            normalized[CYLINDER_TYPE_FIELD] = CYLINDER_TYPE_DEFAULT
    else:
        cylinder_type = normalize_text(normalized.get(CYLINDER_TYPE_FIELD))
        if cylinder_type.casefold() == CYLINDER_TYPE_DEFAULT.casefold():
            normalized[CYLINDER_TYPE_FIELD] = ""
    return normalized


def cylinder_optional_reason() -> str:
    return "Cylinder section is blank/default; optional cylinder fields are ignored for completion."


def manual_completion_override_enabled(entry: dict[str, Any]) -> bool:
    return normalize_text(entry.get(MANUAL_COMPLETION_OVERRIDE_FIELD)).casefold() in {"yes", "true", "1", "y"}


def ignored_empty_fields_at_override(entry: dict[str, Any]) -> tuple[str, ...]:
    text = normalize_text(entry.get(IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD))
    if not text or is_na_value(text):
        return ()
    return tuple(field.strip() for field in text.replace("\n", ";").split(";") if field.strip())


def important_field_applies(entry: dict[str, Any], field_name: str) -> bool:
    if field_name == CUP_COUNT_FIELD:
        return field_applies(entry, field_name) and eoat_type_uses_vacuum(entry)
    return field_applies(entry, field_name)


def non_applicable_reason(entry: dict[str, Any], field_name: str) -> str:
    if field_applies(entry, field_name):
        return ""
    if _entry_type(entry) == ENTRY_TYPE_COMPATIBLE.casefold() and field_name in {"Audit Date", "Auditor"}:
        return "Compatibility rows are not physical audit observations."
    if field_name in VACUUM_TOOLING_FIELDS:
        return "Vacuum tooling fields do not apply to the selected EOAT type."
    if field_name in GRIPPER_TOOLING_FIELDS:
        return "Gripper tooling fields do not apply to the selected EOAT type."
    if field_name in SENSOR_DETAIL_FIELDS:
        return "Sensor detail fields do not apply when sensors are not present or not relevant."
    if field_name in ELECTRICAL_DETAIL_FIELDS:
        if ELECTRICAL_WIRING_PRESENT_FIELD not in entry:
            return "Electrical detail applicability is unknown until the workbook schema includes Electrical/Wiring Present?."
        return "Electrical detail fields do not apply when electrical/wiring is marked No."
    if field_name in QUICK_DISCONNECT_DETAIL_FIELDS:
        return "Quick disconnect detail fields do not apply when quick disconnects are marked No."
    return "Field does not apply to this row."


def applicable_fields(entry: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if field_applies(entry, field)]


def non_applicable_fields(entry: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if not field_applies(entry, field)]


def fields_to_clear_as_na(entry: dict[str, Any], fields: list[str]) -> dict[str, str]:
    return {field: non_applicable_reason(entry, field) for field in fields if not field_applies(entry, field)}


def _any_meaningful(entry: dict[str, Any], fields: set[str]) -> bool:
    return any(is_meaningful_value(entry.get(field)) for field in fields)


def hybrid_completeness_warnings(entry: dict[str, Any]) -> list[str]:
    if normalized_eoat_type(entry) != EOAT_TYPE_HYBRID:
        return []
    warnings: list[str] = []
    if not _any_meaningful(entry, VACUUM_TOOLING_FIELDS):
        warnings.append("Hybrid EOAT is missing vacuum-side tooling details.")
    if not _any_meaningful(entry, GRIPPER_TOOLING_FIELDS):
        warnings.append("Hybrid EOAT is missing gripper/mechanical-side tooling details.")
    return warnings


def semantic_consistency_warnings(entry: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    eoat_type = normalized_eoat_type(entry)
    gripper_type = normalize_text(entry.get(GRIPPER_TYPE_FIELD)).casefold()
    gripper_model = normalize_text(entry.get(GRIPPER_MODEL_FIELD)).casefold()
    cup_count = normalize_text(entry.get(CUP_COUNT_FIELD))
    cup_material = normalize_text(entry.get("Cup Type/Material"))
    if eoat_type == EOAT_TYPE_GRIPPER and "vacuum" in gripper_type:
        warnings.append("Mechanical / Gripper EOAT has Gripper Type that appears to be Vacuum.")
    if eoat_type == EOAT_TYPE_GRIPPER and _any_meaningful(entry, VACUUM_TOOLING_FIELDS):
        warnings.append("Mechanical / Gripper EOAT has meaningful vacuum-side field values.")
    if eoat_type == EOAT_TYPE_VACUUM and _any_meaningful(entry, GRIPPER_TOOLING_FIELDS):
        warnings.append("Vacuum EOAT has meaningful gripper/mechanical-side field values.")
    if gripper_model and any(material in gripper_model for material in MATERIAL_LIKE_VALUES):
        warnings.append(
            "Gripper Model appears to contain a material value; check whether it belongs in Cup Type/Material."
        )
    if eoat_type == EOAT_TYPE_GRIPPER and is_meaningful_value(cup_count):
        warnings.append(f"{CUP_COUNT_FIELD} contains a meaningful value on a Mechanical / Gripper row.")
    if eoat_type == EOAT_TYPE_GRIPPER and is_meaningful_value(cup_material):
        warnings.append("Cup Type/Material contains a meaningful value on a Mechanical / Gripper row.")
    if _is_no(entry.get("Sensors Present?")) and _any_meaningful(entry, SENSOR_DETAIL_FIELDS):
        warnings.append("Sensors Present? is No but sensor detail fields contain meaningful values.")
    if _is_no(entry.get("Quick Disconnects Present?")) and _any_meaningful(entry, QUICK_DISCONNECT_DETAIL_FIELDS):
        warnings.append(
            "Quick Disconnects Present? is No but quick disconnect detail fields contain meaningful values."
        )
    return warnings


def entry_type_requirements(entry: dict[str, Any]) -> dict[str, list[str]]:
    if _entry_type(entry) == ENTRY_TYPE_COMPATIBLE.casefold():
        required = [
            field
            for field in COMPATIBLE_REQUIRED_FIELDS
            if field not in AUTOFILLED_COMPATIBILITY_METADATA_FIELDS and (field in entry or field == TOOL_FIELD)
        ]
        return {
            "entry_type": ENTRY_TYPE_COMPATIBLE,
            "required": required,
            "important": [field for field in IMPORTANT_FIELDS if important_field_applies(entry, field)],
        }
    required = [field for field in AUDITED_REQUIRED_FIELDS if field in entry or field != TOOL_FIELD]
    return {
        "entry_type": ENTRY_TYPE_AUDITED,
        "required": required,
        "important": [field for field in IMPORTANT_FIELDS if important_field_applies(entry, field)],
    }
