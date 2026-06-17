from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .audit_constants import CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD, ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from .audit_field_rules import (
    EOAT_TYPE_GRIPPER,
    EOAT_TYPE_HYBRID,
    EOAT_TYPE_VACUUM,
    cylinder_section_in_use,
    eoat_type_uses_gripper,
    eoat_type_uses_vacuum,
    is_meaningful_value,
    normalized_eoat_type,
)

RulePredicate = Callable[[dict[str, Any]], bool]

ROBOT_PNEUMATIC_CIRCUIT_FIELDS = (
    "Robot Vacuum Circuits",
    "Robot Pressure Circuits",
    "Robot Interchangeable Circuits",
)
EOAT_PNEUMATIC_CIRCUIT_FIELDS = (
    "EOAT Vacuum Circuits",
    "EOAT Pressure Circuits",
    "EOAT Interchangeable Circuits",
)


@dataclass(frozen=True)
class PhotoEvidenceRule:
    key: str
    label: str
    example_filename_prefix: str
    applies: RulePredicate
    required: RulePredicate
    recommended: RulePredicate
    help_text: str = ""
    aliases: tuple[str, ...] = ()
    linked_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("applies", None)
        data.pop("required", None)
        data.pop("recommended", None)
        return data


def _physical_audit(row: dict[str, Any]) -> bool:
    return _text(row.get(ENTRY_TYPE_FIELD)).casefold() != ENTRY_TYPE_COMPATIBLE.casefold()


def _physical_and(predicate: RulePredicate) -> RulePredicate:
    return lambda row: _physical_audit(row) and predicate(row)


def _any_physical(row: dict[str, Any]) -> bool:
    return _physical_audit(row)


def _complete_or_pilot(row: dict[str, Any]) -> bool:
    if not _physical_audit(row):
        return False
    status = _text(row.get("Status")).casefold()
    pilot = _text(row.get("Pilot Candidate?")).casefold()
    return status in {"complete", "audited"} or pilot in {"yes", "maybe", "candidate for pilot"}


def _vacuum_type(row: dict[str, Any]) -> bool:
    return eoat_type_uses_vacuum(row)


def _gripper_required_type(row: dict[str, Any]) -> bool:
    return normalized_eoat_type(row) in {EOAT_TYPE_GRIPPER, EOAT_TYPE_HYBRID}


def _broad_tooling_type(row: dict[str, Any]) -> bool:
    return normalized_eoat_type(row) not in {EOAT_TYPE_VACUUM, EOAT_TYPE_GRIPPER, EOAT_TYPE_HYBRID}


def _sensor_applies(row: dict[str, Any]) -> bool:
    return _is_yes_or_partial(row.get("Sensors Present?")) or _any_meaningful(
        row,
        ("Sensor Type", "Sensor Brand/Model", "Vacuum Confirmation Present?", "Part-Present Detection Present?"),
    )


def _quick_disconnect_applies(row: dict[str, Any]) -> bool:
    return _is_yes_or_partial(row.get("Quick Disconnects Present?")) or _any_meaningful(
        row,
        ("Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"),
    )


def _cable_applies(row: dict[str, Any]) -> bool:
    return _is_yes_or_partial(row.get("Electrical/Wiring Present?")) or is_meaningful_value(
        row.get("Cable Management Condition")
    )


def _pneumatic_or_tooling_applies(row: dict[str, Any]) -> bool:
    return (
        _any_pneumatic_circuit_count(row)
        or eoat_type_uses_vacuum(row)
        or eoat_type_uses_gripper(row)
        or is_meaningful_value(row.get("Tubing Condition"))
    )


def _any_pneumatic_circuit_count(row: dict[str, Any]) -> bool:
    return _robot_pneumatic_applies(row) or _eoat_pneumatic_applies(row)


def _robot_pneumatic_applies(row: dict[str, Any]) -> bool:
    return _any_positive_or_text_count(row, ROBOT_PNEUMATIC_CIRCUIT_FIELDS)


def _eoat_pneumatic_applies(row: dict[str, Any]) -> bool:
    return _any_positive_or_text_count(row, EOAT_PNEUMATIC_CIRCUIT_FIELDS)


def _documentation_applies(row: dict[str, Any]) -> bool:
    return _any_meaningful(
        row, ("Process Binder Complete?", "Drawing/CAD Available?", "BOM Available?", "Photo Folder/Link")
    )


