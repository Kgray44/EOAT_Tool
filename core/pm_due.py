from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit_compatibility import normalize_machine_token
from .paths import resolve_project_paths
from .photo_evidence import pm_bom_evidence_status
from .workbook_cache import row_dicts_cached as row_dicts


@dataclass(frozen=True)
class PmDueItem:
    audit_id: str
    machine: str
    eoat_type: str
    priority: str
    maintenance_frequency: str
    due_state: str
    risk_score: int
    missing_evidence_count: int = 0
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PmDueSummary:
    items: list[PmDueItem] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items], "metrics": dict(self.metrics), "warnings": list(self.warnings)}


def analyze_pm_due(project_root: str | Path) -> PmDueSummary:
    workbook = resolve_project_paths(project_root).master_workbook
    warnings: list[str] = []
    if not workbook.exists():
        return PmDueSummary(metrics={"items": 0}, warnings=[f"Master workbook is missing: {workbook}"])
    try:
        rows = row_dicts(workbook, "EOAT Inventory")
    except Exception as exc:
        return PmDueSummary(metrics={"items": 0}, warnings=[f"Could not read EOAT Inventory: {exc}"])
    items = [build_pm_due_item(project_root, row) for row in rows if str(row.get("Audit ID") or "").strip()]
    items.sort(key=lambda item: (-item.risk_score, item.machine, item.audit_id))
    metrics = {
        "items": len(items),
        "due_now": sum(1 for item in items if item.due_state == "Due Now"),
        "needs_frequency": sum(1 for item in items if item.due_state == "Needs Frequency"),
        "missing_evidence": sum(1 for item in items if item.missing_evidence_count),
        "highest_risk_score": items[0].risk_score if items else 0,
    }
    return PmDueSummary(items=items, metrics=metrics, warnings=warnings)


def build_pm_due_item(project_root: str | Path, row: dict[str, Any]) -> PmDueItem:
    audit_id = _text(row.get("Audit ID"))
    frequency = _text(row.get("Maintenance Frequency"))
    priority = _text(row.get("Priority"))
    known_issues = _text(row.get("Known Issues"))
    evidence = pm_bom_evidence_status(project_root, audit_id)
    missing_evidence = int(evidence.get("missing_required_count") or 0)
    reasons: list[str] = []
    score = 0
    due_state = _frequency_due_state(frequency)
    if due_state == "Needs Frequency":
        score += 20
        reasons.append("Maintenance frequency is missing or unknown.")
    elif due_state == "Due Now":
        score += 15
        reasons.append(f"Maintenance frequency is {frequency}.")
    if priority.casefold() in {"critical", "high"}:
        score += 20 if priority.casefold() == "critical" else 12
        reasons.append(f"Audit priority is {priority}.")
    if known_issues and known_issues.casefold() not in {"none", "no", "n/a", "unknown / not checked"}:
        score += 15
        reasons.append("Known issues are documented.")
    if missing_evidence:
        score += min(20, missing_evidence * 5)
        reasons.append("Required PM/photo evidence is missing.")
    if not reasons:
        reasons.append("No immediate PM risk signals detected.")
    return PmDueItem(
        audit_id=audit_id,
        machine=normalize_machine_token(row.get("Press/Machine #")) or _text(row.get("Press/Machine #")),
        eoat_type=_text(row.get("EOAT Type")),
        priority=priority,
        maintenance_frequency=frequency,
        due_state=due_state,
        risk_score=score,
        missing_evidence_count=missing_evidence,
        reasons=tuple(reasons),
    )


def _frequency_due_state(value: str) -> str:
    text = value.strip().casefold()
    if not text or text in {"unknown", "unknown / not checked", "n/a", "na"}:
        return "Needs Frequency"
    if any(token in text for token in ("daily", "weekly", "per shift", "each shift")):
        return "Due Now"
    if any(token in text for token in ("monthly", "quarterly", "annual", "yearly")):
        return "Scheduled"
    return "Review"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()

