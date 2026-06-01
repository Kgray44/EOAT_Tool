from __future__ import annotations

import time
from pathlib import Path

from .analysis_common import write_timestamped_report
from .audit_progress import generate_audit_progress_report
from .deliverable_check import run_final_deliverable_check
from .documentation_gaps import generate_documentation_gap_report
from .final_handoff import build_final_handoff_package
from .final_summary import generate_final_project_summary
from .issue_analysis import generate_issue_analysis_report
from .kpi_analysis import generate_kpi_dashboard_report
from .logging import log_tool_run
from .mentor_brief import generate_mentor_brief
from .morning_planner import generate_morning_plan
from .paths import resolve_project_paths
from .presentation_export import export_presentation_assets
from .result import ToolResult
from .risk_insights import generate_risk_insights_report
from .validation import run_foundation_validation
from .weekly_summary import generate_weekly_summary

TOOL_ID = "workflow_runner"
TOOL_NAME = "EOAT Workflow Runner"


def _workflow_report(name: str, results: list[ToolResult]) -> str:
    lines = [f"# Workflow Report: {name}", ""]
    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                f"## {index}. {result.tool_name}",
                f"- Status: {'SUCCESS' if result.success else 'FAILED'}",
                f"- Summary: {result.summary}",
            ]
        )
        if result.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in result.warnings[:10])
        if result.errors:
            lines.append("- Errors:")
            lines.extend(f"  - {error}" for error in result.errors[:10])
        if result.output_reports:
            lines.append("- Output reports:")
            lines.extend(f"  - {path}" for path in result.output_reports)
        lines.append("")
    return "\n".join(lines)


def run_workflow(project_root: str | Path, workflow: str, week: int = 1, day: int = 1) -> ToolResult:
    start = time.perf_counter()
    paths = resolve_project_paths(project_root)
    results: list[ToolResult] = []
    normalized = workflow.strip().lower()

    def add(result: ToolResult) -> None:
        results.append(result)

    if normalized == "daily-start":
        add(run_foundation_validation(project_root, write_report=False, log_activity=False))
        add(generate_morning_plan(project_root, week=week, day=day))
    elif normalized == "daily-end":
        add(generate_audit_progress_report(project_root, log_activity=False))
        add(run_foundation_validation(project_root, write_report=True, log_activity=False))
        add(
            ToolResult.ok(
                "daily_summary_command",
                "Daily Summary Command Prep",
                "Run the daily summary tool interactively from Reports or terminal.",
                details=[
                    f'python daily_status_summary.py --project-root "{project_root}" --week {week} --day {day} --interactive'
                ],
            )
        )
    elif normalized == "weekly-review":
        add(generate_audit_progress_report(project_root, log_activity=False))
        add(generate_issue_analysis_report(project_root))
        add(generate_documentation_gap_report(project_root))
        add(generate_kpi_dashboard_report(project_root))
        add(generate_risk_insights_report(project_root, log_activity=False))
        add(generate_weekly_summary(project_root, week=week))
        add(generate_mentor_brief(project_root, days=7))
    elif normalized == "final-review":
        add(run_final_deliverable_check(project_root, log_activity=False))
        add(generate_risk_insights_report(project_root, log_activity=False))
        add(export_presentation_assets(project_root))
        add(generate_final_project_summary(project_root))
        add(build_final_handoff_package(project_root, dry_run=True))
    else:
        return ToolResult.fail(
            TOOL_ID,
            TOOL_NAME,
            f"Unknown workflow: {workflow}",
            errors=["Use daily-start, daily-end, weekly-review, or final-review."],
        )

    failed = [result for result in results if not result.success]
    report = write_timestamped_report(
        paths.validation_reports, f"Workflow_{normalized.replace('-', '_')}", _workflow_report(normalized, results)
    )
    result = ToolResult(
        tool_id=TOOL_ID,
        tool_name=TOOL_NAME,
        success=not failed,
        summary=f"Workflow {normalized} completed with {len(failed)} failed step(s).",
        details=[f"Steps run: {len(results)}", f"Workflow report: {report}"],
        warnings=[warning for item in results for warning in item.warnings],
        errors=[error for item in failed for error in item.errors],
        files_created=[str(report)],
        output_reports=[str(report)],
        metrics={"workflow": normalized, "steps": len(results), "failed_steps": len(failed)},
        duration_seconds=time.perf_counter() - start,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result
