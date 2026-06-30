from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit.relationships import relationship_summary_for_machine
from .audit_compatibility import machine_from_audit_row, normalize_machine_token
from .audit_constants import AIR_ARCHITECTURE_MIXED, MIXED_AIR_CONTROL_BADGE
from .guided_audit import build_guided_audit_plan
from .open_items import load_cached_open_items
from .paths import resolve_project_paths
from .photo_evidence import evidence_coverage_for_audit
from .pm_due import build_pm_due_item
from .press_view import PressViewGroup, load_cached_press_view_groups
from .result import ToolResult
from .robot_info import load_robot_info_for_audit_entry
from .safe_files import ensure_directory, safe_write_text
from .workbook_cache import row_dicts_cached as row_dicts


@dataclass(frozen=True)
class Machine360Action:
    action_id: str
    label: str
    target_page: str
    target_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    requires_expensive_validation: bool = False
    modifies_files: bool = False
    help_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    machine_identity: dict[str, Any] = field(default_factory=dict)
    physical_audit_summary: dict[str, Any] = field(default_factory=dict)
    compatibility_summary: dict[str, Any] = field(default_factory=dict)
    tooling_summary: dict[str, Any] = field(default_factory=dict)
    pneumatic_circuits: dict[str, Any] = field(default_factory=dict)
    sensors_detection: dict[str, Any] = field(default_factory=dict)
    mechanical_routing: dict[str, Any] = field(default_factory=dict)
    reliability_performance: dict[str, Any] = field(default_factory=dict)
    documentation_photos: dict[str, Any] = field(default_factory=dict)
    risk_fmea: dict[str, Any] = field(default_factory=dict)
    kpi_signals: dict[str, Any] = field(default_factory=dict)
    pm_status: dict[str, Any] = field(default_factory=dict)
    notes: list[dict[str, Any]] = field(default_factory=list)
    tags: list[dict[str, Any]] = field(default_factory=list)
    validation_findings: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    actions: list[Machine360Action] = field(default_factory=list)
    last_refreshed: str = ""
    data_sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectDataService:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)
        self.paths = resolve_project_paths(self.project_root)

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        target = _text(audit_id)
        if not target:
            return None
        return next((dict(row) for row in self.list_audits() if _text(row.get("Audit ID")) == target), None)

    def list_audits(self) -> list[dict[str, Any]]:
        return self._rows("EOAT Inventory")

    def list_machines(self) -> list[str]:
        machines = {
            normalize_machine_token(machine_from_audit_row(row))
            for row in self.list_audits()
            if normalize_machine_token(machine_from_audit_row(row))
        }
        return sorted(machines, key=_machine_sort_key)

    def get_machine_context(self, machine_number: str) -> dict[str, Any]:
        machine = normalize_machine_token(machine_number)
        rows = self.list_audits()
        summary = relationship_summary_for_machine(rows, machine)
        open_items = self.get_open_items_for_machine(machine)
        photos = []
        for row in summary.physical_audits:
            audit_id = _text(row.get("Audit ID"))
            if audit_id:
                photos.extend(self.get_photos_for_audit(audit_id))
        return {
            "machine_number": machine,
            "relationship_summary": summary.to_dict(),
            "physical_audits": summary.physical_audits,
            "compatibility_entries": summary.compatibility_entries,
            "linked_compatibility_entries": summary.linked_compatibility_entries,
            "open_items": open_items,
            "photos": photos,
            "validation_findings": self.get_validation_findings("machine", machine),
            "metrics": {
                **summary.metrics,
                "open_item_count": len(open_items),
                "photo_count": len(photos),
            },
            "warnings": list(summary.warnings),
        }

    def get_machine_360(self, machine_number: str) -> Machine360Context:
        return build_machine_360_context(self.project_root, machine_number)

    def get_open_items_for_machine(self, machine_number: str) -> list[dict[str, Any]]:
        machine = normalize_machine_token(machine_number)
        data_sources: list[dict[str, Any]] = []
        open_items = _machine_open_items(self.project_root, machine, data_sources)
        action_rows = self._rows_for_machine("Action Items", machine, machine_header="Related Cell/Press")
        return _merge_open_items(open_items, _open_items_from_action_rows(action_rows, machine))

    def get_photos_for_audit(self, audit_id: str) -> list[dict[str, Any]]:
        target = _text(audit_id)
        if not target:
            return []
        return [dict(row) for row in self._rows("Photo Index") if _text(row.get("Related Audit ID")) == target]

    def get_validation_findings(self, scope: str, target_id: str) -> list[dict[str, Any]]:
        scope_key = _text(scope).casefold()
        target = normalize_machine_token(target_id) if scope_key == "machine" else _text(target_id)
        if scope_key == "project":
            target = ""
        findings = _latest_validation_findings_for_scope(self.paths, scope_key, target)
        return findings

    def _rows(self, sheet_name: str) -> list[dict[str, Any]]:
        if not self.paths.master_workbook.exists():
            return []
        try:
            return [dict(row) for row in row_dicts(self.paths.master_workbook, sheet_name)]
        except Exception:
            return []

    def _rows_for_machine(
        self, sheet_name: str, machine_number: str, *, machine_header: str = "Press/Machine #"
    ) -> list[dict[str, Any]]:
        target = normalize_machine_token(machine_number)
        return [
            dict(row) for row in self._rows(sheet_name) if normalize_machine_token(row.get(machine_header)) == target
        ]


