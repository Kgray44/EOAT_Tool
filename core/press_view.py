from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .audit_compatibility import machine_from_audit_row, normalize_entry_type, normalize_machine_token, part_number_from_row, text_value
from .logging import log_tool_run
from .open_items import list_open_items
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .standards_compliance import analyze_standards_compliance
from .tool_fields import TOOL_FIELD
from .workbook_io import row_dicts


@dataclass(frozen=True)
class PressAuditEntry:
    audit_id: str
    machine: str
    entry_type: str
    tool: str = ""
    eoat_type: str = ""
    status: str = ""
    pilot_candidate: str = ""
    source_audit_id: str = ""
    last_updated: str = ""
    known_issues: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PressViewGroup:
    machine: str
    display_name: str
    physical_audits: list[PressAuditEntry] = field(default_factory=list)
    compatible_entries: list[PressAuditEntry] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    open_item_count: int = 0
    validation_warning_count: int = 0
    photo_count: int = 0
    pilot_candidacy: str = ""
    last_updated: str = ""
    average_compliance_score: int = 0
    worst_compliance_category: str = ""
    open_standards_issues: int = 0

    @property
    def total_entries(self) -> int:
        return len(self.physical_audits) + len(self.compatible_entries)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_entries"] = self.total_entries
        return data


def build_press_view_groups(project_root: str | Path, *, status_filter: str = "", query: str = "") -> list[PressViewGroup]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        rows = row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception:
        return []
    open_counts = _open_item_counts(project_root)
    validation_counts = _validation_counts(project_root)
    photo_counts = _photo_counts(project_root)
    compliance_rollups = _compliance_rollups(project_root)
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        machine = machine_from_audit_row(row)
        if not machine:
            machine = "Unassigned / Missing Press"
        entry = _entry_from_row(row, machine)
        if status_filter and status_filter != "All" and status_filter.casefold() not in entry.status.casefold():
            continue
        group = grouped.setdefault(machine, {"physical": [], "compatible": [], "tools": set(), "pilot": [], "dates": []})
        if entry.entry_type.casefold() == "compatible":
            group["compatible"].append(entry)
        else:
            group["physical"].append(entry)
        if entry.tool:
            group["tools"].add(entry.tool)
        if entry.pilot_candidate:
            group["pilot"].append(entry.pilot_candidate)
        if entry.last_updated:
            group["dates"].append(entry.last_updated)

    groups: list[PressViewGroup] = []
    for machine, data in grouped.items():
        tools = sorted(data["tools"], key=str.casefold)
        group = PressViewGroup(
            machine=machine,
            display_name=_display_name(machine),
            physical_audits=sorted(data["physical"], key=lambda item: item.audit_id.casefold()),
            compatible_entries=sorted(data["compatible"], key=lambda item: item.audit_id.casefold()),
            tools=tools,
            open_item_count=open_counts.get(machine, 0),
            validation_warning_count=validation_counts.get(machine, 0),
            photo_count=photo_counts.get(machine, 0),
            pilot_candidacy=_pilot_summary(data["pilot"]),
            last_updated=max(data["dates"]) if data["dates"] else "",
            average_compliance_score=compliance_rollups.get(machine, {}).get("average_compliance_score", 0),
            worst_compliance_category=compliance_rollups.get(machine, {}).get("worst_category", ""),
            open_standards_issues=compliance_rollups.get(machine, {}).get("open_standards_issues", 0),
        )
        if query and not _matches_group(group, query):
            continue
        groups.append(group)
    return sorted(groups, key=lambda group: _machine_sort_key(group.machine))


def press_view_cache_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).cache / "press_view_groups.json"


def save_press_view_cache(project_root: str | Path, groups: list[PressViewGroup]) -> Path:
    path = press_view_cache_path(project_root)
    ensure_directory(path.parent)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "groups": [group.to_dict() for group in groups],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_cached_press_view_groups(project_root: str | Path) -> tuple[list[PressViewGroup], str | None, str | None]:
    path = press_view_cache_path(project_root)
    if not path.exists():
        return [], None, "No cached press view found."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], None, f"Could not read cached press view: {exc}"
    groups_raw = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(groups_raw, list):
        return [], None, "Cached press view did not contain groups."
    groups = [_group_from_dict(group) for group in groups_raw if isinstance(group, dict)]
    return groups, str(payload.get("generated_at") or ""), None


