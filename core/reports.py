from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import resolve_project_paths


@dataclass(frozen=True)
class ReportFolder:
    label: str
    path: Path
    exists: bool
    recent_files: list[Path]


REPORT_EXTENSIONS = {".md", ".txt", ".json", ".docx", ".pdf", ".csv", ".png", ".xlsx", ".pptx"}
PREVIEW_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".log", ".jsonl"}


def list_recent_files(folder: str | Path, limit: int = 8) -> list[Path]:
    path = Path(folder)
    if not path.exists() or not path.is_dir():
        return []
    files = [
        item
        for item in path.iterdir()
        if item.is_file() and (not REPORT_EXTENSIONS or item.suffix.lower() in REPORT_EXTENSIONS)
    ]
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)[:limit]


def report_folders(project_root: str | Path, limit: int = 8) -> list[ReportFolder]:
    paths = resolve_project_paths(project_root)
    folders = [
        ("Daily Status Reports", paths.daily_reports),
        ("Weekly Status Reports", paths.weekly_reports),
        ("Validation Reports", paths.validation_reports),
        ("Issue Analysis Reports", paths.issue_analysis_reports),
        ("Documentation Gap Reports", paths.documentation_gap_reports),
        ("PM Generated Checklists", paths.pm_generated_checklists),
        ("BOM Standardization Reports", paths.bom_standardization_reports),
        ("FMEA Reports", paths.fmea_reports),
        ("Pilot Candidate Reports", paths.pilot_project / "Candidate_Cells"),
        ("KPI Dashboard Exports", paths.kpi_dashboard_exports),
        ("Audit Progress Reports", paths.audit_progress_reports),
        ("Mentor Briefs", paths.mentor_briefs),
        ("Morning Plans", paths.morning_plans),
        ("Presentation Assets", paths.presentation_assets_root),
        ("Final Report Drafts", paths.final_report),
        ("Handoff Packages", paths.handoff_package_root),
        ("Executive Summary", paths.executive_summary),
        ("Training Materials", paths.training_materials),
        ("Backups", paths.project_admin / "Backups"),
        ("Activity Logs", paths.activity_logs),
    ]
    return [
        ReportFolder(label=label, path=path, exists=path.exists(), recent_files=list_recent_files(path, limit))
        for label, path in folders
    ]


def read_report_preview(path: str | Path, max_chars: int = 30000) -> tuple[str, str | None]:
    report = Path(path)
    if not report.exists():
        return "", f"Report does not exist: {report}"
    if report.suffix.lower() not in PREVIEW_EXTENSIONS:
        return "", f"Preview is only available for text-like files: {report.name}"
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "", str(exc)
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n[Preview truncated.]", None
    return text, None
