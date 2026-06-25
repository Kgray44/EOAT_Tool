from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analysis_common import write_timestamped_csv, write_timestamped_report
from .atlas_exports import (
    atlas_export_dir,
    export_compatibility_matrix,
    export_documentation_gap_report,
    export_photo_coverage_report,
)
from .atlas_models import AtlasDataBundle
from .safe_files import ensure_directory


@dataclass(frozen=True)
class AtlasReportDefinition:
    report_id: str
    section: str
    name: str
    purpose: str
    output_type: str
    source_data: tuple[str, ...]


def atlas_report_catalog() -> tuple[AtlasReportDefinition, ...]:
    return (
        AtlasReportDefinition("setup.changeover_pdf", "Setup / Changeover", "Generate Changeover Packet PDF", "Build a selected setup/changeover PDF from the packet builder.", "PDF", ("Machine", "Tool/Mold/Part", "EOAT", "Photos")),
        AtlasReportDefinition("setup.summary_sheet", "Setup / Changeover", "Generate Setup Summary Sheet", "Create a concise setup context summary.", "MD", ("Machine", "Tool/Mold/Part", "EOAT")),
        AtlasReportDefinition("setup.qr_labels", "Setup / Changeover", "Generate EOAT QR Label Sheet", "Create QR label planning output when QR is enabled.", "MD", ("EOAT profiles", "QR settings")),
        AtlasReportDefinition("compatibility.csv", "Compatibility", "Export Compatibility Data Table CSV", "Export raw compatibility rows for audit and filtering.", "CSV", ("Compatibility indexes",)),
        AtlasReportDefinition("compatibility.missing_eoat", "Compatibility", "Missing Validated EOAT Report", "List tools and relationships without validated EOAT links.", "CSV", ("Tool records", "EOAT links")),
        AtlasReportDefinition("compatibility.machine_coverage", "Compatibility", "Machine Coverage Report", "Summarize machines with and without EOAT/tool coverage.", "MD", ("Machine profiles",)),
        AtlasReportDefinition("compatibility.tool_coverage", "Compatibility", "Tool Coverage Report", "Summarize tool coverage and missing EOAT links.", "MD", ("Tool profiles",)),
        AtlasReportDefinition("compatibility.relationships", "Compatibility", "EOAT Relationship Report", "Summarize EOAT-machine-tool relationship health.", "MD", ("EOAT profiles", "Compatibility indexes")),
        AtlasReportDefinition("documentation.gaps", "Documentation", "Documentation Gap Report", "Export warnings and missing documentation fields.", "CSV", ("Warnings", "Documentation scores")),
        AtlasReportDefinition("documentation.standards", "Documentation", "Standards Compliance Report", "Summarize standards applicability and review status.", "MD", ("Standards", "EOAT profiles")),
        AtlasReportDefinition("documentation.eoat_summary", "Documentation", "EOAT Summary Report", "Summarize EOAT profile coverage, warnings, photos, and standards.", "MD", ("EOAT profiles",)),
        AtlasReportDefinition("documentation.cad_bom_binder", "Documentation", "EOATs Missing CAD/BOM/Process Binder Info", "List EOAT records missing common handoff fields.", "CSV", ("EOAT profiles", "Documentation fields")),
        AtlasReportDefinition("documentation.missing_photos", "Documentation", "EOATs Missing Photos", "List EOAT records with zero linked photos.", "CSV", ("EOAT profiles", "Photo index")),
        AtlasReportDefinition("photos.coverage", "Photos", "Photo Coverage Report", "Export photo counts, missing categories, and folder status.", "CSV", ("Photo index", "EOAT profiles")),
        AtlasReportDefinition("photos.missing_categories", "Photos", "Photo Missing Categories Report", "List missing required photo categories by EOAT.", "CSV", ("Photo index",)),
        AtlasReportDefinition("photos.broken_links", "Photos", "Broken Photo Links Report", "List indexed photo paths that no longer exist.", "CSV", ("Photo paths",)),
        AtlasReportDefinition("photos.source_folder", "Photos", "Source Folder Status Report", "Summarize source folder availability for photo evidence.", "MD", ("Photo folders",)),
        AtlasReportDefinition("pm.package", "PM / Inspection", "PM Checklist Package", "Generate PM checklist package guidance.", "MD", ("PM guidance", "EOAT profiles")),
        AtlasReportDefinition("pm.inspection_sheet", "PM / Inspection", "EOAT Inspection Sheet", "Create an inspection sheet template from Atlas context.", "MD", ("PM guidance", "Standards")),
        AtlasReportDefinition("pm.readiness", "PM / Inspection", "Maintenance Readiness Report", "Summarize readiness for maintenance and inspection handoff.", "MD", ("EOAT profiles", "Warnings")),
        AtlasReportDefinition("analytics.kpi", "Analytics / Management", "KPI Summary Report", "Summarize key coverage, documentation, photo, and warning metrics.", "MD", ("Atlas metrics",)),
        AtlasReportDefinition("analytics.top_warnings", "Analytics / Management", "Top Warnings Report", "Rank records with the most warnings.", "MD", ("Warnings",)),
        AtlasReportDefinition("analytics.pilot_candidate", "Analytics / Management", "Pilot Candidate Report", "Summarize available pilot-candidate evidence if present.", "MD", ("Pilot evidence", "EOAT profiles")),
        AtlasReportDefinition("analytics.fmea_lite", "Analytics / Management", "FMEA-lite Report", "Summarize warning themes for FMEA-lite review if available.", "MD", ("Warnings", "FMEA context")),
        AtlasReportDefinition("handoff.package", "Final Handoff", "Build Final Handoff Package", "Create a handoff package index and readiness summary.", "MD", ("Atlas metrics", "Reports")),
        AtlasReportDefinition("handoff.executive_summary", "Final Handoff", "Export Executive Summary", "Create a leadership-friendly status summary.", "MD", ("Atlas metrics", "Warnings")),
        AtlasReportDefinition("handoff.presentation_pack", "Final Handoff", "Export Presentation Data Pack", "Create a data-pack index for presentation prep.", "MD", ("Atlas metrics", "Reports")),
    )


