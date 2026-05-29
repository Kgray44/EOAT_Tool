from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit_compatibility import (
    load_required_relationships,
    normalize_entry_type,
    parse_machine_tokens,
    part_number_from_row,
    relationship_has_conflict,
    sort_machine_tokens,
    summarize_master_relationships,
    text_value,
)
from .audit.relationships import is_compatibility_row, is_physical_audit_row
from .audit_constants import ENTRY_TYPE_AUDITED, ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from .audit_field_rules import field_applies, is_na_value, manual_completion_override_enabled
from .logging import log_tool_run
from .paths import get_press_capacity_file, resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .workbook_cache import row_dicts_cached as row_dicts
from .gripper_fields import CUP_COUNT_FIELD

MISSING_DATA_FIELDS = [
    "Robot Type",
    "EOAT Type",
    "EOAT Moves",
    CUP_COUNT_FIELD,
    "Tubing Condition",
    "Cable Management Condition",
    "Known Issues",
    "Photos Taken?",
    "Status",
    "Priority",
]


@dataclass
class AuditProgressSummary:
    metrics: dict[str, Any]
    metric_labels: dict[str, str] = field(default_factory=dict)
    coverage_summary: list[tuple[str, Any]] = field(default_factory=list)
    missing_relationships: list[dict[str, Any]] = field(default_factory=list)
    compatibility_opportunities: list[dict[str, Any]] = field(default_factory=list)
    machine_coverage: list[dict[str, Any]] = field(default_factory=list)
    entry_type_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    eoat_type_counts: dict[str, int] = field(default_factory=dict)
    robot_type_counts: dict[str, int] = field(default_factory=dict)
    issue_category_counts: dict[str, int] = field(default_factory=dict)
    missing_field_counts: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = [
            "# EOAT Audit Progress Report",
            "",
            "## Summary",
            "Physical audit rows are direct audit observations. Compatible relationship rows extend coverage from a source physical audit without implying the EOAT was physically audited on that press.",
            f"- Required Machine/Part Relationships: {self.metrics.get('required_relationships', 0)}",
            f"- Physical Audit Rows: {self.metrics.get('physical_audit_rows', 0)}",
            f"- Physically Audited Relationships: {self.metrics.get('physically_audited_relationships', 0)}",
            f"- Compatible Relationship Rows: {self.metrics.get('compatible_relationships', 0)}",
            f"- Covered Relationships: {self.metrics.get('total_covered_relationships', 0)}",
            f"- Remaining Relationships: {self.metrics.get('remaining_relationships', 0)}",
            f"- Pilot candidates: {self.metrics.get('pilot_candidate_yes_count', 0)} yes, {self.metrics.get('pilot_candidate_maybe_count', 0)} maybe",
            "",
            "## Coverage Summary",
        ]
        lines.extend(_table_from_rows(["Metric", "Count"], [{"Metric": label, "Count": value} for label, value in self.coverage_summary]))
        if self.warnings:
            lines.extend(["", "## Warnings"])
            lines.extend(f"- {warning}" for warning in self.warnings)
        lines.extend(["", "## Missing Relationships"])
        lines.extend(_table_from_rows(["Machine No.", "NGW Part Number", "NGW Part Description", "Reason Missing", "Suggested Next Action"], self.missing_relationships))
        lines.extend(["", "## Compatibility Opportunities"])
        lines.extend(_table_from_rows(["NGW Part Number", "NGW Part Description", "Source Audited Machine", "Compatible Missing Machines", "Suggested Action"], self.compatibility_opportunities))
        lines.extend(["", "## Machine Coverage"])
        lines.extend(_table_from_rows(["Machine No.", "Required Relationships", "Audited", "Compatible", "Covered Total", "Remaining", "Coverage %"], self.machine_coverage))
        lines.extend(["", "## Existing Entries by Type"])
        lines.extend(_table_from_counts(self.entry_type_counts))
        lines.extend(["", "## Audit Coverage By EOAT Type"])
        lines.extend(_table_from_counts(self.eoat_type_counts))
        lines.extend(["", "## Audit Coverage By Robot Type"])
        lines.extend(_table_from_counts(self.robot_type_counts))
        lines.extend(["", "## Issues By Category"])
        lines.extend(_table_from_counts(self.issue_category_counts))
        lines.extend(["", "## Missing Data Summary"])
        lines.extend(_table_from_counts(self.missing_field_counts))
        lines.extend(
            [
                "",
                "## Recommended Next Cleanup Actions",
                "- Fill missing required audit fields for high-priority or pilot-candidate cells.",
                "- Add photos for audited EOATs where Photos Taken? is blank or No.",
                "- Convert repeated known issues into Issue Log entries.",
                "- Review open action items before the next mentor check-in.",
            ]
        )
        return "\n".join(lines) + "\n"