def _has_issue_or_damage(row: dict[str, Any]) -> bool:
    condition_fields = (
        "Drop/Mis-Pick History",
        "Tubing Condition",
        "Cable Management Condition",
        "Mounting Hardware Condition",
        "EOAT Alignment Condition",
    )
    bad_tokens = (
        "worn",
        "wear",
        "damage",
        "damaged",
        "poor",
        "loose",
        "missing",
        "misaligned",
        "leak",
        "follow-up",
        "follow up",
        "issue",
    )
    return _has_meaningful_issue(row) or any(
        any(token in _text(row.get(field)).casefold() for token in bad_tokens) for field in condition_fields
    )


def _has_meaningful_issue(row: dict[str, Any]) -> bool:
    issue = _text(row.get("Known Issues")).casefold()
    if not issue:
        return False
    return issue not in {
        "none",
        "no",
        "n/a",
        "na",
        "no issue observed.",
        "no issues observed",
        "unknown / not checked",
        "unknown",
    }


def _any_meaningful(row: dict[str, Any], fields: Iterable[str]) -> bool:
    return any(is_meaningful_value(row.get(field)) for field in fields)


def _any_positive_or_text_count(row: dict[str, Any], fields: Iterable[str]) -> bool:
    for field in fields:
        value = row.get(field)
        if not is_meaningful_value(value):
            continue
        text = _text(value)
        try:
            if float(text) > 0:
                return True
        except ValueError:
            return True
    return False


def _is_yes(value: Any) -> bool:
    return _text(value).casefold() == "yes"


def _is_yes_or_partial(value: Any) -> bool:
    return _text(value).casefold() in {"yes", "partial"}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


