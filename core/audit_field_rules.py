from __future__ import annotations

from typing import Any

from .audit_constants import (
    AIR_ARCHITECTURE_EXTERNAL_ONLY,
    AIR_ARCHITECTURE_MIXED,
    AIR_ARCHITECTURE_ROBOT_ONLY,
    AIR_CIRCUIT_ARCHITECTURE_FIELD,
    AUDIT_CONTEXT_FIELD,
    AUTOFILLED_COMPATIBILITY_METADATA_FIELDS,
    COMPATIBILITY_CONFIDENCE_FIELD,
    COMPATIBILITY_SOURCE_FIELD,
    CYLINDER_COUNT_FIELD,
    CYLINDER_TYPE_DEFAULT,
    CYLINDER_TYPE_FIELD,
    ENTRY_TYPE_AUDITED,
    ENTRY_TYPE_COMPATIBLE,
    ENTRY_TYPE_FIELD,
    EOAT_INTERCHANGEABLE_CIRCUITS_FIELD,
    EOAT_PNEUMATIC_FIELDS,
    EOAT_PRESSURE_CIRCUITS_FIELD,
    EOAT_VACUUM_CIRCUITS_FIELD,
    EXTERNAL_INTERCHANGEABLE_CIRCUITS_FIELD,
    EXTERNAL_PNEUMATIC_FIELDS,
    EXTERNAL_PRESSURE_CIRCUITS_FIELD,
    EXTERNAL_VACUUM_CIRCUITS_FIELD,
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    PHYSICAL_AUDIT_VERIFIED_FIELD,
    ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD,
    ROBOT_PNEUMATIC_FIELDS,
    ROBOT_PRESSURE_CIRCUITS_FIELD,
    ROBOT_VACUUM_CIRCUITS_FIELD,
    SOURCE_AUDIT_ID_FIELD,
    air_architecture_hides_external_fields,
    air_architecture_hides_robot_fields,
    machine_uses_mixed_air_architecture,
)
from .audit_context import MACHINE_CONTEXT_FIELDS, infer_audit_context, is_bench_audit_context
from .eoat_ids import EOAT_ASSEMBLY_ID_FIELD
from .gripper_fields import (
    CUP_COUNT_FIELD,
    GRIPPER_COUNT_FIELD,
    GRIPPER_MODEL_FIELD,
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
    *EOAT_PNEUMATIC_FIELDS,
    *ROBOT_PNEUMATIC_FIELDS,
    *EXTERNAL_PNEUMATIC_FIELDS,
}
GRIPPER_TOOLING_FIELDS = {GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD}
SENSOR_DETAIL_FIELDS = {
    "Sensor Type",
    "Sensor Brand/Model",
    "Vacuum Confirmation Present?",
    "Part-Present Detection Present?",
}
ELECTRICAL_WIRING_PRESENT_FIELD = "Electrical/Wiring Present?"
ELECTRICAL_DETAIL_FIELDS = {"Electrical Quick Disconnect Type", "Cable Management Condition"}
QUICK_DISCONNECT_DETAIL_FIELDS = {"Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"}
SPECIALTY_GRIPPER_MODEL_ALLOWLIST = {
    "AUD-20260604-009": {"silicone od"},
    "AUD-20260604-007": {"silicone od"},
}