def _table_from_counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["No data yet."]
    lines = ["| Item | Count |", "| --- | ---: |"]
    for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key or 'Blank'} | {value} |")
    return lines


def _table_from_rows(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No data yet."]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _column in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def _count_status(rows: list[dict[str, Any]], status_value: str) -> int:
    return sum(1 for row in rows if str(row.get("Status") or "").strip().lower() == status_value.lower())


def _truthy_yes(value: Any) -> bool:
    return str(value or "").strip().lower() == "yes"


METRIC_LABELS = {
    "required_relationships": "Required Machine/Part Relationships",
    "physically_audited_relationships": "Physically Audited Relationships",
    "compatible_relationships": "Compatible Relationships",
    "total_covered_relationships": "Total Covered Relationships",
    "remaining_relationships": "Remaining Relationships",
    "physical_audit_rows": "Physical Audit Rows",
    "compatibility_rows": "Compatible Relationship Rows",
    "duplicate_relationship_rows": "Duplicate Relationship Rows",
    "conflict_rows": "Conflict Rows",
    "machines_with_full_coverage": "Machines With Full Coverage",
    "machines_with_partial_coverage": "Machines With Partial Coverage",
    "machines_with_no_coverage": "Machines With No Coverage",
    "parts_with_at_least_one_physical_audit": "Parts/Tools With At Least One Physical Audit",
    "parts_still_needing_first_physical_audit": "Parts/Tools Still Needing First Physical Audit",
    "compatibility_opportunities_available": "Compatibility Opportunities Available",
    "total_eoat_inventory_rows": "Total EOAT Inventory Rows",
    "photos_indexed_count": "Photos Indexed",
    "interviews_logged_count": "Interviews Logged",
    "issues_logged_count": "Issues Logged",
    "open_action_items_count": "Open Action Items",
}


def calculate_audit_progress(
    project_root_or_master_audit_path: str | Path,
    press_capacity_path: str | Path | None = None,
) -> tuple[AuditProgressSummary | None, ToolResult | None]:
    input_path = Path(project_root_or_master_audit_path)
    if input_path.suffix.lower() in {".xlsx", ".xlsm"}:
        workbook_path = input_path
        capacity_path = Path(press_capacity_path) if press_capacity_path else workbook_path.parent / "press_capacity.xlsx"
        project_root: Path | None = None
    else:
        paths = resolve_project_paths(input_path)
        workbook_path = paths.master_workbook
        capacity_path = Path(press_capacity_path) if press_capacity_path else get_press_capacity_file(input_path)
        project_root = input_path
    if not workbook_path.exists():
        return None, ToolResult.fail(
            "audit_progress_dashboard",
            "EOAT Audit Progress Dashboard Tool",
            "Master workbook is missing.",
            errors=[str(workbook_path)],
        )
    try:
        inventory = row_dicts(workbook_path, "EOAT Inventory")
        issues = row_dicts(workbook_path, "Issue Log")
        interviews = row_dicts(workbook_path, "Interview Notes")
        photos = row_dicts(workbook_path, "Photo Index")
        actions = row_dicts(workbook_path, "Action Items")
        pilots = row_dicts(workbook_path, "Pilot Candidates")
    except Exception as exc:
        return None, ToolResult.fail(
            "audit_progress_dashboard",
            "EOAT Audit Progress Dashboard Tool",
            "Could not read workbook.",
            errors=[str(exc)],
        )

    summary = calculate_audit_progress_from_rows(inventory, capacity_path, issues=issues, interviews=interviews, photos=photos, actions=actions, pilots=pilots)
    if project_root is None:
        return summary, None
    return summary, None


def calculate_audit_progress_from_workbooks(master_audit_path: str | Path, press_capacity_path: str | Path) -> AuditProgressSummary:
    inventory = row_dicts(master_audit_path, "EOAT Inventory")
    issues = row_dicts(master_audit_path, "Issue Log")
    interviews = row_dicts(master_audit_path, "Interview Notes")
    photos = row_dicts(master_audit_path, "Photo Index")
    actions = row_dicts(master_audit_path, "Action Items")
    pilots = row_dicts(master_audit_path, "Pilot Candidates")
    return calculate_audit_progress_from_rows(inventory, press_capacity_path, issues=issues, interviews=interviews, photos=photos, actions=actions, pilots=pilots)


def calculate_audit_progress_from_rows(
    inventory: list[dict[str, Any]],
    press_capacity_path: str | Path,
    *,
    issues: list[dict[str, Any]] | None = None,
    interviews: list[dict[str, Any]] | None = None,
    photos: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
    pilots: list[dict[str, Any]] | None = None,
) -> AuditProgressSummary:
    issues = issues or []
    interviews = interviews or []
    photos = photos or []
    actions = actions or []
    pilots = pilots or []
    required_relationships, warnings = load_required_relationships(press_capacity_path)
    required_by_key = {relationship.key: relationship for relationship in required_relationships}
    required_keys = set(required_by_key)
    master_by_key = summarize_master_relationships(inventory)
    audited_keys = {
        key
        for key, rows in master_by_key.items()
        if key in required_keys and any(row["entry_type"] == ENTRY_TYPE_AUDITED for row in rows)
    }
    compatible_keys = {
        key
        for key, rows in master_by_key.items()
        if key in required_keys and any(row["entry_type"] == ENTRY_TYPE_COMPATIBLE for row in rows)
    }
    covered_keys = audited_keys | compatible_keys
    missing_keys = required_keys - covered_keys
    audited_part_sources: dict[str, list[str]] = defaultdict(list)
    physical_audit_rows = 0
    compatibility_rows = 0
    unknown_treated_as_audited = 0
    for row in inventory:
        if is_compatibility_row(row):
            compatibility_rows += 1
        else:
            physical_audit_rows += 1
            if not text_value(row.get(ENTRY_TYPE_FIELD)):
                unknown_treated_as_audited += 1
            part_number = part_number_from_row(row)
            machines = parse_machine_tokens(row.get("Press/Machine #"))
            if part_number and machines and is_physical_audit_row(row):
                audited_part_sources[text_value(part_number).upper()].extend(machines)

    duplicate_rows = _duplicate_relationship_rows(master_by_key)
    conflict_rows = _conflict_rows(master_by_key, required_by_key)
    machine_coverage = _machine_coverage(required_relationships, audited_keys, compatible_keys, covered_keys)
    missing_relationships = _missing_relationship_rows(missing_keys, required_by_key, audited_part_sources)
    compatibility_opportunities = _compatibility_opportunity_rows(missing_keys, required_by_key, audited_part_sources)
    required_parts = {key[1] for key in required_keys}
    audited_parts = set(audited_part_sources) & required_parts if required_parts else set(audited_part_sources)

    missing_counts = {
        field: sum(
            1
            for row in inventory
            if not manual_completion_override_enabled(row)
            and field_applies(row, field)
            and _missing_applicable_value(row.get(field))
        )
        for field in MISSING_DATA_FIELDS
    }
    open_statuses = {"open", "not started", "needs follow-up", "in progress", "blocked"}
    metrics = {
        "required_relationships": len(required_keys),
        "physically_audited_relationships": len(audited_keys),
        "compatible_relationships": len(compatible_keys),
        "total_covered_relationships": len(covered_keys),
        "remaining_relationships": len(missing_keys),
        "physical_audit_rows": physical_audit_rows,
        "compatibility_rows": compatibility_rows,
        "duplicate_relationship_rows": duplicate_rows,
        "conflict_rows": conflict_rows,
        "machines_with_full_coverage": sum(1 for row in machine_coverage if row["Remaining"] == 0 and row["Required Relationships"] > 0),
        "machines_with_partial_coverage": sum(1 for row in machine_coverage if 0 < row["Covered Total"] < row["Required Relationships"]),
        "machines_with_no_coverage": sum(1 for row in machine_coverage if row["Covered Total"] == 0 and row["Required Relationships"] > 0),
        "parts_with_at_least_one_physical_audit": len(audited_parts),
        "parts_still_needing_first_physical_audit": len(required_parts - audited_parts),
        "compatibility_opportunities_available": len([row for row in missing_relationships if row["Suggested Next Action"] == "Use Compatibility Entry"]),
        "total_eoat_inventory_rows": len(inventory),
        "audited_eoat_count": len(audited_keys) if required_keys else physical_audit_rows,
        "needs_followup_count": _count_status(inventory, "Needs follow-up"),
        "pilot_candidate_yes_count": sum(1 for row in inventory if str(row.get("Pilot Candidate?") or "").lower() == "yes"),
        "pilot_candidate_maybe_count": sum(1 for row in inventory if str(row.get("Pilot Candidate?") or "").lower() == "maybe"),
        "photos_indexed_count": len(photos),
        "interviews_logged_count": len(interviews),
        "issues_logged_count": len(issues),
        "open_issues_count": sum(1 for row in issues if str(row.get("Status") or "").strip().lower() in open_statuses),
        "open_action_items_count": sum(1 for row in actions if str(row.get("Status") or "").strip().lower() in open_statuses),
        "blocked_or_in_progress_action_items_count": sum(1 for row in actions if str(row.get("Status") or "").strip().lower() in {"blocked", "in progress"}),
        "pilot_candidates_sheet_rows": len(pilots),
        "missing_important_fields_total": sum(missing_counts.values()),
    }
    coverage_summary = [(METRIC_LABELS[key], metrics[key]) for key in METRIC_LABELS if key in metrics]
    summary = AuditProgressSummary(
        metrics=metrics,
        metric_labels=METRIC_LABELS,
        coverage_summary=coverage_summary,
        missing_relationships=missing_relationships,
        compatibility_opportunities=compatibility_opportunities,
        machine_coverage=machine_coverage,
        entry_type_counts={
            ENTRY_TYPE_AUDITED: physical_audit_rows - unknown_treated_as_audited,
            ENTRY_TYPE_COMPATIBLE: compatibility_rows,
            "Unknown treated as Audited": unknown_treated_as_audited,
        },
        warnings=warnings,
        eoat_type_counts=dict(Counter(str(row.get("EOAT Type") or "Blank") for row in inventory)),
        robot_type_counts=dict(Counter(str(row.get("Robot Type") or "Blank") for row in inventory)),
        issue_category_counts=dict(Counter(str(row.get("Issue Category") or "Blank") for row in issues)),
        missing_field_counts=missing_counts,
    )
    return summary


def _missing_applicable_value(value: Any) -> bool:
    return not text_value(value) or is_na_value(value)


def _duplicate_relationship_rows(master_by_key: dict[tuple[str, str], list[dict[str, Any]]]) -> int:
    return sum(len(rows) - 1 for rows in master_by_key.values() if len(rows) > 1)


def _conflict_rows(master_by_key: dict[tuple[str, str], list[dict[str, Any]]], required_by_key: dict[tuple[str, str], Any]) -> int:
    total = 0
    for key, rows in master_by_key.items():
        if relationship_has_conflict(rows, required_by_key.get(key)):
            total += len(rows)
    return total


def _machine_coverage(required_relationships, audited_keys: set[tuple[str, str]], compatible_keys: set[tuple[str, str]], covered_keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    by_machine: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for relationship in required_relationships:
        by_machine[relationship.machine_no].add(relationship.key)
    rows: list[dict[str, Any]] = []
    for machine in sort_machine_tokens(list(by_machine)):
        required = by_machine[machine]
        audited = len(required & audited_keys)
        compatible = len(required & compatible_keys)
        covered = len(required & covered_keys)
        remaining = len(required) - covered
        coverage = round((covered / len(required)) * 100, 1) if required else 0
        rows.append(
            {
                "Machine No.": machine,
                "Required Relationships": len(required),
                "Audited": audited,
                "Compatible": compatible,
                "Covered Total": covered,
                "Remaining": remaining,
                "Coverage %": f"{coverage:g}%",
            }
        )
    return rows


def _missing_relationship_rows(missing_keys: set[tuple[str, str]], required_by_key: dict[tuple[str, str], Any], audited_part_sources: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for machine, part in sorted(missing_keys, key=lambda key: ((0, int(key[0])) if key[0].isdigit() else (1, key[0]), key[1])):
        relationship = required_by_key[(machine, part)]
        has_source = part in audited_part_sources
        rows.append(
            {
                "Machine No.": machine,
                "NGW Part Number": relationship.part_number,
                "NGW Part Description": relationship.part_description,
                "Reason Missing": "No master audit relationship row found.",
                "Suggested Next Action": "Use Compatibility Entry" if has_source else "Needs Physical Audit",
            }
        )
    return rows


def _compatibility_opportunity_rows(missing_keys: set[tuple[str, str]], required_by_key: dict[tuple[str, str], Any], audited_part_sources: dict[str, list[str]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for machine, part in missing_keys:
        if part not in audited_part_sources:
            continue
        relationship = required_by_key[(machine, part)]
        grouped.setdefault(
            part,
            {
                "NGW Part Number": relationship.part_number,
                "NGW Part Description": relationship.part_description,
                "Source Audited Machine": ", ".join(sort_machine_tokens(audited_part_sources[part])),
                "Compatible Missing Machines": [],
                "Suggested Action": "Use Compatibility Entry",
            },
        )
        grouped[part]["Compatible Missing Machines"].append(machine)
    rows = []
    for row in grouped.values():
        row["Compatible Missing Machines"] = ", ".join(sort_machine_tokens(row["Compatible Missing Machines"]))
        rows.append(row)
    return sorted(rows, key=lambda row: str(row["NGW Part Number"]))


def generate_audit_progress_report(project_root: str | Path, log_activity: bool = True) -> ToolResult:
    summary, error = calculate_audit_progress(project_root)
    if error:
        return error
    assert summary is not None
    paths = resolve_project_paths(project_root)
    ensure_directory(paths.audit_progress_reports)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    report_path = paths.audit_progress_reports / f"Audit_Progress_{stamp}.md"
    try:
        try:
            output = safe_write_text(report_path, summary.to_markdown(), overwrite=False)
        except FileExistsError:
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            output = safe_write_text(paths.audit_progress_reports / f"Audit_Progress_{stamp}.md", summary.to_markdown(), overwrite=False)
    except Exception as exc:
        return ToolResult.fail(
            "audit_progress_dashboard",
            "EOAT Audit Progress Dashboard Tool",
            "Could not write audit progress report.",
            errors=[str(exc)],
        )
    result = ToolResult.ok(
        "audit_progress_dashboard",
        "EOAT Audit Progress Dashboard Tool",
        "Generated audit progress report.",
        details=["Calculated audit progress metrics.", f"Report: {output}"],
        files_created=[str(output)],
        output_reports=[str(output)],
        metrics=summary.metrics,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result