PHOTO_EVIDENCE_RULES: tuple[PhotoEvidenceRule, ...] = (
    PhotoEvidenceRule(
        "overall_eoat",
        "Front View",
        "FrontView",
        applies=_any_physical,
        required=_complete_or_pilot,
        recommended=_any_physical,
        help_text="Front context photo for the complete EOAT assembly.",
        aliases=("front view", "frontview", "front", "overall", "overall eoat", "eoat overall"),
        linked_fields=("EOAT Type", "Status"),
    ),
    PhotoEvidenceRule(
        "robot_connection",
        "Tool Connection",
        "ToolConnection",
        applies=_any_physical,
        required=_complete_or_pilot,
        recommended=_any_physical,
        help_text="Robot/tool connection or changeover interface.",
        aliases=("tool connection", "robot connection", "robot", "connection", "ati", "dovetail"),
        linked_fields=("Connection Type",),
    ),
    PhotoEvidenceRule(
        "vacuum_cups",
        "Vacuum Cups",
        "VacuumCups",
        applies=_physical_and(_vacuum_type),
        required=_physical_and(lambda row: _complete_or_pilot(row) and _vacuum_type(row)),
        recommended=_physical_and(_vacuum_type),
        help_text="Required for vacuum and hybrid EOAT rows.",
        aliases=("vacuum cup", "vacuum cups", "vacuum", "cups", "vacuum cups / grippers", "vacuum_cups_grippers"),
        linked_fields=("# of Cups", "Cup Type/Material", "Cup Diameter/Size"),
    ),
    PhotoEvidenceRule(
        "grippers",
        "Grippers",
        "Grippers",
        applies=_physical_and(_gripper_required_type),
        required=_physical_and(lambda row: _complete_or_pilot(row) and _gripper_required_type(row)),
        recommended=_physical_and(_gripper_required_type),
        help_text="Required for mechanical/gripper and hybrid EOAT rows.",
        aliases=("gripper", "grippers", "jaw", "finger", "vacuum cups / grippers", "vacuum_cups_grippers"),
        linked_fields=("# of Grippers", "Gripper Type", "Gripper Model"),
    ),
    PhotoEvidenceRule(
        "cylinders",
        "Cylinders",
        "Cylinders",
        applies=_physical_and(cylinder_section_in_use),
        required=_physical_and(cylinder_section_in_use),
        recommended=_physical_and(cylinder_section_in_use),
        help_text=f"Required when {CYLINDER_COUNT_FIELD} is populated.",
        aliases=("cylinder", "cylinders", "linear cylinder", "rotary cylinder", "actuator"),
        linked_fields=(CYLINDER_COUNT_FIELD, CYLINDER_TYPE_FIELD),
    ),
    PhotoEvidenceRule(
        "sensors",
        "Sensor Mounting",
        "SensorMounting",
        applies=_physical_and(_sensor_applies),
        required=_physical_and(lambda row: _is_yes(row.get("Sensors Present?"))),
        recommended=_physical_and(_sensor_applies),
        help_text="Required when Sensors Present? is Yes.",
        aliases=("sensor", "sensors", "sensor mounting", "sensor_mounting"),
        linked_fields=(
            "Sensors Present?",
            "Sensor Type",
            "Sensor Brand/Model",
            "Vacuum Confirmation Present?",
            "Part-Present Detection Present?",
        ),
    ),
    PhotoEvidenceRule(
        "tubing_routing",
        "Tubing Routing",
        "TubingRouting",
        applies=_physical_and(_pneumatic_or_tooling_applies),
        required=_physical_and(_any_pneumatic_circuit_count),
        recommended=_physical_and(_pneumatic_or_tooling_applies),
        help_text="Required when pneumatic circuit counts are populated.",
        aliases=("tubing", "routing", "tubing routing", "pneumatic routing"),
        linked_fields=("Tubing Condition", "Tubing Routing Notes"),
    ),
    PhotoEvidenceRule(
        "quick_disconnects",
        "Quick Disconnects",
        "QuickDisconnects",
        applies=_physical_and(_quick_disconnect_applies),
        required=_physical_and(lambda row: _is_yes(row.get("Quick Disconnects Present?"))),
        recommended=_physical_and(_quick_disconnect_applies),
        help_text="Required when Quick Disconnects Present? is Yes.",
        aliases=("quick disconnect", "quick disconnects", "quick_disconnect", "quickdisconnect"),
        linked_fields=(
            "Quick Disconnects Present?",
            "Pneumatic Quick Disconnect Type",
            "Electrical Quick Disconnect Type",
        ),
    ),
    PhotoEvidenceRule(
        "cable_management",
        "Cable Management",
        "CableManagement",
        applies=_physical_and(_cable_applies),
        required=_physical_and(lambda row: _is_yes(row.get("Electrical/Wiring Present?"))),
        recommended=_physical_and(_cable_applies),
        help_text="Required when Electrical/Wiring Present? is Yes.",
        aliases=("cable", "cable management", "wiring", "electrical"),
        linked_fields=("Electrical/Wiring Present?", "Cable Management Condition", "Electrical Quick Disconnect Type"),
    ),
    PhotoEvidenceRule(
        "robot_side_pneumatics",
        "Robot-Side Pneumatics",
        "RobotSidePneumatics",
        applies=_physical_and(_robot_pneumatic_applies),
        required=_physical_and(_robot_pneumatic_applies),
        recommended=_physical_and(_robot_pneumatic_applies),
        help_text="Required when robot-side pneumatic circuit counts are populated.",
        aliases=(
            "robot-side pneumatic",
            "robot side pneumatic",
            "robot pneumatics",
            "robot circuits",
            "robot-side pneumatics",
        ),
        linked_fields=ROBOT_PNEUMATIC_CIRCUIT_FIELDS,
    ),
    PhotoEvidenceRule(
        "eoat_pneumatic_circuits",
        "EOAT-Side Pneumatics",
        "EOATSidePneumatics",
        applies=_physical_and(
            lambda row: _eoat_pneumatic_applies(row) or eoat_type_uses_vacuum(row) or _gripper_required_type(row)
        ),
        required=_physical_and(_eoat_pneumatic_applies),
        recommended=_physical_and(
            lambda row: _eoat_pneumatic_applies(row) or eoat_type_uses_vacuum(row) or _gripper_required_type(row)
        ),
        help_text="Required when EOAT-side pneumatic circuit counts are populated.",
        aliases=(
            "eoat-side pneumatic",
            "eoat side pneumatic",
            "eoat pneumatics",
            "pneumatic circuit",
            "pneumatic",
            "circuits",
            "eoat-side pneumatics",
        ),
        linked_fields=EOAT_PNEUMATIC_CIRCUIT_FIELDS,
    ),
    PhotoEvidenceRule(
        "wear_damage",
        "Wear/Damage",
        "WearDamage",
        applies=_any_physical,
        required=_physical_and(_has_issue_or_damage),
        recommended=_any_physical,
        help_text="Required when issues, wear, damage, poor routing, or loose hardware are documented.",
        aliases=("wear", "damage", "wear / damage", "wear_damage", "wear/damage"),
        linked_fields=(
            "Known Issues",
            "Drop/Mis-Pick History",
            "Tubing Condition",
            "Cable Management Condition",
            "Mounting Hardware Condition",
        ),
    ),
    PhotoEvidenceRule(
        "tool_label_id_plate",
        "Tool Label / ID Plate",
        "ToolLabelIDPlate",
        applies=_any_physical,
        required=_complete_or_pilot,
        recommended=_any_physical,
        help_text="Tool label, ID plate, or identifying marker.",
        aliases=("tool label", "id plate", "label", "nameplate", "tool id", "id plate"),
        linked_fields=("Tool #", "Part Name/Description"),
    ),
    PhotoEvidenceRule(
        "process_binder_reference",
        "Process Binder/Documentation Reference",
        "ProcessBinderReference",
        applies=_physical_and(_documentation_applies),
        required=_physical_and(lambda row: _is_yes(row.get("Process Binder Complete?"))),
        recommended=_physical_and(_documentation_applies),
        help_text="Documentation or process binder reference evidence.",
        aliases=("process binder", "binder", "documentation", "reference", "process binder reference"),
        linked_fields=("Process Binder Complete?", "Drawing/CAD Available?", "BOM Available?", "Photo Folder/Link"),
    ),
    PhotoEvidenceRule(
        "other",
        "Other",
        "Other",
        applies=_any_physical,
        required=lambda _row: False,
        recommended=lambda _row: False,
        help_text="Optional catch-all for useful evidence that does not fit another shot type.",
        aliases=("other", "misc", "miscellaneous"),
        linked_fields=("Notes",),
    ),
    PhotoEvidenceRule(
        "mounting_hardware",
        "Mounting Hardware",
        "MountingHardware",
        applies=_any_physical,
        required=_complete_or_pilot,
        recommended=_any_physical,
        help_text="Legacy evidence category retained for existing indexed photos and checklists.",
        aliases=("mounting", "hardware", "mounting hardware"),
        linked_fields=("Mounting Hardware Condition", "Fastener/Locking Hardware Present?", "EOAT Alignment Condition"),
    ),
)