FIELD_GROUPS = {
    "Audit ID": "header",
    "Audit Date": "header",
    "Auditor": "header",
    "Entry Type": "header",
    "Plant/Area": "machine_context",
    "Press/Machine #": "machine_context",
    TOOL_FIELD: "machine_context",
    EOAT_ASSEMBLY_ID_FIELD: "machine_context",
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
    "Sensors Present?": "sensor",
    "Sensor Type": "sensor",
    "Sensor Brand/Model": "sensor",
    "Vacuum Confirmation Present?": "sensor",
    "Part-Present Detection Present?": "sensor",
    ELECTRICAL_WIRING_PRESENT_FIELD: "electrical",
    "Quick Disconnects Present?": "quick_disconnect",
    "Pneumatic Quick Disconnect Type": "pneumatic",
    AIR_CIRCUIT_ARCHITECTURE_FIELD: "pneumatic_circuit",
    EOAT_VACUUM_CIRCUITS_FIELD: "pneumatic_circuit",
    EOAT_PRESSURE_CIRCUITS_FIELD: "pneumatic_circuit",
    EOAT_INTERCHANGEABLE_CIRCUITS_FIELD: "pneumatic_circuit",
    ROBOT_VACUUM_CIRCUITS_FIELD: "pneumatic_circuit",
    ROBOT_PRESSURE_CIRCUITS_FIELD: "pneumatic_circuit",
    ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD: "pneumatic_circuit",
    EXTERNAL_VACUUM_CIRCUITS_FIELD: "pneumatic_circuit",
    EXTERNAL_PRESSURE_CIRCUITS_FIELD: "pneumatic_circuit",
    EXTERNAL_INTERCHANGEABLE_CIRCUITS_FIELD: "pneumatic_circuit",
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
    AUDIT_CONTEXT_FIELD: "audit_context",
    SOURCE_AUDIT_ID_FIELD: "compatibility",
    COMPATIBILITY_SOURCE_FIELD: "compatibility",
    PHYSICAL_AUDIT_VERIFIED_FIELD: "compatibility",
    COMPATIBILITY_CONFIDENCE_FIELD: "compatibility",
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
        and text.casefold()
        not in {
            "unknown / not checked",
            "unknown",
            "not checked",
            "not observable",
            "follow-up required",
            "follow up required",
        }
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
    architecture = entry.get(AIR_CIRCUIT_ARCHITECTURE_FIELD)
    if field_name in ROBOT_PNEUMATIC_FIELDS and air_architecture_hides_robot_fields(architecture):
        return False
    if field_name in EXTERNAL_PNEUMATIC_FIELDS and air_architecture_hides_external_fields(architecture):
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
    if field_name in ROBOT_PNEUMATIC_FIELDS:
        return "Robot-supplied circuit fields do not apply when air architecture is External Peripheral Only."
    if field_name in EXTERNAL_PNEUMATIC_FIELDS:
        return "External peripheral IO circuit fields do not apply when air architecture is Robot Only."
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
    if (
        gripper_model
        and any(material in gripper_model for material in MATERIAL_LIKE_VALUES)
        and not _allowed_specialty_gripper_model(entry, gripper_model)
    ):
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
    warnings.extend(air_architecture_warnings(entry))
    return warnings


def _allowed_specialty_gripper_model(entry: dict[str, Any], gripper_model: str) -> bool:
    audit_id = normalize_text(entry.get("Audit ID"))
    return gripper_model in SPECIALTY_GRIPPER_MODEL_ALLOWLIST.get(audit_id, set())


def air_architecture_warnings(entry: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    architecture = normalize_text(entry.get(AIR_CIRCUIT_ARCHITECTURE_FIELD))
    if not architecture or is_na_value(architecture):
        warnings.append(f"{AIR_CIRCUIT_ARCHITECTURE_FIELD} is blank.")
    if architecture == AIR_ARCHITECTURE_ROBOT_ONLY and any(
        _is_real_circuit_value(entry.get(field)) for field in EXTERNAL_PNEUMATIC_FIELDS
    ):
        warnings.append("Robot Only architecture selected, but external circuit fields contain values.")
    if architecture == AIR_ARCHITECTURE_EXTERNAL_ONLY and any(
        _is_real_circuit_value(entry.get(field)) for field in ROBOT_PNEUMATIC_FIELDS
    ):
        warnings.append("External Peripheral Only architecture selected, but robot-supplied circuit fields contain values.")
    if architecture == AIR_ARCHITECTURE_MIXED and not any(
        _is_real_circuit_value(entry.get(field)) for field in EXTERNAL_PNEUMATIC_FIELDS
    ):
        warnings.append("Mixed air architecture selected, but no external circuit count appears to be documented.")
    if machine_uses_mixed_air_architecture(entry.get("Press/Machine #")) and architecture != AIR_ARCHITECTURE_MIXED:
        warnings.append(
            "This Cleanroom machine is expected to use Mixed Robot + External Peripheral air architecture unless verified otherwise."
        )
    warnings.extend(_air_circuit_count_consistency_warnings(entry))
    return warnings


def _is_real_circuit_value(value: Any) -> bool:
    text = normalize_text(value)
    if not text or is_na_value(text):
        return False
    folded = text.casefold()
    if folded in {
        "unknown / not checked",
        "unknown / needs verification",
        "unknown",
        "not checked",
        "needs verification",
        "not applicable",
    }:
        return False
    parsed = _numeric_circuit_value(text)
    if parsed is not None:
        return parsed > 0
    return True


def _numeric_circuit_value(value: Any) -> int | None:
    text = normalize_text(value)
    if not text or is_na_value(text):
        return None
    if text.endswith(".0"):
        text = text[:-2]
    try:
        parsed = int(text)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _air_circuit_count_consistency_warnings(entry: dict[str, Any]) -> list[str]:
    checks = (
        ("Pressure", EOAT_PRESSURE_CIRCUITS_FIELD, ROBOT_PRESSURE_CIRCUITS_FIELD, EXTERNAL_PRESSURE_CIRCUITS_FIELD),
        ("Vacuum", EOAT_VACUUM_CIRCUITS_FIELD, ROBOT_VACUUM_CIRCUITS_FIELD, EXTERNAL_VACUUM_CIRCUITS_FIELD),
        (
            "Interchangeable",
            EOAT_INTERCHANGEABLE_CIRCUITS_FIELD,
            ROBOT_INTERCHANGEABLE_CIRCUITS_FIELD,
            EXTERNAL_INTERCHANGEABLE_CIRCUITS_FIELD,
        ),
    )
    warnings: list[str] = []
    for label, eoat_field, robot_field, external_field in checks:
        eoat_count = _numeric_circuit_value(entry.get(eoat_field))
        robot_count = _numeric_circuit_value(entry.get(robot_field))
        external_count = _numeric_circuit_value(entry.get(external_field))
        if eoat_count is None or robot_count is None or external_count is None:
            continue
        source_count = robot_count + external_count
        if eoat_count != source_count:
            warnings.append(
                f"{label} circuit mismatch: EOAT total is {eoat_count}, but robot + external source count is {source_count}."
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
            "audit_context": infer_audit_context(entry),
            "required": required,
            "important": [field for field in IMPORTANT_FIELDS if important_field_applies(entry, field)],
        }
    ignored_fields = MACHINE_CONTEXT_FIELDS if is_bench_audit_context(entry) else frozenset()
    required = [
        field
        for field in AUDITED_REQUIRED_FIELDS
        if field not in ignored_fields and (field in entry or field != TOOL_FIELD)
    ]
    return {
        "entry_type": ENTRY_TYPE_AUDITED,
        "audit_context": infer_audit_context(entry),
        "required": required,
        "important": [
            field for field in IMPORTANT_FIELDS if field not in ignored_fields and important_field_applies(entry, field)
        ],
    }
