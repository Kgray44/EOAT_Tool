from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit_compatibility import machine_from_audit_row, normalize_machine_token
from .guided_audit import build_guided_audit_plan
from .open_items import list_open_items
from .paths import resolve_project_paths
from .photo_evidence import evidence_coverage_for_audit
from .press_view import PressViewGroup, build_press_view_groups
from .robot_info import load_robot_info_for_audit_entry
from .workbook_cache import row_dicts_cached as row_dicts


@dataclass(frozen=True)
class Machine360Context:
    machine_number: str
    display_name: str
    physical_audits: list[dict[str, Any]] = field(default_factory=list)
    compatible_entries: list[dict[str, Any]] = field(default_factory=list)
    linked_compatible_entries: list[dict[str, Any]] = field(default_factory=list)
    open_items: list[dict[str, Any]] = field(default_factory=list)
    photo_evidence: list[dict[str, Any]] = field(default_factory=list)
    guided_plans: list[dict[str, Any]] = field(default_factory=list)
    robot_info: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_machine_360_context(project_root: str | Path, machine_number: str) -> Machine360Context:
    machine = normalize_machine_token(machine_number) or str(machine_number or "").strip()
    warnings: list[str] = []
    if not machine:
        warnings.append("No machine number selected.")
    paths = resolve_project_paths(project_root)
    inventory = _inventory_rows(paths.master_workbook, warnings)
    groups = build_press_view_groups(project_root)
    group = _find_press_group(groups, machine)
    machine_rows = [row for row in inventory if _row_matches_machine(row, machine)]
    physical_rows = [row for row in machine_rows if str(row.get("Entry Type") or "Audited").strip().casefold() != "compatible"]
    compatible_rows = [row for row in machine_rows if str(row.get("Entry Type") or "").strip().casefold() == "compatible"]
    open_items = _machine_open_items(project_root, machine)
    evidence = _photo_evidence(project_root, physical_rows)
    guided = [build_guided_audit_plan(row, limit=5).to_dict() for row in physical_rows[:5]]
    robot_info = _robot_info(project_root, physical_rows)
    linked = [entry.to_dict() for entry in group.linked_compatible_entries] if group else []
    metrics = {
        "physical_audit_count": len(physical_rows) if physical_rows else len(group.physical_audits) if group else 0,
        "compatible_entry_count": len(compatible_rows) if compatible_rows else len(group.compatible_entries) if group else 0,
        "linked_compatible_count": len(linked),
        "open_item_count": len(open_items),
        "missing_required_photo_evidence": sum(item.get("missing_required_count", 0) for item in evidence),
        "guided_gap_count": sum(len(plan.get("steps", [])) for plan in guided),
        "robot_info_rows": len(robot_info),
    }
    actions = _recommended_actions(metrics, warnings)
    display_name = group.display_name if group else f"Press/Machine {machine}" if machine else "No Machine Selected"
    return Machine360Context(
        machine_number=machine,
        display_name=display_name,
        physical_audits=[dict(row) for row in physical_rows],
        compatible_entries=[dict(row) for row in compatible_rows],
        linked_compatible_entries=linked,
        open_items=open_items,
        photo_evidence=evidence,
        guided_plans=guided,
        robot_info=robot_info,
        metrics=metrics,
        warnings=warnings,
        recommended_actions=actions,
    )


def _inventory_rows(workbook: Path, warnings: list[str]) -> list[dict[str, Any]]:
    if not workbook.exists():
        warnings.append("Master workbook is missing.")
        return []
    try:
        return row_dicts(workbook, "EOAT Inventory")
    except Exception as exc:
        warnings.append(f"Could not read EOAT Inventory: {exc}")
        return []


def _find_press_group(groups: list[PressViewGroup], machine: str) -> PressViewGroup | None:
    target = normalize_machine_token(machine)
    for group in groups:
        if normalize_machine_token(group.machine) == target:
            return group
    return None


def _row_matches_machine(row: dict[str, Any], machine: str) -> bool:
    return normalize_machine_token(machine_from_audit_row(row)) == normalize_machine_token(machine)


def _machine_open_items(project_root: str | Path, machine: str) -> list[dict[str, Any]]:
    try:
        items = list_open_items(project_root, include_validation=True)
    except Exception:
        return []
    target = normalize_machine_token(machine)
    return [
        {
            "id": item.id,
            "source": item.source,
            "severity": item.severity,
            "category": item.category,
            "title": item.title,
            "machine": item.machine,
            "audit_id": item.audit_id,
            "field": item.field,
            "status": item.status,
            "recommended_action": item.recommended_action,
        }
        for item in items
        if normalize_machine_token(item.machine) == target
    ]


def _photo_evidence(project_root: str | Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for row in rows:
        audit_id = str(row.get("Audit ID") or "").strip()
        if not audit_id:
            continue
        coverage = evidence_coverage_for_audit(project_root, audit_id, row=row)
        if coverage is not None:
            evidence.append(coverage.to_dict())
    return evidence


def _robot_info(project_root: str | Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for row in rows:
        try:
            info = load_robot_info_for_audit_entry(project_root, row)
        except Exception:
            info = None
        if not info:
            continue
        item = {str(key): value for key, value in info.items()}
        key = tuple(sorted((str(k), str(v)) for k, v in item.items()))
        if key in seen:
            continue
        seen.add(key)
        values.append(item)
    return values


def _recommended_actions(metrics: dict[str, Any], warnings: list[str]) -> list[str]:
    actions: list[str] = []
    if warnings:
        actions.append("Resolve the data access warnings before relying on Machine 360 for handoff decisions.")
    if metrics.get("physical_audit_count", 0) == 0:
        actions.append("Create or load the physical audit for this machine.")
    if metrics.get("guided_gap_count", 0):
        actions.append("Use Guided Audit Mode to close the highest-priority missing audit fields.")
    if metrics.get("missing_required_photo_evidence", 0):
        actions.append("Capture or intake the missing required photo evidence.")
    if metrics.get("open_item_count", 0):
        actions.append("Review unresolved open items tied to this machine.")
    if not actions:
        actions.append("Review the machine summary and export handoff evidence when ready.")
    return actions

