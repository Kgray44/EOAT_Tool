from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .paths import resolve_project_paths
from .safe_files import ensure_directory, safe_write_text


class ValidationSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    AUTO_FIXABLE = "AUTO_FIXABLE"


SEVERITY_ORDER = {
    ValidationSeverity.BLOCKER.value: 0,
    ValidationSeverity.ERROR.value: 1,
    ValidationSeverity.AUTO_FIXABLE.value: 2,
    ValidationSeverity.WARNING.value: 3,
    ValidationSeverity.INFO.value: 4,
}


@dataclass(frozen=True)
class ValidationFinding:
    finding_id: str
    severity: str
    category: str
    sheet_name: str = ""
    row_number: int | None = None
    column_name: str = ""
    audit_id: str = ""
    machine_number: str = ""
    message: str = ""
    current_value: str = ""
    expected_behavior: str = ""
    recommended_action: str = ""
    fix_available: bool = False
    fix_id: str = ""
    source_validator: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "severity", normalize_severity(self.severity))
        if not self.finding_id:
            object.__setattr__(self, "finding_id", stable_finding_id(self))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidationFinding":
        return cls(
            finding_id=str(data.get("finding_id") or ""),
            severity=str(data.get("severity") or ValidationSeverity.WARNING.value),
            category=str(data.get("category") or ""),
            sheet_name=str(data.get("sheet_name") or ""),
            row_number=_row_number(data.get("row_number")),
            column_name=str(data.get("column_name") or ""),
            audit_id=str(data.get("audit_id") or ""),
            machine_number=str(data.get("machine_number") or ""),
            message=str(data.get("message") or ""),
            current_value=str(data.get("current_value") or ""),
            expected_behavior=str(data.get("expected_behavior") or ""),
            recommended_action=str(data.get("recommended_action") or ""),
            fix_available=bool(data.get("fix_available")),
            fix_id=str(data.get("fix_id") or ""),
            source_validator=str(data.get("source_validator") or ""),
        )


def normalize_severity(value: str | ValidationSeverity) -> str:
    text = str(value.value if isinstance(value, ValidationSeverity) else value or "").strip().upper()
    return text if text in ValidationSeverity._value2member_map_ else ValidationSeverity.WARNING.value


def stable_finding_id(finding: ValidationFinding) -> str:
    parts = [
        normalize_severity(finding.severity),
        finding.category,
        finding.sheet_name,
        str(finding.row_number or ""),
        finding.column_name,
        finding.audit_id,
        finding.machine_number,
        finding.message,
        finding.current_value,
        finding.expected_behavior,
        finding.recommended_action,
        finding.fix_id,
        finding.source_validator,
    ]
    digest = hashlib.sha256("\u241f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"vf_{digest}"


def make_finding(
    severity: str | ValidationSeverity,
    category: str,
    message: str,
    *,
    sheet_name: str = "",
    row_number: int | None = None,
    column_name: str = "",
    audit_id: str = "",
    machine_number: str = "",
    current_value: Any = "",
    expected_behavior: str = "",
    recommended_action: str = "",
    fix_available: bool = False,
    fix_id: str = "",
    source_validator: str = "",
) -> ValidationFinding:
    return ValidationFinding(
        finding_id="",
        severity=normalize_severity(severity),
        category=category,
        sheet_name=sheet_name,
        row_number=row_number,
        column_name=column_name,
        audit_id=audit_id,
        machine_number=machine_number,
        message=message,
        current_value="" if current_value is None else str(current_value),
        expected_behavior=expected_behavior,
        recommended_action=recommended_action,
        fix_available=bool(fix_available),
        fix_id=fix_id if fix_available else "",
        source_validator=source_validator,
    )


def findings_to_dicts(findings: Iterable[ValidationFinding]) -> list[dict[str, Any]]:
    return [finding.to_dict() for finding in sorted(findings, key=finding_sort_key)]


def findings_from_result(result: Any) -> list[ValidationFinding]:
    data = getattr(result, "structured_data", {}) or {}
    raw_findings = data.get("validation_findings", [])
    findings: list[ValidationFinding] = []
    if isinstance(raw_findings, list):
        for raw in raw_findings:
            if isinstance(raw, ValidationFinding):
                findings.append(raw)
            elif isinstance(raw, dict):
                findings.append(ValidationFinding.from_dict(raw))
    return sorted(findings, key=finding_sort_key)


def finding_sort_key(finding: ValidationFinding) -> tuple[int, str, str, int, str, str]:
    return (
        SEVERITY_ORDER.get(normalize_severity(finding.severity), 9),
        finding.category.casefold(),
        finding.sheet_name.casefold(),
        finding.row_number or 0,
        finding.audit_id.casefold(),
        finding.column_name.casefold(),
    )


def summarize_findings(findings: Iterable[ValidationFinding]) -> dict[str, Any]:
    counts = {severity.value: 0 for severity in ValidationSeverity}
    category_counts: dict[str, int] = {}
    fixable = 0
    total = 0
    for finding in findings:
        total += 1
        severity = normalize_severity(finding.severity)
        counts[severity] = counts.get(severity, 0) + 1
        category_counts[finding.category] = category_counts.get(finding.category, 0) + 1
        if finding.fix_available:
            fixable += 1
    return {
        "total": total,
        "by_severity": counts,
        "by_category": dict(sorted(category_counts.items())),
        "fix_available_count": fixable,
    }


def validation_json_payload(project_root: str | Path, result: Any, findings: Iterable[ValidationFinding] | None = None) -> dict[str, Any]:
    finding_rows = list(findings) if findings is not None else findings_from_result(result)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(resolve_project_paths(project_root).project_root),
        "tool_id": getattr(result, "tool_id", "workbook_validator"),
        "tool_name": getattr(result, "tool_name", "EOAT Project Foundation Validation"),
        "success": bool(getattr(result, "success", False)),
        "summary": str(getattr(result, "summary", "")),
        "summary_counts": summarize_findings(finding_rows),
        "findings": findings_to_dicts(finding_rows),
    }


def write_validation_json_report(project_root: str | Path, result: Any, findings: Iterable[ValidationFinding] | None = None) -> Path:
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.validation_reports)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    payload = validation_json_payload(project_root, result, findings)
    report_path = paths.validation_reports / f"Foundation_Validation_{stamp}.json"
    try:
        return safe_write_text(report_path, json.dumps(payload, indent=2, sort_keys=True) + "\n", overwrite=False)
    except FileExistsError:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        report_path = paths.validation_reports / f"Foundation_Validation_{stamp}.json"
        return safe_write_text(report_path, json.dumps(payload, indent=2, sort_keys=True) + "\n", overwrite=False)


def attach_findings(result: Any, findings: Iterable[ValidationFinding]) -> Any:
    finding_rows = list(findings)
    result.structured_data["validation_findings"] = findings_to_dicts(finding_rows)
    summary = summarize_findings(finding_rows)
    result.metrics["validation_finding_count"] = summary["total"]
    result.metrics["validation_fix_available_count"] = summary["fix_available_count"]
    result.metrics["validation_findings_by_severity"] = summary["by_severity"]
    return result


def _row_number(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ValidationFinding",
    "ValidationSeverity",
    "attach_findings",
    "findings_from_result",
    "findings_to_dicts",
    "make_finding",
    "summarize_findings",
    "validation_json_payload",
    "write_validation_json_report",
]
