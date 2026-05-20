from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .workbook_io import row_dicts

MISSING_DATA_FIELDS = [
    "Robot Type",
    "EOAT Type",
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
    eoat_type_counts: dict[str, int] = field(default_factory=dict)
    robot_type_counts: dict[str, int] = field(default_factory=dict)
    issue_category_counts: dict[str, int] = field(default_factory=dict)
    missing_field_counts: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = [
            "# EOAT Audit Progress Report",
            "",
            "## Summary",
            f"- Total EOAT inventory rows: {self.metrics.get('total_eoat_inventory_rows', 0)}",
            f"- Audited EOAT count: {self.metrics.get('audited_eoat_count', 0)}",
            f"- Needs follow-up count: {self.metrics.get('needs_followup_count', 0)}",
            f"- Pilot candidates: {self.metrics.get('pilot_candidate_yes_count', 0)} yes, {self.metrics.get('pilot_candidate_maybe_count', 0)} maybe",
            "",
            "## Key Metrics",
        ]
        for key, value in self.metrics.items():
            lines.append(f"- {key}: {value}")
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


def _count_status(rows: list[dict[str, Any]], status_value: str) -> int:
    return sum(1 for row in rows if str(row.get("Status") or "").strip().lower() == status_value.lower())


def _truthy_yes(value: Any) -> bool:
    return str(value or "").strip().lower() == "yes"


def calculate_audit_progress(project_root: str | Path) -> tuple[AuditProgressSummary | None, ToolResult | None]:
    paths = resolve_project_paths(project_root)
    workbook_path = paths.master_workbook
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

    missing_counts = {
        field: sum(1 for row in inventory if not str(row.get(field) or "").strip())
        for field in MISSING_DATA_FIELDS
    }
    open_statuses = {"open", "not started", "needs follow-up", "in progress", "blocked"}
    metrics = {
        "total_eoat_inventory_rows": len(inventory),
        "audited_eoat_count": _count_status(inventory, "Audited"),
        "not_audited_count": _count_status(inventory, "Not audited"),
        "needs_followup_count": _count_status(inventory, "Needs follow-up"),
        "candidate_for_pilot_count": _count_status(inventory, "Candidate for pilot"),
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
    summary = AuditProgressSummary(
        metrics=metrics,
        eoat_type_counts=dict(Counter(str(row.get("EOAT Type") or "Blank") for row in inventory)),
        robot_type_counts=dict(Counter(str(row.get("Robot Type") or "Blank") for row in inventory)),
        issue_category_counts=dict(Counter(str(row.get("Issue Category") or "Blank") for row in issues)),
        missing_field_counts=missing_counts,
    )
    return summary, None


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