def build_machine_360_context(project_root: str | Path, machine_number: str) -> Machine360Context:
    machine = normalize_machine_token(machine_number) or str(machine_number or "").strip()
    warnings: list[str] = []
    data_sources: list[dict[str, Any]] = []
    if not machine:
        warnings.append("No machine number selected.")
    paths = resolve_project_paths(project_root)
    inventory = _inventory_rows(paths.master_workbook, warnings, data_sources)
    groups, press_cache_generated_at = _cached_press_groups(project_root, warnings, data_sources)
    group = _find_press_group(groups, machine)
    relationship_summary = relationship_summary_for_machine(inventory, machine)
    warnings.extend(relationship_summary.warnings)
    physical_rows = relationship_summary.physical_audits
    compatible_rows = relationship_summary.compatibility_entries
    open_items = _machine_open_items(project_root, machine, data_sources)
    evidence = _photo_evidence(project_root, physical_rows)
    guided = [build_guided_audit_plan(row, limit=5).to_dict() for row in physical_rows[:5]]
    robot_info = _robot_info(project_root, physical_rows)
    linked = relationship_summary.linked_compatibility_entries
    notes, tags = _annotations_for_machine(project_root, machine, physical_rows, data_sources)
    issue_rows = _machine_sheet_rows(paths, "Issue Log", machine, warnings, data_sources, "issue log")
    kpi_rows = _machine_sheet_rows(paths, "KPI Baseline", machine, warnings, data_sources, "KPI baseline")
    fmea_rows = _machine_sheet_rows(paths, "FMEA Draft", machine, warnings, data_sources, "FMEA draft")
    pilot_rows = _machine_sheet_rows(paths, "Pilot Candidates", machine, warnings, data_sources, "pilot candidates")
    interview_rows = _machine_sheet_rows(paths, "Interview Notes", machine, warnings, data_sources, "interview notes")
    action_rows = _machine_sheet_rows(
        paths, "Action Items", machine, warnings, data_sources, "action items", machine_header="Related Cell/Press"
    )
    open_items = _merge_open_items(open_items, _open_items_from_action_rows(action_rows, machine))
    photo_rows = _machine_sheet_rows(paths, "Photo Index", machine, warnings, data_sources, "photo index")
    validation_findings = _latest_validation_findings(paths, machine, data_sources)
    reports = _reports_for_machine(paths, machine, data_sources)
    machine_identity = _machine_identity(machine, group, physical_rows, compatible_rows, robot_info)
    physical_summary = _physical_audit_summary(physical_rows, guided)
    compatibility_summary = _compatibility_summary(compatible_rows, linked, group)
    tooling_summary = _tooling_summary(physical_rows, compatible_rows)
    pneumatic_summary = _pneumatic_summary(physical_rows, robot_info)
    sensors_summary = _sensors_summary(physical_rows)
    mechanical_summary = _mechanical_routing_summary(physical_rows)
    reliability_summary = _reliability_summary(physical_rows, issue_rows, action_rows)
    documentation_summary = _documentation_photo_summary(project_root, physical_rows, evidence, photo_rows)
    risk_summary = _risk_fmea_summary(issue_rows, fmea_rows, pilot_rows)
    kpi_summary = _kpi_summary(kpi_rows)
    pm_summary = _pm_status(project_root, physical_rows)
    metrics = {
        "physical_audit_count": len(physical_rows) if physical_rows else len(group.physical_audits) if group else 0,
        "compatible_entry_count": len(compatible_rows)
        if compatible_rows
        else len(group.compatible_entries)
        if group
        else 0,
        "linked_compatible_count": len(linked),
        "open_item_count": len(open_items),
        "missing_required_photo_evidence": sum(item.get("missing_required_count", 0) for item in evidence),
        "guided_gap_count": sum(len(plan.get("steps", [])) for plan in guided),
        "robot_info_rows": len(robot_info),
        "issue_count": len(issue_rows),
        "kpi_rows": len(kpi_rows),
        "fmea_rows": len(fmea_rows),
        "report_reference_count": len(reports),
        "validation_finding_count": len(validation_findings),
        "photo_index_rows": len(photo_rows),
    }
    if group:
        metrics.update(
            {
                "press_cache_open_item_count": group.open_item_count,
                "press_cache_validation_warning_count": group.validation_warning_count,
                "press_cache_photo_count": group.photo_count,
                "press_cache_generated_at": press_cache_generated_at or "",
            }
        )
    actions = _recommended_actions(metrics, warnings)
    display_name = group.display_name if group else f"Press/Machine {machine}" if machine else "No Machine Selected"
    action_payloads = _machine_actions(project_root, machine, display_name, physical_rows, documentation_summary)
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
        machine_identity=machine_identity,
        physical_audit_summary=physical_summary,
        compatibility_summary=compatibility_summary,
        tooling_summary=tooling_summary,
        pneumatic_circuits=pneumatic_summary,
        sensors_detection=sensors_summary,
        mechanical_routing=mechanical_summary,
        reliability_performance=reliability_summary,
        documentation_photos=documentation_summary,
        risk_fmea=risk_summary,
        kpi_signals=kpi_summary,
        pm_status=pm_summary,
        notes=notes,
        tags=tags,
        validation_findings=validation_findings,
        reports=reports,
        actions=action_payloads,
        last_refreshed=datetime.now().isoformat(timespec="seconds"),
        data_sources=data_sources,
    )


