from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from core.gripper_fields import CUP_COUNT_FIELD


@dataclass(frozen=True)
class SuggestedAnnotation:
    tag_name: str
    target_type: str
    field_key: str
    reason: str
    audit_id: str = ""
    machine_id: str = ""
    severity: str = "Warning"
    confidence: int = 80
    suggested_comment: str = ""
    current_value: str = ""
    data_fingerprint: str = ""
    suggestion_id: str = ""


def meaningful(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.upper() not in {"N/A", "NA"} and text.casefold() not in {"unknown", "unknown / not checked", "not applicable"}


def suggestion_fingerprint(*parts: Any) -> str:
    joined = "\u241f".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:20]


def make_suggestion(
    *,
    tag_name: str,
    target_type: str,
    field_key: str,
    reason: str,
    audit_id: str,
    machine_id: str,
    current_value: Any,
    severity: str = "Warning",
    confidence: int = 80,
    suggested_comment: str = "",
) -> SuggestedAnnotation:
    value_text = str(current_value or "").strip()
    data_fingerprint = suggestion_fingerprint(audit_id, field_key, tag_name, reason, value_text)
    return SuggestedAnnotation(
        tag_name=tag_name,
        target_type=target_type,
        field_key=field_key,
        audit_id=audit_id,
        machine_id=machine_id,
        reason=reason,
        severity=severity,
        confidence=confidence,
        suggested_comment=suggested_comment or reason,
        current_value=value_text,
        data_fingerprint=data_fingerprint,
        suggestion_id=f"sug_{data_fingerprint}",
    )


def suggested_annotations_for_audit(entry: dict[str, Any]) -> list[SuggestedAnnotation]:
    audit_id = str(entry.get("Audit ID") or "").strip()
    machine_id = str(entry.get("Press/Machine #") or "").strip()
    eoat_type = str(entry.get("EOAT Type") or "").casefold()
    suggestions: list[SuggestedAnnotation] = []
    if ("gripper" in eoat_type or "mechanical" in eoat_type) and meaningful(entry.get("Cup Type/Material")):
        suggestions.append(
            make_suggestion(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key="Cup Type/Material",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="EOAT Type is Mechanical / Gripper, but Cup Type/Material has a value.",
                severity="Error",
                confidence=95,
                current_value=entry.get("Cup Type/Material"),
            )
        )
    if ("gripper" in eoat_type or "mechanical" in eoat_type) and meaningful(entry.get(CUP_COUNT_FIELD)):
        suggestions.append(
            make_suggestion(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key=CUP_COUNT_FIELD,
                audit_id=audit_id,
                machine_id=machine_id,
                reason=f"EOAT Type is Mechanical / Gripper, but {CUP_COUNT_FIELD} has a value.",
                severity="Error",
                confidence=95,
                current_value=entry.get(CUP_COUNT_FIELD),
            )
        )
    if str(entry.get("Sensors Present?") or "").strip().casefold() == "no" and meaningful(entry.get("Sensor Type")):
        suggestions.append(
            make_suggestion(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key="Sensor Type",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="Sensors Present? is No, but Sensor Type is populated.",
                severity="Error",
                confidence=95,
                current_value=entry.get("Sensor Type"),
            )
        )
    if str(entry.get("Quick Disconnects Present?") or "").strip().casefold() == "no" and (
        meaningful(entry.get("Pneumatic Quick Disconnect Type")) or meaningful(entry.get("Electrical Quick Disconnect Type"))
    ):
        suggestions.append(
            make_suggestion(
                tag_name="Data Conflict",
                target_type="audit_field",
                field_key="Quick Disconnects Present?",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="Quick Disconnects Present? is No, but quick-disconnect detail fields are populated.",
                severity="Error",
                confidence=90,
                current_value=(
                    f"Pneumatic={entry.get('Pneumatic Quick Disconnect Type') or ''}; "
                    f"Electrical={entry.get('Electrical Quick Disconnect Type') or ''}"
                ),
            )
        )
    if str(entry.get("Photos Taken?") or "").strip().casefold() == "no" and str(entry.get("Priority") or "").strip().casefold() in {"high", "critical"}:
        suggestions.append(
            make_suggestion(
                tag_name="Missing Evidence",
                target_type="audit_field",
                field_key="Photos Taken?",
                audit_id=audit_id,
                machine_id=machine_id,
                reason="Photos Taken? is No on a high-priority audit.",
                severity="Warning",
                confidence=85,
                current_value=f"Photos Taken?={entry.get('Photos Taken?') or ''}; Priority={entry.get('Priority') or ''}",
            )
        )
    return suggestions
