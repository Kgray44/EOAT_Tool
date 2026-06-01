from __future__ import annotations

import json
from pathlib import Path

from core.paths import resolve_project_paths

from .fake_config import create_fake_config
from .fake_images import create_fake_images
from .fake_workbook import create_fake_master_workbook


def create_fake_eoat_project(temp_dir: str | Path, *, minimal: bool = False, with_photos: bool = True) -> Path:
    root = Path(temp_dir) / "Fake_EOAT_Standardization_Project"
    paths = resolve_project_paths(root)

    for folder in [
        paths.project_admin,
        paths.daily_reports,
        paths.weekly_reports,
        paths.validation_reports,
        paths.activity_logs,
        paths.mentor_briefs,
        paths.morning_plans,
        paths.audit_root,
        paths.master_workbook.parent,
        paths.cell_photos,
        paths.incoming_photos,
        paths.audit_progress_reports,
        paths.issue_analysis_reports,
        paths.kpi_data,
        paths.kpi_dashboard_exports,
        paths.standards,
        paths.documentation_gap_reports,
        paths.pm_generated_checklists,
        paths.bom_standardization_reports,
        paths.fmea,
        paths.fmea_reports,
        paths.pilot_project,
        paths.pilot_project / "Candidate_Cells",
        paths.final_handoff,
        paths.annotation_exports,
        paths.presentation_assets_root,
        paths.handoff_package_root,
        paths.final_report,
        paths.executive_summary,
        paths.training_materials,
        paths.project_admin / "Backups",
        paths.reference_data,
        root / "Reports",
        root / "Backups",
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    if not minimal:
        create_fake_master_workbook(paths.master_workbook)
        _write_schedule_files(root)
        if with_photos:
            create_fake_images(paths.incoming_photos)
        _write_seed_reports(root)
        create_fake_config(root, paths.project_admin / "fake_user_config.json")
    return root


def create_minimal_fake_project(temp_dir: str | Path) -> Path:
    return create_fake_eoat_project(temp_dir, minimal=True, with_photos=False)


def _write_schedule_files(root: Path) -> None:
    admin = root / "00_Project_Admin"
    week1_schedule = {
        "week": 1,
        "days": {
            "1": [
                "Confirm project folder structure and workbook access",
                "Review EOAT Command Center with mentor",
                "Start Press 101 baseline audit",
            ],
            "2": [
                "Audit Press 102 gripper EOAT",
                "Intake photos from Press 101 and Press 102",
                "Run workbook validation after Day 2 data entry",
                "Draft questions for maintenance about vacuum loss",
            ],
            "3": ["Continue EOAT audit sweep"],
            "4": ["Review documentation gaps"],
            "5": ["Generate Week 1 summary"],
        },
    }
    week1_progress = {
        "week": 1,
        "tasks": [
            {
                "id": "W1D1T1",
                "day": "1",
                "task": "Confirm project folder structure and workbook access",
                "status": "Complete",
                "evidence": ["Fake Week 1 Day 1 summary"],
            },
            {
                "id": "W1D1T2",
                "day": "1",
                "task": "Review EOAT Command Center with mentor",
                "status": "In progress",
            },
            {
                "id": "W1D1T3",
                "day": "1",
                "task": "Start Press 101 baseline audit",
                "status": "Blocked",
                "evidence": ["Need production window"],
            },
            {
                "id": "W1D2T1",
                "day": "2",
                "task": "Audit Press 102 gripper EOAT",
                "status": "Not started",
            },
            {
                "id": "W1D2T2",
                "day": "2",
                "task": "Intake photos from Press 101 and Press 102",
                "status": "Not started",
            },
            {
                "id": "W1D2T3",
                "day": "2",
                "task": "Run workbook validation after Day 2 data entry",
                "status": "Not started",
            },
            {
                "id": "W1D4STRETCH1",
                "day": "4",
                "task": "Future stretch task: compare BOM common components",
                "status": "Not started",
            },
        ],
    }
    week2_schedule = {
        "week": 2,
        "days": {
            "1": ["Continue audit sweep"],
            "2": ["Run issue analysis with mentor"],
            "3": ["Draft first PM checklist"],
            "4": ["Review KPI baseline"],
            "5": ["Generate weekly summary"],
        },
    }
    week2_progress = {
        "week": 2,
        "tasks": [
            {"id": "W2D1T1", "day": "1", "task": "Continue audit sweep", "status": "Not started"},
            {
                "id": "W2D5STRETCH1",
                "day": "5",
                "task": "Future stretch task: prepare pilot candidate review",
                "status": "Not started",
            },
        ],
    }
    for name, data in {
        "project_schedule_week1.json": week1_schedule,
        "task_progress_week1.json": week1_progress,
        "project_schedule_week2.json": week2_schedule,
        "task_progress_week2.json": week2_progress,
    }.items():
        (admin / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_seed_reports(root: Path) -> None:
    paths = resolve_project_paths(root)
    (paths.daily_reports / "Week1_Day1_Activity_Summary_2026-05-18.md").write_text(
        "# Week 1 Day 1 Activity Summary\n\n- Completed project setup review.\n- Blocker: production window for Press 101.\n",
        encoding="utf-8",
    )
    (paths.daily_reports / "Week1_Day1_Activity_Summary_2026-05-18.json").write_text(
        json.dumps(
            {"week": 1, "day": 1, "completed": ["Project setup review"], "blocked": ["Press 101 access"]}, indent=2
        ),
        encoding="utf-8",
    )
    (paths.validation_reports / "Foundation_Validation_2026-05-18_0800.md").write_text(
        "# Foundation Validation\n\nSynthetic prior validation report.\n",
        encoding="utf-8",
    )
    (paths.issue_analysis_reports / "Issue_Analysis_2026-05-18_0800.md").write_text(
        "# Issue Analysis\n\nSynthetic older issue report.\n",
        encoding="utf-8",
    )
    (paths.weekly_reports / "Week1_Summary_2026-05-18.md").write_text(
        "# Week 1 Summary\n\nSynthetic older weekly summary.\n",
        encoding="utf-8",
    )