def generate_machine_360_summary(
    project_root: str | Path, machine_number: str, context: Machine360Context | None = None
) -> ToolResult:
    context = context or build_machine_360_context(project_root, machine_number)
    if not context.machine_number:
        return ToolResult.fail("machine_360_summary", "Machine 360 Summary", "No machine was selected.")
    paths = resolve_project_paths(project_root)
    folder = ensure_directory(paths.project_admin / "Machine_360_Summaries")
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_machine = re.sub(r"[^A-Za-z0-9_-]+", "_", context.machine_number).strip("_") or "machine"
    path = folder / f"Machine_{safe_machine}_360_Summary_{stamp}.md"
    lines = [
        f"# {context.display_name} Machine 360",
        "",
        f"- Last refreshed: {context.last_refreshed or 'Unknown'}",
        f"- Physical audits: {context.metrics.get('physical_audit_count', 0)}",
        f"- Compatible entries assigned here: {context.metrics.get('compatible_entry_count', 0)}",
        f"- Linked compatible entries: {context.metrics.get('linked_compatible_count', 0)}",
        f"- Open items: {context.metrics.get('open_item_count', 0)}",
        f"- Validation findings from latest report: {context.metrics.get('validation_finding_count', 0)}",
        "",
    ]
    for title, section in _summary_sections(context):
        lines.extend([f"## {title}"])
        if section:
            for key, value in section.items():
                lines.append(f"- {key}: {_summary_value(value)}")
        else:
            lines.append("- No data available.")
        lines.append("")
    lines.extend(["## Recommended Actions", *[f"- {action}" for action in context.recommended_actions], ""])
    if context.warnings:
        lines.extend(["## Warnings", *[f"- {warning}" for warning in context.warnings], ""])
    saved = safe_write_text(path, "\n".join(lines).rstrip() + "\n", overwrite=False)
    return ToolResult.ok(
        "machine_360_summary",
        "Machine 360 Summary",
        f"Generated Machine 360 summary for {context.display_name}.",
        files_created=[str(saved)],
        output_reports=[str(saved)],
        metrics={"machine": context.machine_number, "physical_audits": context.metrics.get("physical_audit_count", 0)},
    )