def all_photo_evidence_rules() -> list[PhotoEvidenceRule]:
    return list(PHOTO_EVIDENCE_RULES)


def photo_evidence_rule_by_key(key: str) -> PhotoEvidenceRule:
    target = _normalize_key(key)
    for rule in PHOTO_EVIDENCE_RULES:
        candidates = {rule.key, rule.label, *rule.aliases}
        if target in {_normalize_key(candidate) for candidate in candidates}:
            return rule
    raise KeyError(key)


def rule_by_key(key: str) -> PhotoEvidenceRule:
    return photo_evidence_rule_by_key(key)


def applicable_photo_evidence_rules(row: dict[str, Any]) -> list[PhotoEvidenceRule]:
    return [rule for rule in PHOTO_EVIDENCE_RULES if rule.applies(row)]


def required_photo_evidence_rules(row: dict[str, Any]) -> list[PhotoEvidenceRule]:
    return [rule for rule in PHOTO_EVIDENCE_RULES if rule.applies(row) and rule.required(row)]


def applicable_photo_evidence_types(row: dict[str, Any]) -> list[PhotoEvidenceRule]:
    return applicable_photo_evidence_rules(row)


def required_photo_evidence_types(row: dict[str, Any]) -> list[PhotoEvidenceRule]:
    return required_photo_evidence_rules(row)


def photo_evidence_labels_required_for(row: dict[str, Any]) -> list[str]:
    return [rule.label for rule in required_photo_evidence_rules(row)]


def photo_evidence_aliases() -> dict[str, tuple[str, ...]]:
    return {rule.key: rule.aliases for rule in PHOTO_EVIDENCE_RULES}


def _normalize_key(value: str) -> str:
    return _text(value).replace("_", " ").replace("-", " ").casefold()


__all__ = [
    "EOAT_PNEUMATIC_CIRCUIT_FIELDS",
    "PHOTO_EVIDENCE_RULES",
    "PhotoEvidenceRule",
    "ROBOT_PNEUMATIC_CIRCUIT_FIELDS",
    "all_photo_evidence_rules",
    "applicable_photo_evidence_rules",
    "applicable_photo_evidence_types",
    "photo_evidence_aliases",
    "photo_evidence_labels_required_for",
    "photo_evidence_rule_by_key",
    "required_photo_evidence_rules",
    "required_photo_evidence_types",
    "rule_by_key",
]