def generate_atlas_report(bundle: AtlasDataBundle, report_id: str) -> Path:
    definition = _definition(report_id)
    if report_id == "compatibility.csv":
        return export_compatibility_matrix(bundle)
    if report_id == "documentation.gaps":
        return export_documentation_gap_report(bundle)
    if report_id == "photos.coverage":
        return export_photo_coverage_report(bundle)
    if report_id == "compatibility.missing_eoat":
        return write_timestamped_csv(
            _report_section_dir(bundle, definition),
            "Missing_Validated_EOAT",
            [{"Tool": tool.tool, "Machines": "; ".join(tool.compatible_machines)} for tool in bundle.tools if not tool.compatible_eoats],
        )
    if report_id == "documentation.missing_photos":
        return write_timestamped_csv(
            _report_section_dir(bundle, definition),
            "EOATs_Missing_Photos",
            [{"EOAT": eoat.eoat_id, "Tools": "; ".join(eoat.tools), "Machines": "; ".join(eoat.machines)} for eoat in bundle.eoats if eoat.photo_count <= 0],
        )
    if report_id == "photos.missing_categories":
        return write_timestamped_csv(
            _report_section_dir(bundle, definition),
            "Photo_Missing_Categories",
            [{"EOAT": eoat.eoat_id, "Missing Categories": "; ".join(eoat.photos.missing_categories)} for eoat in bundle.eoats if eoat.photos.missing_categories],
        )
    return write_timestamped_report(_report_section_dir(bundle, definition), _safe_name(definition.name), _generic_report_markdown(bundle, definition))


def latest_atlas_report(bundle: AtlasDataBundle, report_id: str) -> Path | None:
    definition = _definition(report_id)
    folders = [_report_section_dir(bundle, definition), atlas_export_dir(bundle.project_root)]
    files = []
    for folder in folders:
        if folder.exists():
            files.extend(path for path in folder.iterdir() if path.is_file() and _safe_name(definition.name).casefold() in path.stem.casefold())
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def _definition(report_id: str) -> AtlasReportDefinition:
    for definition in atlas_report_catalog():
        if definition.report_id == report_id:
            return definition
    raise KeyError(report_id)


def _report_section_dir(bundle: AtlasDataBundle, definition: AtlasReportDefinition) -> Path:
    return ensure_directory(atlas_export_dir(bundle.project_root) / "Reports_Handoff" / _safe_name(definition.section))


def _generic_report_markdown(bundle: AtlasDataBundle, definition: AtlasReportDefinition) -> str:
    lines = [
        f"# {definition.name}",
        "",
        definition.purpose,
        "",
        f"- Output type: {definition.output_type}",
        f"- Source data: {', '.join(definition.source_data)}",
        f"- EOAT records: {len(bundle.eoats)}",
        f"- Machine records: {len(bundle.machines)}",
        f"- Tool records: {len(bundle.tools)}",
        f"- Open warnings: {len(bundle.warnings) + sum(eoat.warning_count for eoat in bundle.eoats)}",
        "",
        "## Notes",
        "- Generated from the cached EOAT Atlas bundle.",
        "- Source workbooks and photo folders were not modified.",
    ]
    return "\n".join(lines).strip() + "\n"


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "Atlas_Report"


__all__ = [
    "AtlasReportDefinition",
    "atlas_report_catalog",
    "generate_atlas_report",
    "latest_atlas_report",
]