def _inventory_rows(workbook: Path, warnings: list[str], data_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not workbook.exists():
        warnings.append("Master workbook is missing.")
        data_sources.append({"name": "EOAT Inventory", "status": "missing", "path": str(workbook), "row_count": 0})
        return []
    try:
        rows = row_dicts(workbook, "EOAT Inventory")
        data_sources.append(
            {"name": "EOAT Inventory", "status": "loaded", "path": str(workbook), "row_count": len(rows)}
        )
        return rows
    except Exception as exc:
        warnings.append(f"Could not read EOAT Inventory: {exc}")
        data_sources.append(
            {"name": "EOAT Inventory", "status": "error", "path": str(workbook), "error": str(exc), "row_count": 0}
        )
        return []


def _cached_press_groups(
    project_root: str | Path, warnings: list[str], data_sources: list[dict[str, Any]]
) -> tuple[list[PressViewGroup], str]:
    try:
        groups, generated_at, warning = load_cached_press_view_groups(project_root)
    except Exception as exc:
        warnings.append(f"Could not load cached Press View data: {exc}")
        data_sources.append({"name": "Press View cache", "status": "error", "error": str(exc), "row_count": 0})
        return [], ""
    if groups:
        data_sources.append(
            {
                "name": "Press View cache",
                "status": "loaded",
                "generated_at": generated_at or "",
                "row_count": len(groups),
            }
        )
        return groups, generated_at or ""
    data_sources.append(
        {
            "name": "Press View cache",
            "status": "missing",
            "warning": warning or "No cached press view found.",
            "row_count": 0,
        }
    )
    return [], ""


def _find_press_group(groups: list[PressViewGroup], machine: str) -> PressViewGroup | None:
    target = normalize_machine_token(machine)
    for group in groups:
        if normalize_machine_token(group.machine) == target:
            return group
    return None


def _machine_open_items(
    project_root: str | Path, machine: str, data_sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        items, generated_at, warning = load_cached_open_items(project_root)
    except Exception as exc:
        data_sources.append({"name": "Open items snapshot", "status": "error", "error": str(exc), "row_count": 0})
        return []
    if not items:
        data_sources.append(
            {
                "name": "Open items snapshot",
                "status": "missing_optional",
                "warning": warning or "No cached open-items snapshot found.",
                "row_count": 0,
            }
        )
        return []
    target = normalize_machine_token(machine)
    rows = [
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
    data_sources.append(
        {"name": "Open items snapshot", "status": "loaded", "generated_at": generated_at or "", "row_count": len(rows)}
    )
    return rows


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


def _annotations_for_machine(
    project_root: str | Path,
    machine: str,
    physical_rows: list[dict[str, Any]],
    data_sources: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = resolve_project_paths(project_root)
    if not paths.annotations_database.exists():
        data_sources.append(
            {
                "name": "Annotation database",
                "status": "missing_optional",
                "path": str(paths.annotations_database),
                "row_count": 0,
            }
        )
        return [], []
    try:
        from .annotations.service import AnnotationService
    except Exception as exc:
        data_sources.append({"name": "Annotation database", "status": "error", "error": str(exc), "row_count": 0})
        return [], []
    try:
        service = AnnotationService(project_root, initialize=False)
        notes_by_id: dict[str, dict[str, Any]] = {}
        tags_by_id: dict[str, dict[str, Any]] = {}
        for note in service.search_notes(machine_id=machine):
            notes_by_id[str(note.get("id") or len(notes_by_id))] = dict(note)
        for tag in service.list_tag_assignments(machine_id=machine):
            tags_by_id[str(tag.get("assignment_id") or len(tags_by_id))] = dict(tag)
        for row in physical_rows:
            audit_id = _text(row.get("Audit ID"))
            if not audit_id:
                continue
            for note in service.search_notes(audit_id=audit_id):
                notes_by_id[str(note.get("id") or len(notes_by_id))] = dict(note)
            for tag in service.list_tag_assignments(audit_id=audit_id):
                tags_by_id[str(tag.get("assignment_id") or len(tags_by_id))] = dict(tag)
        notes = list(notes_by_id.values())
        tags = list(tags_by_id.values())
        data_sources.append(
            {
                "name": "Annotation database",
                "status": "loaded",
                "path": str(paths.annotations_database),
                "row_count": len(notes) + len(tags),
            }
        )
        return notes, tags
    except Exception as exc:
        data_sources.append(
            {
                "name": "Annotation database",
                "status": "error",
                "path": str(paths.annotations_database),
                "error": str(exc),
                "row_count": 0,
            }
        )
        return [], []


def _machine_sheet_rows(
    paths,
    sheet_name: str,
    machine: str,
    warnings: list[str],
    data_sources: list[dict[str, Any]],
    source_label: str,
    *,
    machine_header: str = "Press/Machine #",
) -> list[dict[str, Any]]:
    if not paths.master_workbook.exists():
        return []
    try:
        rows = row_dicts(paths.master_workbook, sheet_name)
    except Exception as exc:
        data_sources.append(
            {"name": source_label, "status": "error", "sheet": sheet_name, "error": str(exc), "row_count": 0}
        )
        return []
    target = normalize_machine_token(machine)
    matches = [row for row in rows if normalize_machine_token(row.get(machine_header)) == target]
    data_sources.append(
        {
            "name": source_label,
            "status": "loaded",
            "sheet": sheet_name,
            "row_count": len(matches),
            "total_rows": len(rows),
        }
    )
    return [dict(row) for row in matches]


def _open_items_from_action_rows(action_rows: list[dict[str, Any]], machine: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in action_rows:
        status = _text(row.get("Status")) or "Open"
        if status.casefold() in {"resolved", "closed", "complete", "completed", "done"}:
            continue
        action_id = _text(row.get("Action ID")) or f"action:{len(rows) + 1}"
        priority = _text(row.get("Priority")) or "Medium"
        rows.append(
            {
                "id": f"action_item:{action_id}",
                "source": "action_item",
                "severity": "Critical"
                if priority.casefold() == "critical"
                else "High"
                if priority.casefold() == "high"
                else "Medium",
                "category": "follow_up",
                "title": _text(row.get("Action Item")) or "Open action item",
                "machine": machine,
                "audit_id": "",
                "field": "",
                "status": status,
                "recommended_action": _text(row.get("Notes")) or "Review or close the action item.",
                "due_date": _text(row.get("Due Date")),
            }
        )
    return rows


def _merge_open_items(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*first, *second]:
        item_id = _text(row.get("id")) or f"open_item:{len(merged) + 1}"
        if item_id in seen:
            continue
        seen.add(item_id)
        merged.append(row)
    return merged


def _latest_validation_findings(paths, machine: str, data_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folder = paths.validation_reports
    if not folder.exists():
        data_sources.append(
            {"name": "Latest validation report", "status": "missing_optional", "path": str(folder), "row_count": 0}
        )
        return []
    files = sorted(folder.glob("Foundation_Validation_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        data_sources.append(
            {"name": "Latest validation report", "status": "missing_optional", "path": str(folder), "row_count": 0}
        )
        return []
    path = files[0]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        data_sources.append(
            {
                "name": "Latest validation report",
                "status": "error",
                "path": str(path),
                "error": str(exc),
                "row_count": 0,
            }
        )
        return []
    target = normalize_machine_token(machine)
    findings = [
        dict(finding)
        for finding in payload.get("findings", [])
        if isinstance(finding, dict) and normalize_machine_token(finding.get("machine_number")) == target
    ]
    data_sources.append(
        {"name": "Latest validation report", "status": "loaded", "path": str(path), "row_count": len(findings)}
    )
    return findings


def _latest_validation_findings_for_scope(paths, scope: str, target_id: str) -> list[dict[str, Any]]:
    folder = paths.validation_reports
    if not folder.exists():
        return []
    files = sorted(folder.glob("Foundation_Validation_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        return []
    try:
        payload = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_findings = payload.get("findings", []) if isinstance(payload, dict) else []
    findings = [dict(finding) for finding in raw_findings if isinstance(finding, dict)]
    if scope == "project":
        return findings
    if scope == "machine":
        return [
            finding
            for finding in findings
            if normalize_machine_token(finding.get("machine_number")) == normalize_machine_token(target_id)
        ]
    if scope == "audit":
        return [finding for finding in findings if _text(finding.get("audit_id")) == target_id]
    if scope == "field":
        return [finding for finding in findings if _text(finding.get("column_name")).casefold() == target_id.casefold()]
    return [
        finding
        for finding in findings
        if target_id
        and target_id.casefold()
        in " ".join(
            _text(finding.get(key)) for key in ("audit_id", "machine_number", "column_name", "message", "category")
        ).casefold()
    ]


def _reports_for_machine(paths, machine: str, data_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target = normalize_machine_token(machine)
    if not target:
        return []
    folders = [
        paths.daily_reports,
        paths.weekly_reports,
        paths.validation_reports,
        paths.audit_progress_reports,
        paths.issue_analysis_reports,
        paths.kpi_dashboard_exports,
        paths.documentation_gap_reports,
        paths.pm_generated_checklists,
        paths.fmea_reports,
        paths.risk_insights_reports,
        paths.final_report,
    ]
    candidates: list[Path] = []
    for folder in folders:
        if not folder.exists():
            continue
        try:
            candidates.extend(
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json", ".csv"}
            )
        except OSError:
            continue
    candidates = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[:80]
    matches: list[dict[str, Any]] = []
    needles = {target, f"press {target}".casefold(), f"machine {target}".casefold()}
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:12000]
        except OSError:
            continue
        haystack = f"{path.name}\n{text}".casefold()
        if any(needle in haystack for needle in needles):
            matches.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "folder": path.parent.name,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                }
            )
    data_sources.append(
        {"name": "Report references", "status": "loaded", "candidate_count": len(candidates), "row_count": len(matches)}
    )
    return matches


def _machine_identity(
    machine: str,
    group: PressViewGroup | None,
    physical_rows: list[dict[str, Any]],
    compatible_rows: list[dict[str, Any]],
    robot_info: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = physical_rows or compatible_rows
    first = rows[0] if rows else {}
    return {
        "machine_number": machine,
        "display_name": group.display_name
        if group
        else f"Press/Machine {machine}"
        if machine
        else "No Machine Selected",
        "plant_area": _first_value(rows, "Plant/Area"),
        "robot_type": _first_value(rows, "Robot Type"),
        "robot_model_controller": _first_value(rows, "Robot Model/Controller"),
        "physical_audit_count": len(physical_rows),
        "compatible_entry_count": len(compatible_rows),
        "primary_audit_id": _text(first.get("Audit ID")),
        "robot_info_available": bool(robot_info),
    }


def _physical_audit_summary(rows: list[dict[str, Any]], guided: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "audit_ids": _unique_values(rows, "Audit ID"),
        "statuses": _value_counts(rows, "Status"),
        "priorities": _value_counts(rows, "Priority"),
        "pilot_candidates": _value_counts(rows, "Pilot Candidate?"),
        "latest_audit_date": max(_unique_values(rows, "Audit Date"), default=""),
        "guided_gap_count": sum(len(plan.get("steps", [])) for plan in guided),
    }


def _compatibility_summary(
    compatible_rows: list[dict[str, Any]], linked: list[dict[str, Any]], group: PressViewGroup | None
) -> dict[str, Any]:
    return {
        "compatible_assigned_here": len(compatible_rows),
        "linked_compatible_from_source_audits": len(linked),
        "source_audit_ids": _unique_values(compatible_rows, "Source Audit ID"),
        "compatibility_sources": _unique_values(compatible_rows, "Compatibility Source"),
        "compatibility_family_machine_count": group.compatibility_family_machine_count
        if group
        else len({entry.get("machine") for entry in linked if entry.get("machine")}),
        "physical_audits_counted_separately": True,
    }


def _tooling_summary(physical_rows: list[dict[str, Any]], compatible_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = physical_rows or compatible_rows
    return {
        "tools": _unique_values(rows, "Tool #"),
        "eoat_types": _unique_values(rows, "EOAT Type"),
        "part_families": _unique_values(rows, "Part Family"),
        "part_descriptions": _unique_values(rows, "Part Name/Description"),
        "parts_picked": _unique_values(rows, "Number of Parts Picked"),
        "cylinder_counts": _unique_values(rows, "# of Cylinders"),
        "cylinder_types": _unique_values(rows, "Cylinder Type"),
        "gripper_counts": _unique_values(rows, "# of Grippers"),
        "cup_counts": _unique_values(rows, "# of Cups"),
    }


def _pneumatic_summary(rows: list[dict[str, Any]], robot_info: list[dict[str, Any]]) -> dict[str, Any]:
    architectures = _unique_values(rows, "Air Circuit Architecture")
    mixed_air = any(value == AIR_ARCHITECTURE_MIXED for value in architectures)
    return {
        "air_architectures": architectures,
        "air_control_badge": MIXED_AIR_CONTROL_BADGE if mixed_air else "",
        "mixed_air_control": mixed_air,
        "vacuum_circuits": _unique_values(rows, "EOAT Vacuum Circuits"),
        "pressure_circuits": _unique_values(rows, "EOAT Pressure Circuits"),
        "interchangeable_circuits": _unique_values(rows, "EOAT Interchangeable Circuits"),
        "external_vacuum_circuits": _unique_values(rows, "External Vacuum Circuits"),
        "external_pressure_circuits": _unique_values(rows, "External Pressure Circuits"),
        "external_interchangeable_circuits": _unique_values(rows, "External Interchangeable Circuits"),
        "vacuum_generator_types": _unique_values(rows, "Vacuum Generator Type"),
        "pneumatic_quick_disconnects": _unique_values(rows, "Pneumatic Quick Disconnect Type"),
        "quick_disconnects_present": _value_counts(rows, "Quick Disconnects Present?"),
        "robot_side_rows": len(robot_info),
        "robot_vacuum_circuits": _unique_values(robot_info, "Robot Vacuum Circuits"),
        "robot_pressure_circuits": _unique_values(robot_info, "Robot Pressure Circuits"),
        "robot_interchangeable_circuits": _unique_values(robot_info, "Robot Interchangeable Circuits"),
        "robot_notes": _unique_values(robot_info, "Robot Notes"),
        "robot_side_air_sources": _unique_values(robot_info, "Robot Pneumatic Notes")
        or _unique_values(robot_info, "Pneumatic Notes"),
    }


def _sensors_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sensors_present": _value_counts(rows, "Sensors Present?"),
        "sensor_types": _unique_values(rows, "Sensor Type"),
        "sensor_brand_models": _unique_values(rows, "Sensor Brand/Model"),
        "part_present_detection": _value_counts(rows, "Part-Present Detection Present?"),
        "vacuum_confirmation": _value_counts(rows, "Vacuum Confirmation Present?"),
        "electrical_quick_disconnects": _unique_values(rows, "Electrical Quick Disconnect Type"),
    }


def _mechanical_routing_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tubing_condition": _value_counts(rows, "Tubing Condition"),
        "tubing_routing_notes": _unique_values(rows, "Tubing Routing Notes"),
        "cable_management_condition": _value_counts(rows, "Cable Management Condition"),
        "mounting_hardware_condition": _value_counts(rows, "Mounting Hardware Condition"),
        "alignment_condition": _value_counts(rows, "EOAT Alignment Condition"),
        "locking_hardware_present": _value_counts(rows, "Fastener/Locking Hardware Present?"),
    }


def _reliability_summary(
    rows: list[dict[str, Any]], issue_rows: list[dict[str, Any]], action_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "known_issues": _unique_values(rows, "Known Issues"),
        "drop_mispick_history": _unique_values(rows, "Drop/Mis-Pick History"),
        "maintenance_frequency": _unique_values(rows, "Maintenance Frequency"),
        "cycle_time_concern": _value_counts(rows, "Cycle Time Concern?"),
        "scrap_quality_concern": _value_counts(rows, "Scrap/Quality Concern?"),
        "issue_log_rows": len(issue_rows),
        "open_action_items": len(
            [
                row
                for row in action_rows
                if _text(row.get("Status")).casefold() not in {"resolved", "closed", "complete", "completed"}
            ]
        ),
    }


def _documentation_photo_summary(
    project_root: str | Path,
    rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    photo_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    primary_folder = ""
    for row in rows:
        primary_folder = _text(row.get("Photo Folder/Link"))
        if primary_folder:
            break
    primary_path = _resolve_photo_folder(project_root, primary_folder)
    return {
        "photos_taken": _value_counts(rows, "Photos Taken?"),
        "photo_folder_links": _unique_values(rows, "Photo Folder/Link"),
        "primary_folder_path": str(primary_path) if primary_path else "",
        "photo_index_rows": len(photo_rows),
        "missing_required_photo_evidence": sum(item.get("missing_required_count", 0) for item in evidence),
        "drawing_cad_available": _value_counts(rows, "Drawing/CAD Available?"),
        "bom_available": _value_counts(rows, "BOM Available?"),
        "process_binder_complete": _value_counts(rows, "Process Binder Complete?"),
        "evidence_items": evidence,
    }


def _risk_fmea_summary(
    issue_rows: list[dict[str, Any]], fmea_rows: list[dict[str, Any]], pilot_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    rpns = [_int(row.get("RPN")) for row in fmea_rows if _int(row.get("RPN")) is not None]
    issue_severity = [_int(row.get("Severity")) for row in issue_rows if _int(row.get("Severity")) is not None]
    return {
        "issue_log_rows": len(issue_rows),
        "fmea_rows": len(fmea_rows),
        "pilot_candidate_rows": len(pilot_rows),
        "highest_rpn": max(rpns, default=0),
        "highest_issue_severity": max(issue_severity, default=0),
        "failure_modes": _unique_values(fmea_rows, "Failure Mode"),
        "pilot_approval_statuses": _value_counts(pilot_rows, "Approval Status"),
    }


def _kpi_summary(kpi_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": len(kpi_rows),
        "downtime_minutes": _sum_numeric(kpi_rows, "Downtime Minutes"),
        "part_drops": _sum_numeric(kpi_rows, "Part Drops"),
        "mis_picks": _sum_numeric(kpi_rows, "Mis-Picks"),
        "scrap_quantity": _sum_numeric(kpi_rows, "Scrap Quantity"),
        "maintenance_events": _sum_numeric(kpi_rows, "Maintenance Event Count"),
        "data_sources": _unique_values(kpi_rows, "Data Source"),
    }


def _pm_status(project_root: str | Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for row in rows:
        try:
            items.append(build_pm_due_item(project_root, row).to_dict())
        except Exception:
            continue
    return {
        "items": items,
        "due_now": sum(1 for item in items if item.get("due_state") == "Due Now"),
        "needs_frequency": sum(1 for item in items if item.get("due_state") == "Needs Frequency"),
        "highest_risk_score": max([int(item.get("risk_score") or 0) for item in items], default=0),
    }


def _machine_actions(
    project_root: str | Path,
    machine: str,
    display_name: str,
    physical_rows: list[dict[str, Any]],
    documentation_summary: dict[str, Any],
) -> list[Machine360Action]:
    primary_audit = next((_text(row.get("Audit ID")) for row in physical_rows if _text(row.get("Audit ID"))), "")
    photo_folder = _text(documentation_summary.get("primary_folder_path"))
    machine_payload = {"machine": machine, "display_name": display_name}
    return [
        Machine360Action(
            "open_audit",
            "Open Audit",
            "audit",
            "audit",
            {"audit_id": primary_audit, **machine_payload},
            available=bool(primary_audit),
        ),
        Machine360Action("open_press_view", "Open Press View", "press_view", "machine", machine_payload),
        Machine360Action("add_note", "Add Note", "notes", "machine", machine_payload),
        Machine360Action("add_tag", "Add Tag", "tags", "machine", machine_payload),
        Machine360Action(
            "create_follow_up", "Create Follow-Up", "open_items", "machine", machine_payload, modifies_files=True
        ),
        Machine360Action(
            "run_machine_validation",
            "Run Machine Validation",
            "workbook_health",
            "machine",
            machine_payload,
            requires_expensive_validation=True,
            modifies_files=True,
            help_text="Runs foundation validation only after this explicit button click.",
        ),
        Machine360Action(
            "generate_machine_summary",
            "Generate Machine Summary",
            "machine_360",
            "machine",
            machine_payload,
            modifies_files=True,
        ),
        Machine360Action(
            "open_photo_folder",
            "Open Photo Folder",
            "photos",
            "photo",
            {"path": photo_folder, **machine_payload},
            available=bool(photo_folder),
        ),
        Machine360Action(
            "generate_pm_checklist",
            "Generate PM Checklist",
            "pm_checklists",
            "machine",
            machine_payload,
            modifies_files=True,
        ),
        Machine360Action(
            "generate_work_instruction_draft",
            "Generate Work Instruction Draft",
            "standards_docs",
            "machine",
            machine_payload,
            available=False,
            help_text="No work-instruction draft generator is registered in this app yet.",
        ),
    ]


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


def _summary_sections(context: Machine360Context) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("Machine Identity", context.machine_identity),
        ("Physical Audit Summary", context.physical_audit_summary),
        ("Compatibility Summary", context.compatibility_summary),
        ("EOAT Tooling Summary", context.tooling_summary),
        ("Pneumatic Circuits", context.pneumatic_circuits),
        ("Sensors and Detection", context.sensors_detection),
        ("Mechanical / Routing", context.mechanical_routing),
        ("Reliability / Performance", context.reliability_performance),
        ("Documentation / Photos", {k: v for k, v in context.documentation_photos.items() if k != "evidence_items"}),
        ("Risk / FMEA", context.risk_fmea),
        ("KPI Signals", context.kpi_signals),
        ("PM Status", context.pm_status),
    ]


def _first_value(rows: list[dict[str, Any]], field: str) -> str:
    for row in rows:
        value = _text(row.get(field))
        if value:
            return value
    return ""


def _unique_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = _text(row.get(field))
        if not value or value.casefold() in {"n/a", "na"}:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def _value_counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = _text(row.get(field)) or "Unknown"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0].casefold()))


def _sum_numeric(rows: list[dict[str, Any]], field: str) -> float:
    total = 0.0
    for row in rows:
        value = _int(row.get(field))
        if value is not None:
            total += value
    return total


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _machine_sort_key(machine: str) -> tuple[int, int | str]:
    value = normalize_machine_token(machine)
    if value.isdigit():
        return (0, int(value))
    return (1, value.casefold())


def _summary_value(value: Any) -> str:
    if isinstance(value, dict):
        if not value:
            return "None"
        return ", ".join(f"{key}={item}" for key, item in value.items())
    if isinstance(value, list):
        if not value:
            return "None"
        if len(value) > 5:
            return ", ".join(str(item) for item in value[:5]) + f" (+{len(value) - 5} more)"
        return ", ".join(str(item) for item in value)
    return str(value)


def _resolve_photo_folder(project_root: str | Path, link: str) -> Path | None:
    text = _text(link)
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return Path(project_root) / path
