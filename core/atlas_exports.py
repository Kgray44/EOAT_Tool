from __future__ import annotations

from pathlib import Path

from .analysis_common import write_timestamped_csv, write_timestamped_report
from .atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, RecommendationResult
from .compatibility_engine import compatibility_matrix_rows
from .paths import resolve_project_paths
from .safe_files import ensure_directory


def atlas_export_dir(project_root: str | Path) -> Path:
    return ensure_directory(resolve_project_paths(project_root).final_handoff / "Atlas_Exports")


def export_compatibility_matrix(bundle: AtlasDataBundle, *, mode: str = "eoat_machine") -> Path:
    rows = compatibility_matrix_rows(bundle, mode=mode)
    return write_timestamped_csv(atlas_export_dir(bundle.project_root), f"Atlas_Compatibility_{mode}", rows)


def export_documentation_gap_report(bundle: AtlasDataBundle) -> Path:
    rows = []
    for warning in bundle.warnings:
        rows.append(
            {
                "Severity": warning.severity,
                "Title": warning.title,
                "Message": warning.message,
                "Source": warning.source,
                "EOAT": warning.related_eoat_id,
                "Machine": warning.machine,
                "Tool": warning.tool,
                "Suggested Fix": warning.suggested_fix,
            }
        )
    for eoat in bundle.eoats:
        for warning in eoat.warnings:
            rows.append(
                {
                    "Severity": warning.severity,
                    "Title": warning.title,
                    "Message": warning.message,
                    "Source": warning.source,
                    "EOAT": warning.related_eoat_id or eoat.eoat_id,
                    "Machine": warning.machine,
                    "Tool": warning.tool,
                    "Suggested Fix": warning.suggested_fix,
                }
            )
    return write_timestamped_csv(atlas_export_dir(bundle.project_root), "Atlas_Documentation_Gaps", rows)


def export_photo_coverage_report(bundle: AtlasDataBundle) -> Path:
    rows = [
        {
            "EOAT": eoat.eoat_id,
            "Photo Count": eoat.photo_count,
            "Folder": eoat.photos.folder_path,
            "Folder Exists": eoat.photos.folder_exists,
            "Missing Categories": "; ".join(eoat.photos.missing_categories),
        }
        for eoat in bundle.eoats
    ]
    return write_timestamped_csv(atlas_export_dir(bundle.project_root), "Atlas_Photo_Coverage", rows)


def export_eoat_summary(bundle: AtlasDataBundle, eoat: EOATRecord) -> Path:
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in eoat.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# EOAT Summary: {eoat.eoat_id}",
            "",
            f"- EOAT Type: {eoat.eoat_type}",
            f"- Status: {eoat.status}",
            f"- Tools: {', '.join(eoat.tools)}",
            f"- Machines: {', '.join(eoat.machines)}",
            f"- Connection: {eoat.connection_type}",
            f"- Documentation: {eoat.documentation.score}% ({eoat.documentation.status_label})",
            f"- Photos: {eoat.photo_count}",
            "",
            "## Install Checklist",
            "- Verify EOAT ID and tool/machine compatibility.",
            "- Inspect cups, grippers, tubing, sensors, quick disconnects, and mounting hardware as applicable.",
            "- Review all warnings before production.",
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(atlas_export_dir(bundle.project_root), f"Atlas_EOAT_{_safe_name(eoat.eoat_id)}", markdown)


def export_machine_summary(bundle: AtlasDataBundle, machine: MachineRecord) -> Path:
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in machine.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# Machine Summary: {machine.machine}",
            "",
            f"- Robot Type: {machine.robot_type}",
            f"- Robot Model/Controller: {machine.robot_model}",
            f"- Compatible EOATs: {', '.join(machine.compatible_eoats)}",
            f"- Compatible Tools: {', '.join(machine.compatible_tools)}",
            f"- Documentation Score: {machine.documentation_score}%",
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(
        atlas_export_dir(bundle.project_root), f"Atlas_Machine_{_safe_name(machine.machine)}", markdown
    )


def export_recommendation_summary(bundle: AtlasDataBundle, result: RecommendationResult) -> Path:
    best = result.best.eoat_id if result.best else "No recommendation"
    candidate_lines = [
        f"- #{candidate.rank} {candidate.eoat_id} ({candidate.score}): {candidate.summary}"
        for candidate in result.candidates
    ] or ["No candidates found."]
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in result.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# EOAT Atlas Recommendation: {result.query}",
            "",
            result.summary,
            "",
            f"- Best EOAT: {best}",
            f"- Compatible Machines: {', '.join(result.compatible_machines)}",
            "",
            "## Candidates",
            *candidate_lines,
            "",
            "## Before Install",
            *[f"{index}. {item}" for index, item in enumerate(result.install_checklist, start=1)],
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(
        atlas_export_dir(bundle.project_root), f"Atlas_Recommendation_{_safe_name(result.query)[:40]}", markdown
    )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "Summary"


__all__ = [
    "atlas_export_dir",
    "export_compatibility_matrix",
    "export_documentation_gap_report",
    "export_eoat_summary",
    "export_machine_summary",
    "export_photo_coverage_report",
    "export_recommendation_summary",
]
