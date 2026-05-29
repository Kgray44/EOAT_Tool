from __future__ import annotations

import hashlib
import json
from typing import Any

TARGET_TYPES = {
    "audit",
    "audit_field",
    "machine",
    "note",
    "compatibility_entry",
    "photo",
    "workbook_warning",
    "pilot_candidate",
    "project_item",
}


def normalize_target_type(target_type: str) -> str:
    normalized = (target_type or "").strip().lower().replace(" ", "_").replace("-", "_")
    if normalized not in TARGET_TYPES:
        raise ValueError(f"Unsupported annotation target type: {target_type}")
    return normalized


def target_identity_payload(
    *,
    target_type: str,
    audit_id: str = "",
    machine_id: str = "",
    field_key: str = "",
    object_ref: str = "",
) -> dict[str, str]:
    normalized_type = normalize_target_type(target_type)
    payload = {
        "target_type": normalized_type,
        "audit_id": str(audit_id or "").strip(),
        "machine_id": str(machine_id or "").strip(),
        "field_key": str(field_key or "").strip(),
        "object_ref": str(object_ref or "").strip(),
    }
    if normalized_type == "audit" and not payload["object_ref"]:
        payload["object_ref"] = payload["audit_id"]
    if normalized_type == "audit_field" and not payload["object_ref"]:
        payload["machine_id"] = ""
        payload["object_ref"] = f"{payload['audit_id']}::{payload['field_key']}"
    if normalized_type == "machine" and not payload["object_ref"]:
        payload["object_ref"] = payload["machine_id"]
    return payload


def target_id_for(**kwargs: Any) -> str:
    payload = target_identity_payload(**kwargs)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha1(encoded).hexdigest()[:24]
    return f"target_{digest}"


def display_label_for_target(
    *,
    target_type: str,
    target_label: str = "",
    audit_id: str = "",
    machine_id: str = "",
    field_label: str = "",
    field_key: str = "",
    object_ref: str = "",
) -> str:
    if target_label:
        return target_label
    normalized_type = normalize_target_type(target_type)
    if normalized_type == "audit_field":
        pieces = [audit_id, field_label or field_key]
        return " / ".join(piece for piece in pieces if piece)
    if normalized_type == "audit":
        return audit_id or object_ref or "Audit"
    if normalized_type == "machine":
        return f"Machine {machine_id}" if machine_id else "Machine"
    return object_ref or normalized_type.replace("_", " ").title()
