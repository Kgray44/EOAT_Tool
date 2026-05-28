from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_MASTER_PRESS_LIST_FILE, DEFAULT_PRESS_CAPACITY_FILE, EXPECTED_NUMBERED_FOLDERS, EXPECTED_WORKBOOK_RELATIVE


@dataclass(frozen=True)
class EOATProjectPaths:
    project_root: Path

    @classmethod
    def from_root(cls, project_root: str | Path) -> "EOATProjectPaths":
        return cls(Path(project_root))

    @property
    def master_workbook(self) -> Path:
        return self.project_root.joinpath(*EXPECTED_WORKBOOK_RELATIVE)

    @property
    def robot_info_workbook(self) -> Path:
        return self.master_workbook.parent / "Robot_Info.xlsx"

    @property
    def project_admin(self) -> Path:
        return self.project_root / "00_Project_Admin"

    @property
    def daily_reports(self) -> Path:
        return self.project_admin / "Daily_Status_Reports"

    @property
    def weekly_reports(self) -> Path:
        return self.project_admin / "Weekly_Status_Reports"

    @property
    def validation_reports(self) -> Path:
        return self.project_admin / "Validation_Reports"

    @property
    def activity_logs(self) -> Path:
        return self.project_admin / "Activity_Logs"

    @property
    def logs(self) -> Path:
        return self.project_admin / "logs"

    @property
    def cache(self) -> Path:
        return self.project_admin / "cache"

    @property
    def project_data(self) -> Path:
        return self.project_root / "project_data"

    @property
    def annotations_database(self) -> Path:
        return self.project_data / "annotations.sqlite"

    @property
    def annotation_exports(self) -> Path:
        return self.project_root / "reports" / "exports"

    @property
    def mentor_briefs(self) -> Path:
        return self.project_admin / "Mentor_Briefs"

    @property
    def morning_plans(self) -> Path:
        return self.daily_reports / "Morning_Plans"

    @property
    def audit_root(self) -> Path:
        return self.project_root / "01_EOAT_Audit"

    @property
    def reference_data(self) -> Path:
        return self.project_admin / "reference_data"

    @property
    def legacy_reference_data(self) -> Path:
        return self.project_root / "reference-data"

    @property
    def cell_photos(self) -> Path:
        return self.audit_root / "Cell_Photos"

    @property
    def incoming_photos(self) -> Path:
        return self.cell_photos / "Incoming_Photos"

    @property
    def audit_progress_reports(self) -> Path:
        return self.audit_root / "Audit_Progress_Reports"

    @property
    def issue_analysis_reports(self) -> Path:
        return self.audit_root / "Issue_Analysis_Reports"

    @property
    def kpi_data(self) -> Path:
        return self.project_root / "02_KPI_Data"

    @property
    def kpi_dashboard_exports(self) -> Path:
        return self.kpi_data / "Dashboard_Exports"

    @property
    def standards(self) -> Path:
        return self.project_root / "03_Standards"

    @property
    def documentation_gap_reports(self) -> Path:
        return self.standards / "Documentation_Gap_Reports"

    @property
    def pm_generated_checklists(self) -> Path:
        return self.standards / "PM_Checklist_Draft" / "Generated_Checklists"

    @property
    def bom_standardization_reports(self) -> Path:
        return self.standards / "BOM_Template_Draft" / "BOM_Standardization_Reports"

    @property
    def fmea(self) -> Path:
        return self.project_root / "04_FMEA"

    @property
    def fmea_reports(self) -> Path:
        return self.fmea / "FMEA_Reports"

    @property
    def pilot_project(self) -> Path:
        return self.project_root / "05_Pilot_Project"

    @property
    def final_handoff(self) -> Path:
        return self.project_root / "06_Final_Handoff"

    @property
    def presentation_assets_root(self) -> Path:
        return self.final_handoff / "Presentation" / "Auto_Exported_Content"

    @property
    def handoff_package_root(self) -> Path:
        return self.final_handoff / "Handoff_Package"

    @property
    def final_report(self) -> Path:
        return self.final_handoff / "Final_Report"

    @property
    def risk_insights_reports(self) -> Path:
        return self.final_handoff / "Risk_Insights"

    @property
    def executive_summary(self) -> Path:
        return self.final_handoff / "Executive_Summary"

    @property
    def training_materials(self) -> Path:
        return self.final_handoff / "Training_Materials"

    def expected_numbered_folders(self) -> list[Path]:
        return [self.project_root / folder for folder in EXPECTED_NUMBERED_FOLDERS]


def resolve_project_paths(project_root: str | Path) -> EOATProjectPaths:
    return EOATProjectPaths.from_root(project_root)


def get_reference_data_dir(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).reference_data


def get_press_capacity_file(project_root: str | Path) -> Path:
    return get_reference_data_dir(project_root) / DEFAULT_PRESS_CAPACITY_FILE


def get_master_press_list_file(project_root: str | Path) -> Path:
    return get_reference_data_dir(project_root) / DEFAULT_MASTER_PRESS_LIST_FILE


def validate_looks_like_eoat_project_root(project_root: str | Path) -> tuple[bool, list[str]]:
    paths = resolve_project_paths(project_root)
    missing: list[str] = []
    if not paths.project_root.exists():
        missing.append(f"Project root does not exist: {paths.project_root}")
    for folder in paths.expected_numbered_folders():
        if not folder.exists():
            missing.append(f"Missing expected folder: {folder.name}")
    if not paths.master_workbook.exists():
        missing.append(f"Missing master workbook: {paths.master_workbook}")
    return not missing, missing
