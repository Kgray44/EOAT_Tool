from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SuggestedAnnotation:
    tag_name: str
    target_type: str
    field_key: str
    reason: str
    audit_id: str = ""
    machine_id: str = ""


def meaningful(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.upper() not in {"N/A", "NA"} and text.casefold() not in {"unknown", "unknown / not checked", "not applicable"}


def suggested_annotations_for_audit(entry: dict[str, Any]) -> list[SuggestedAnnotation]:
    audit_id = str(entry.get("Audit ID") or "").strip()
    machine_id = str(entry.get("Press/Machine #") or "").strip()
    eoat_type = str(entry.get("EOAT Type") or "").casefold()
    suggestions: list[SuggestedAnnotation] = []
    if ("gripper" in eoat_type or "mechanical" in eoat_type) and meaningful(entry.get("Cup Type/Material")):
        suggestions.append(
            SuggestedAnnotation(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key="Cup Type/Material",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="EOAT Type is Mechanical / Gripper, but Cup Type/Material has a value.",
            )
        )
    if str(entry.get("Sensors Present?") or "").strip().casefold() == "no" and meaningful(entry.get("Sensor Type")):
        suggestions.append(
            SuggestedAnnotation(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key="Sensor Type",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="Sensors Present? is No, but Sensor Type is populated.",
            )
        )
    if str(entry.get("Quick Disconnects Present?") or "").strip().casefold() == "no" and (
        meaningful(entry.get("Pneumatic Quick Disconnect Type")) or meaningful(entry.get("Electrical Quick Disconnect Type"))
    ):
        suggestions.append(
            SuggestedAnnotation(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key="Quick Disconnects Present?",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="Quick Disconnects Present? is No, but quick-disconnect detail fields are populated.",
            )
        )
    if str(entry.get("Photos Taken?") or "").strip().casefold() == "no" and str(entry.get("Priority") or "").strip().casefold() in {"high", "critical"}:
        suggestions.append(
            SuggestedAnnotation(
                tag_name="Missing Evidence",
                target_type="audit_field",
                field_key="Photos Taken?",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="Photos Taken? is No on a high-priority audit.",
            )
        )
    return suggestions
