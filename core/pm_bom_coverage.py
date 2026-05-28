from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .audit_field_rules import eoat_type_uses_gripper, is_meaningful_value
from .gripper_fields import GRIPPER_MODEL_FIELD
from .gripper_presets import is_known_gripper_preset
from .photo_evidence import evidence_coverage_for_audit


@dataclass(frozen=True)
class PmBomCoverage:
    audit_id: str
    machine: str
    spare_parts_info_missing: bool
    bom_available: bool
    gripper_preset_known: bool
    standard_parts_opportunities: tuple[str, ...]
    documentation_photo_evidence_missing: bool
    missing_documentation_fields: tuple[str, ...]
    missing_evidence_categories: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DOCUMENTATION_FIELDS = (
    "Spare Parts Identified?",
    "Drawing/CAD Available?",
    "BOM Available?",
    "Process Binder Complete?",
)


def is_spare_parts_info_missing(row: dict[str, Any]) -> bool:
    return _yes_no_value(row.get("Spare Parts Identified?")) != "yes"


def is_bom_available(row: dict[str, Any]) -> bool:
    return _yes_no_value(row.get("BOM Available?")) == "yes"


def is_gripper_preset_known_for_row(row: dict[str, Any], project_root: str | Path | None = None) -> bool:
    if not eoat_type_uses_gripper(row):
        return False
    return is_known_gripper_preset(row.get(GRIPPER_MODEL_FIELD), project_root)


def missing_documentation_fields(row: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in DOCUMENTATION_FIELDS:
        value = _yes_no_value(row.get(field))
        if value not in {"yes", "partial"}:
            missing.append(field)
    return missing


def standard_parts_opportunities(row: dict[str, Any], project_root: str | Path | None = None) -> list[str]:
    opportunities: list[str] = []
    if is_spare_parts_info_missing(row):
        opportunities.append("Document spare parts status before PM/BOM handoff.")
    if not is_bom_available(row):
        opportunities.append("Confirm whether an EOAT BOM exists or should be created.")
    if eoat_type_uses_gripper(row):
        model = _text(row.get(GRIPPER_MODEL_FIELD))
        if is_known_gripper_preset(model, project_root):
            opportunities.append(f"Use gripper preset reference for {model}.")
        elif is_meaningful_value(model):
            opportunities.append("Review whether this gripper model should become a managed preset.")
        else:
            opportunities.append("Capture gripper model before standardizing mechanical spare parts.")
    return opportunities


def is_documentation_photo_evidence_missing(project_root: str | Path, row: dict[str, Any]) -> bool:
    return bool(missing_documentation_fields(row) or missing_required_evidence_categories(project_root, row))


def missing_required_evidence_categories(project_root: str | Path, row: dict[str, Any]) -> list[str]:
    audit_id = _text(row.get("Audit ID"))
    if not audit_id:
        return []
    coverage = evidence_coverage_for_audit(project_root, audit_id, row=row)
    if coverage is None:
        return []
    return [status.category for status in coverage.statuses if status.required and not status.present]


def build_pm_bom_coverage(project_root: str | Path, row: dict[str, Any]) -> PmBomCoverage:
    missing_docs = tuple(missing_documentation_fields(row))
    missing_evidence = tuple(missing_required_evidence_categories(project_root, row))
    return PmBomCoverage(
        audit_id=_text(row.get("Audit ID")),
        machine=_text(row.get("Press/Machine #")),
        spare_parts_info_missing=is_spare_parts_info_missing(row),
        bom_available=is_bom_available(row),
        gripper_preset_known=is_gripper_preset_known_for_row(row, project_root),
        standard_parts_opportunities=tuple(standard_parts_opportunities(row, project_root)),
        documentation_photo_evidence_missing=bool(missing_docs or missing_evidence),
        missing_documentation_fields=missing_docs,
        missing_evidence_categories=missing_evidence,
    )


def _yes_no_value(value: Any) -> str:
    text = _text(value).casefold()
    if text in {"yes", "y", "true"}:
        return "yes"
    if text in {"partial", "partially"}:
        return "partial"
    if text in {"no", "n", "false"}:
        return "no"
    if text in {"unknown / not checked", "unknown", "not checked", ""}:
        return "unknown"
    return text


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "PmBomCoverage",
    "build_pm_bom_coverage",
    "is_bom_available",
    "is_documentation_photo_evidence_missing",
    "is_gripper_preset_known_for_row",
    "is_spare_parts_info_missing",
    "missing_documentation_fields",
    "missing_required_evidence_categories",
    "standard_parts_opportunities",
]
