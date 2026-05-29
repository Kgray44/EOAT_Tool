from __future__ import annotations

from typing import Any

from .audit.schema import (
    AUDIT_GROUP_LAYOUT,
    AUDIT_SECTION_LAYOUT,
    STORAGE_NONE,
    SYSTEM_METADATA_FIELDS,
    AuditFieldSpec,
    all_audit_fields,
    audit_section_groups,
    audit_sections,
    field_by_header,
)
from .audit.schema import (
    fields_for_section as schema_fields_for_section,
)
from .audit_field_rules import field_applies

METADATA_FIELDS = list(SYSTEM_METADATA_FIELDS)
PNEUMATIC_CIRCUITS_SECTION = "Pneumatic Circuits"


def audit_field_order(*, include_metadata: bool = False) -> list[str]:
    fields: list[str] = []
    for section_fields in AUDIT_SECTION_LAYOUT.values():
        fields.extend(section_fields)
    if include_metadata:
        fields.extend(field_name for field_name in METADATA_FIELDS if field_name not in fields)
    return fields


def audit_field_specs(*, include_metadata: bool = True) -> tuple[AuditFieldSpec, ...]:
    return tuple(
        spec
        for spec in all_audit_fields()
        if spec.storage_target != STORAGE_NONE and (include_metadata or spec.section != "System Metadata")
    )


def audit_field_registry(*, include_metadata: bool = True) -> dict[str, AuditFieldSpec]:
    return {spec.workbook_header: spec for spec in audit_field_specs(include_metadata=include_metadata)}


def get_audit_field_spec(field_name: str) -> AuditFieldSpec:
    try:
        return field_by_header(field_name)
    except KeyError:
        folded = str(field_name or "").strip().casefold()
        for spec in all_audit_fields():
            if spec.label.casefold() == folded or spec.field_id.casefold() == folded:
                return spec
    raise KeyError(field_name)


def section_for_field(field_name: str) -> str | None:
    try:
        return get_audit_field_spec(field_name).section
    except KeyError:
        return None


def fields_for_section(section_name: str) -> list[AuditFieldSpec]:
    return list(schema_fields_for_section(section_name))


def field_options(field_name: str) -> tuple[str, ...]:
    return get_audit_field_spec(field_name).dropdown_values


def fields_applicable_to_entry(entry: dict[str, Any], fields: list[str] | None = None) -> list[str]:
    candidates = fields if fields is not None else audit_field_order()
    return [field_name for field_name in candidates if field_applies(entry, field_name)]


__all__ = [
    "AUDIT_GROUP_LAYOUT",
    "AUDIT_SECTION_LAYOUT",
    "AuditFieldSpec",
    "METADATA_FIELDS",
    "PNEUMATIC_CIRCUITS_SECTION",
    "audit_field_order",
    "audit_field_registry",
    "audit_field_specs",
    "audit_section_groups",
    "audit_sections",
    "field_options",
    "fields_applicable_to_entry",
    "fields_for_section",
    "get_audit_field_spec",
    "section_for_field",
]