def export_press_summary(project_root: str | Path, machine: str) -> ToolResult:
    started = time.perf_counter()
    groups = build_press_view_groups(project_root)
    group = next((item for item in groups if item.machine == machine), None)
    if group is None:
        return ToolResult.fail("press_view_export", "Press View Summary Export", f"Press/Machine {machine} was not found.")
    lines = [
        f"# {group.display_name} Summary",
        "",
        f"- Physical audits: {len(group.physical_audits)}",
        f"- Compatible entries: {len(group.compatible_entries)}",
        f"- Tools: {', '.join(group.tools) if group.tools else 'None listed'}",
        f"- Open items: {group.open_item_count}",
        f"- Validation warnings: {group.validation_warning_count}",
        f"- Indexed photos: {group.photo_count}",
        f"- Pilot candidacy: {group.pilot_candidacy or 'Not flagged'}",
        f"- Average compliance score: {group.average_compliance_score}",
        f"- Worst compliance category: {group.worst_compliance_category or 'None'}",
        f"- Open standards issues: {group.open_standards_issues}",
        f"- Last updated: {group.last_updated or 'Unknown'}",
        "",
        "## Physical Audits",
    ]
    lines.extend(_entry_lines(group.physical_audits))
    lines.extend(["", "## Compatible Entries"])
    lines.extend(_entry_lines(group.compatible_entries))
    paths = resolve_project_paths(project_root)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_machine = re.sub(r"[^A-Za-z0-9_-]+", "_", machine).strip("_") or "unassigned"
    path = paths.project_admin / "Press_View_Summaries" / f"Press_{safe_machine}_Summary_{stamp}.md"
    try:
        saved = safe_write_text(path, "\n".join(lines).rstrip() + "\n", overwrite=False)
    except Exception as exc:
        return ToolResult.fail("press_view_export", "Press View Summary Export", "Could not export press summary.", errors=[str(exc)])
    result = ToolResult.ok(
        "press_view_export",
        "Press View Summary Export",
        f"Exported {group.display_name} summary.",
        files_created=[str(saved)],
        output_reports=[str(saved)],
        duration_seconds=time.perf_counter() - started,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result


def _entry_from_row(row: dict[str, Any], machine: str) -> PressAuditEntry:
    return PressAuditEntry(
        audit_id=text_value(row.get("Audit ID")),
        machine=machine,
        entry_type=normalize_entry_type(row.get("Entry Type")),
        tool=part_number_from_row(row) or text_value(row.get(TOOL_FIELD)),
        eoat_type=text_value(row.get("EOAT Type")),
        status=text_value(row.get("Status")),
        pilot_candidate=text_value(row.get("Pilot Candidate?")),
        source_audit_id=text_value(row.get("Source Audit ID")),
        last_updated=_date_text(row.get("Audit Date")),
        known_issues=text_value(row.get("Known Issues")),
    )


def _entry_from_dict(data: dict[str, Any]) -> PressAuditEntry:
    return PressAuditEntry(
        audit_id=str(data.get("audit_id") or ""),
        machine=str(data.get("machine") or ""),
        entry_type=str(data.get("entry_type") or ""),
        tool=str(data.get("tool") or ""),
        eoat_type=str(data.get("eoat_type") or ""),
        status=str(data.get("status") or ""),
        pilot_candidate=str(data.get("pilot_candidate") or ""),
        source_audit_id=str(data.get("source_audit_id") or ""),
        last_updated=str(data.get("last_updated") or ""),
        known_issues=str(data.get("known_issues") or ""),
    )


def _group_from_dict(data: dict[str, Any]) -> PressViewGroup:
    physical = [_entry_from_dict(item) for item in data.get("physical_audits", []) if isinstance(item, dict)]
    compatible = [_entry_from_dict(item) for item in data.get("compatible_entries", []) if isinstance(item, dict)]
    return PressViewGroup(
        machine=str(data.get("machine") or ""),
        display_name=str(data.get("display_name") or ""),
        physical_audits=physical,
        compatible_entries=compatible,
        tools=[str(item) for item in data.get("tools", []) if item],
        open_item_count=int(data.get("open_item_count") or 0),
        validation_warning_count=int(data.get("validation_warning_count") or 0),
        photo_count=int(data.get("photo_count") or 0),
        pilot_candidacy=str(data.get("pilot_candidacy") or ""),
        last_updated=str(data.get("last_updated") or ""),
        average_compliance_score=int(data.get("average_compliance_score") or 0),
        worst_compliance_category=str(data.get("worst_compliance_category") or ""),
        open_standards_issues=int(data.get("open_standards_issues") or 0),
    )


def _open_item_counts(project_root: str | Path) -> dict[str, int]:
    try:
        items = list_open_items(project_root, include_resolved=False, include_validation=False)
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for item in items:
        machine = normalize_machine_token(item.machine)
        if machine:
            counts[machine] = counts.get(machine, 0) + 1
    return counts


def _validation_counts(project_root: str | Path) -> dict[str, int]:
    folder = resolve_project_paths(project_root).validation_reports
    if not folder.exists():
        return {}
    payload: dict[str, Any] = {}
    for path in sorted(folder.glob("Foundation_Validation_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            break
        except (OSError, json.JSONDecodeError):
            continue
    counts: dict[str, int] = {}
    for finding in payload.get("findings", []) if isinstance(payload, dict) else []:
        severity = str(finding.get("severity") or "").upper()
        if severity == "INFO":
            continue
        machine = normalize_machine_token(finding.get("machine_number"))
        if machine:
            counts[machine] = counts.get(machine, 0) + 1
    return counts


def _photo_counts(project_root: str | Path) -> dict[str, int]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return {}
    try:
        rows = row_dicts(paths.master_workbook, "Photo Index")
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        machine = normalize_machine_token(row.get("Press/Machine #"))
        if machine:
            counts[machine] = counts.get(machine, 0) + 1
    return counts


def _compliance_rollups(project_root: str | Path) -> dict[str, dict[str, Any]]:
    try:
        summary, error = analyze_standards_compliance(project_root)
    except Exception:
        return {}
    if error or summary is None:
        return {}
    rollups: dict[str, dict[str, Any]] = {}
    for rollup in summary.press_rollups:
        machine = normalize_machine_token(rollup.machine) or rollup.machine
        if machine:
            rollups[machine] = rollup.to_dict()
    return rollups


def _entry_lines(entries: list[PressAuditEntry]) -> list[str]:
    if not entries:
        return ["- None"]
    return [
        f"- {entry.audit_id or '(missing audit id)'} | {entry.entry_type} | {entry.tool or 'no tool'} | {entry.eoat_type or 'no EOAT type'} | {entry.status or 'no status'}"
        for entry in entries
    ]


def _matches_group(group: PressViewGroup, query: str) -> bool:
    needle = query.casefold().strip()
    haystack = " ".join(
        [
            group.machine,
            group.display_name,
            " ".join(group.tools),
            group.pilot_candidacy,
            " ".join(entry.audit_id + " " + entry.status + " " + entry.eoat_type + " " + entry.known_issues for entry in group.physical_audits + group.compatible_entries),
        ]
    ).casefold()
    return needle in haystack


def _pilot_summary(values: list[str]) -> str:
    normalized = [value for value in values if value]
    if any(value.casefold() == "yes" for value in normalized):
        return "Yes"
    if any(value.casefold() == "maybe" for value in normalized):
        return "Maybe"
    if normalized:
        return ", ".join(sorted(set(normalized))[:3])
    return ""


def _display_name(machine: str) -> str:
    if machine == "Unassigned / Missing Press":
        return machine
    if re.search(r"\b(press|machine)\b", machine, flags=re.IGNORECASE):
        return machine
    return f"Press/Machine {machine}"


def _machine_sort_key(machine: str) -> tuple[int, int | str]:
    if machine.isdigit():
        return (0, int(machine))
    return (1, machine.casefold())


def _date_text(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return text_value(value)
