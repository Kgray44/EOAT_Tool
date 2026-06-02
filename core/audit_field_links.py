from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, unquote


@dataclass(frozen=True)
class AuditFieldLink:
    audit_id: str = ""
    audit_key: str = ""
    machine_number: str = ""
    tool_number: str = ""
    field_key: str = ""
    field_label: str = ""
    page: str = "EOAT Audit"
    created_at: str = ""

    def target_dict(self) -> dict[str, object]:
        return {
            "target_type": "audit_field",
            "target_label": friendly_audit_field_label(self),
            "audit_id": self.audit_id,
            "machine_id": self.machine_number,
            "field_key": self.field_key,
            "field_label": self.field_label or self.field_key,
        }


def build_audit_field_link(
    audit_context: Mapping[str, Any],
    field_key: str,
    field_label: str | None = None,
    *,
    created_at: str | None = None,
) -> AuditFieldLink:
    return AuditFieldLink(
        audit_id=_text(audit_context.get("Audit ID") or audit_context.get("audit_id")),
        audit_key=_text(audit_context.get("audit_key")),
        machine_number=_text(audit_context.get("Press/Machine #") or audit_context.get("machine_number")),
        tool_number=_text(audit_context.get("Tool #") or audit_context.get("tool_number")),
        field_key=_text(field_key),
        field_label=_text(field_label) or _text(field_key),
        created_at=created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def serialize_audit_field_link(link: AuditFieldLink | Mapping[str, Any]) -> str:
    if isinstance(link, Mapping):
        link = AuditFieldLink(
            audit_id=_text(link.get("audit_id") or link.get("Audit ID")),
            audit_key=_text(link.get("audit_key")),
            machine_number=_text(link.get("machine_number") or link.get("machine") or link.get("Press/Machine #")),
            tool_number=_text(link.get("tool_number") or link.get("tool") or link.get("Tool #")),
            field_key=_text(link.get("field_key")),
            field_label=_text(link.get("field_label")),
            page=_text(link.get("page")) or "EOAT Audit",
            created_at=_text(link.get("created_at")),
        )
    pairs = {
        "audit_id": link.audit_id,
        "audit_key": link.audit_key,
        "machine": link.machine_number,
        "tool": link.tool_number,
        "field_key": link.field_key,
        "field_label": link.field_label,
        "page": link.page,
        "created_at": link.created_at,
    }
    return ";".join(f"{key}={quote(value, safe='')}" for key, value in pairs.items() if value)


def parse_audit_field_link(value: str | Mapping[str, Any] | AuditFieldLink | None) -> AuditFieldLink | None:
    if isinstance(value, AuditFieldLink):
        return value if value.field_key or value.field_label else None
    if isinstance(value, Mapping):
        link = serialize_audit_field_link(value)
        return parse_audit_field_link(link)
    text = _text(value)
    if not text or "=" not in text:
        return None
    data: dict[str, str] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        key = key.strip()
        if not key:
            continue
        data[key] = unquote(raw.strip())
    field_key = _text(data.get("field_key"))
    field_label = _text(data.get("field_label")) or field_key
    if not field_key and not field_label:
        return None
    return AuditFieldLink(
        audit_id=_text(data.get("audit_id")),
        audit_key=_text(data.get("audit_key")),
        machine_number=_text(data.get("machine")),
        tool_number=_text(data.get("tool")),
        field_key=field_key or field_label,
        field_label=field_label,
        page=_text(data.get("page")) or "EOAT Audit",
        created_at=_text(data.get("created_at")),
    )


def friendly_audit_field_label(link: AuditFieldLink | str | Mapping[str, Any] | None) -> str:
    parsed = parse_audit_field_link(link)
    if parsed is None:
        return ""
    parts = []
    if parsed.machine_number:
        parts.append(parsed.machine_number)
    if parsed.tool_number:
        parts.append(f"Tool {parsed.tool_number}")
    if parsed.field_label or parsed.field_key:
        parts.append(f"Field: {parsed.field_label or parsed.field_key}")
    if parsed.audit_id:
        parts.append(f"Audit {parsed.audit_id}")
    return " / ".join(parts)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
