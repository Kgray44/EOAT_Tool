from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .audit_constants import ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from .audit_field_rules import eoat_type_uses_gripper, eoat_type_uses_vacuum, is_meaningful_value
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .validation_findings import ValidationFinding, ValidationSeverity, make_finding
from .workbook_io import row_dicts

PHOTO_EVIDENCE_TOOL_NAME = "EOAT Photo Evidence Coverage"

STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_MISSING = "missing"
STATUS_NOT_APPLICABLE = "not applicable"
STATUS_FOLLOW_UP = "follow-up needed"

EOAT_CIRCUIT_FIELDS = (
    "EOAT Vacuum Circuits",
    "EOAT Pressure Circuits",
    "EOAT Interchangeable Circuits",
)


@dataclass(frozen=True)
class PhotoEvidenceCategory:
    key: str
    label: str
    applies_when: str
    required_when: str
    recommended_when: str
    example_filename_prefix: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceCoverageStatus:
    audit_id: str
    category: str
    label: str
    applies: bool
    required: bool
    present: bool
    photo_count: int
    status: str
    warning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditEvidenceCoverage:
    audit_id: str
    machine: str
    statuses: tuple[EvidenceCoverageStatus, ...]
    row_data: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    @property
    def missing_required_count(self) -> int:
        return sum(1 for status in self.statuses if status.required and not status.present)

    @property
    def follow_up_needed_count(self) -> int:
        return sum(1 for status in self.statuses if status.status == STATUS_FOLLOW_UP)

    @property
    def complete_count(self) -> int:
        return sum(1 for status in self.statuses if status.status == STATUS_COMPLETE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "machine": self.machine,
            "missing_required_count": self.missing_required_count,
            "follow_up_needed_count": self.follow_up_needed_count,
            "complete_count": self.complete_count,
            "statuses": [status.to_dict() for status in self.statuses],
        }


PHOTO_EVIDENCE_CATEGORIES: tuple[PhotoEvidenceCategory, ...] = (
    PhotoEvidenceCategory(
        "overall_eoat",
        "Overall EOAT",
        "Applies to every physical audit row.",
        "Required when an audit is marked complete, audited, or a pilot candidate.",
        "Recommended for every audit.",
        "OverallEOAT",
    ),
    PhotoEvidenceCategory(
        "robot_connection",
        "Robot Connection",
        "Applies to every physical audit row.",
        "Required when an audit is marked complete, audited, or a pilot candidate.",
        "Recommended for every audit.",
        "RobotConnection",
    ),
    PhotoEvidenceCategory(
        "eoat_pneumatic_circuits",
        "EOAT-Side Pneumatic Circuits",
        "Applies when EOAT-side pneumatic circuit fields are meaningful or the EOAT uses vacuum/gripper tooling.",
        "Required when EOAT-side pneumatic circuits are documented on a complete audit.",
        "Recommended for vacuum, mechanical/gripper, and hybrid EOATs.",
        "EOATPneumaticCircuits",
    ),
    PhotoEvidenceCategory(
        "sensors",
        "Sensors",
        "Applies when Sensors Present? is Yes, Partial, or sensor details are meaningful.",
        "Required when Sensors Present? is Yes.",
        "Recommended when sensor details are applicable.",
        "Sensors",
    ),
    PhotoEvidenceCategory(
        "quick_disconnects",
        "Quick Disconnects",
        "Applies when Quick Disconnects Present? is Yes/Partial or quick disconnect details are meaningful.",
        "Required when Quick Disconnects Present? is Yes.",
        "Recommended when quick disconnect details are applicable.",
        "QuickDisconnects",
    ),
    PhotoEvidenceCategory(
        "tubing_routing",
        "Tubing Routing",
        "Applies to vacuum, mechanical/gripper, and hybrid EOATs.",
        "Required when a pneumatic EOAT audit is complete.",
        "Recommended for every pneumatic EOAT.",
        "TubingRouting",
    ),
    PhotoEvidenceCategory(
        "grippers",
        "Grippers",
        "Applies to mechanical/gripper and hybrid EOATs.",
        "Required when a gripper EOAT audit is complete.",
        "Recommended for mechanical/gripper and hybrid EOATs.",
        "Grippers",
    ),
    PhotoEvidenceCategory(
        "vacuum_cups",
        "Vacuum Cups",
        "Applies to vacuum and hybrid EOATs.",
        "Required when a vacuum EOAT audit is complete.",
        "Recommended for vacuum and hybrid EOATs.",
        "VacuumCups",
    ),
    PhotoEvidenceCategory(
        "mounting_hardware",
        "Mounting Hardware",
        "Applies to every physical audit row.",
        "Required when an audit is marked complete, audited, or a pilot candidate.",
        "Recommended for every audit.",
        "MountingHardware",
    ),
    PhotoEvidenceCategory(
        "cable_management",
        "Cable Management",
        "Applies when electrical/wiring or cable management details are meaningful.",
        "Required when a complete audit has electrical/wiring or cable management details.",
        "Recommended for every audit with documented wiring.",
        "CableManagement",
    ),
    PhotoEvidenceCategory(
        "wear_damage",
        "Wear / Damage",
        "Applies to every physical audit row.",
        "Required when issues, wear, damage, loose hardware, or poor routing are documented.",
        "Recommended for every audit.",
        "WearDamage",
    ),
    PhotoEvidenceCategory(
        "process_binder_reference",
        "Process Binder Reference",
        "Applies when process binder or documentation completion is documented.",
        "Required when Process Binder Complete? is Yes.",
        "Recommended when documentation is part of the audit decision.",
        "ProcessBinderReference",
    ),
)

PHOTO_CATEGORY_ALIASES = {
    "overall_eoat": ("overall", "overall eoat", "eoat overall"),
    "robot_connection": ("robot connection", "robot", "connection"),
    "eoat_pneumatic_circuits": ("eoat-side pneumatic", "pneumatic circuit", "pneumatic", "circuits"),
    "sensors": ("sensor", "sensors"),
    "quick_disconnects": ("quick disconnect", "quick_disconnect", "quickdisconnect"),
    "tubing_routing": ("tubing", "routing", "tubing routing"),
    "grippers": ("gripper", "grippers", "vacuum cups / grippers", "vacuum_cups_grippers"),
    "vacuum_cups": ("vacuum cup", "vacuum cups", "vacuum", "vacuum cups / grippers", "vacuum_cups_grippers"),
    "mounting_hardware": ("mounting", "hardware", "mounting hardware"),
    "cable_management": ("cable", "cable management", "wiring"),
    "wear_damage": ("wear", "damage", "wear / damage", "wear_damage"),
    "process_binder_reference": ("process binder", "binder", "documentation", "reference"),
}


def photo_evidence_categories() -> list[PhotoEvidenceCategory]:
    return list(PHOTO_EVIDENCE_CATEGORIES)


def audit_photo_intake_root(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).audit_root / "Photos" / "Incoming"


def audit_photo_intake_folder(project_root: str | Path, audit_id: str) -> Path:
    return audit_photo_intake_root(project_root) / _safe_folder_part(audit_id or "Unassigned_Audit")


def create_audit_photo_intake_folder(project_root: str | Path, audit_id: str, *, log_activity: bool = True) -> ToolResult:
    started = time.perf_counter()
    audit_id = _text(audit_id)
    if not audit_id:
        return ToolResult.fail("photo_evidence_intake_folder", PHOTO_EVIDENCE_TOOL_NAME, "Audit ID is required.")
    folder = ensure_directory(audit_photo_intake_folder(project_root, audit_id))
    result = ToolResult.ok(
        "photo_evidence_intake_folder",
        PHOTO_EVIDENCE_TOOL_NAME,
        "Created audit photo intake folder.",
        details=[f"Audit ID: {audit_id}", f"Folder: {folder}"],
        files_created=[str(folder)],
        metrics={"audit_id": audit_id},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def export_photo_checklist(project_root: str | Path, audit_id: str, *, log_activity: bool = True) -> ToolResult:
    started = time.perf_counter()
    audit_id = _text(audit_id)
    if not audit_id:
        return ToolResult.fail("photo_evidence_checklist", PHOTO_EVIDENCE_TOOL_NAME, "Audit ID is required.")
    folder = ensure_directory(audit_photo_intake_folder(project_root, audit_id))
    row = _find_audit_row(project_root, audit_id)
    markdown = build_photo_checklist_markdown(project_root, audit_id, row=row)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = safe_write_text(folder / f"Photo_Checklist_{_safe_folder_part(audit_id)}_{stamp}.md", markdown, overwrite=False)
    result = ToolResult.ok(
        "photo_evidence_checklist",
        PHOTO_EVIDENCE_TOOL_NAME,
        "Exported audit photo checklist.",
        details=[f"Audit ID: {audit_id}", f"Checklist: {path}", f"Intake folder: {folder}"],
        files_created=[str(path)],
        output_reports=[str(path)],
        metrics={"audit_id": audit_id},
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def build_photo_checklist_markdown(project_root: str | Path, audit_id: str, *, row: dict[str, Any] | None = None) -> str:
    audit_id = _text(audit_id)
    row = row if row is not None else _find_audit_row(project_root, audit_id)
    coverage = evidence_coverage_for_audit(project_root, audit_id, row=row)
    machine = _text((row or {}).get("Press/Machine #")) or "N/A"
    eoat_type = _text((row or {}).get("EOAT Type")) or "N/A"
    lines = [
        f"# Photo Evidence Checklist - {audit_id or 'Unassigned Audit'}",
        "",
        f"- Audit ID: {audit_id or 'N/A'}",
        f"- Press/Machine #: {machine}",
        f"- EOAT Type: {eoat_type}",
        f"- Intake folder: {audit_photo_intake_folder(project_root, audit_id)}",
        "",
        "## Expected Photos",
        "| Needed | Category | Example Filename Prefix | Status | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    status_by_key = {status.category: status for status in coverage.statuses} if coverage else {}
    for category in PHOTO_EVIDENCE_CATEGORIES:
        status = status_by_key.get(category.key)
        needed = "Required" if status and status.required else "Recommended" if status and status.applies else "N/A"
        status_text = status.status if status else "not checked"
        note = status.warning if status and status.warning else category.recommended_when
        lines.append(f"| {needed} | {category.label} | {category.example_filename_prefix} | {status_text} | {note} |")
    lines.extend(
        [
            "",
            "## Intake Notes",
            "- Keep this folder local to the project.",
            "- Do not add real photos to source control.",
            "- Rename or intake photos through the EOAT Command Center Photos page when ready.",
        ]
    )
    return "\n".join(lines) + "\n"


def evidence_coverage_for_project(project_root: str | Path) -> list[AuditEvidenceCoverage]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    rows = row_dicts(paths.master_workbook, "EOAT Inventory")
    photo_rows = row_dicts(paths.master_workbook, "Photo Index")
    coverage_rows: list[AuditEvidenceCoverage] = []
    for row in rows:
        audit_id = _text(row.get("Audit ID"))
        if not audit_id:
            continue
        coverage = evidence_coverage_for_audit(project_root, audit_id, row=row, photo_rows=photo_rows)
        if coverage is not None:
            coverage_rows.append(coverage)
    return coverage_rows


def evidence_coverage_for_audit(
    project_root: str | Path,
    audit_id: str,
    *,
    row: dict[str, Any] | None = None,
    photo_rows: list[dict[str, Any]] | None = None,
) -> AuditEvidenceCoverage | None:
    audit_id = _text(audit_id)
    if not audit_id:
        return None
    row = row if row is not None else _find_audit_row(project_root, audit_id)
    if row is None:
        return None
    photo_rows = photo_rows if photo_rows is not None else _photo_rows(project_root)
    related_photos = _photo_rows_for_audit(photo_rows, row)
    statuses = tuple(_coverage_status_for_category(row, category, related_photos) for category in PHOTO_EVIDENCE_CATEGORIES)
    return AuditEvidenceCoverage(audit_id=audit_id, machine=_text(row.get("Press/Machine #")), statuses=statuses, row_data=dict(row))


def validate_photo_evidence(project_root: str | Path) -> tuple[list[str], dict[str, int], list[ValidationFinding]]:
    coverages = evidence_coverage_for_project(project_root)
    findings = photo_evidence_findings_from_coverages(coverages)
    warnings = [finding.message for finding in findings]
    metrics = {
        "photo_evidence_audit_count": len(coverages),
        "photo_evidence_missing_required_count": sum(coverage.missing_required_count for coverage in coverages),
        "photo_evidence_finding_count": len(findings),
    }
    return warnings, metrics, findings


def missing_evidence_findings(project_root: str | Path) -> list[ValidationFinding]:
    return photo_evidence_findings_from_coverages(evidence_coverage_for_project(project_root))


def photo_evidence_findings_from_coverages(coverages: Iterable[AuditEvidenceCoverage]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for coverage in coverages:
        row = coverage.row_data
        for status in coverage.statuses:
            if status.required and not status.present:
                findings.append(
                    make_finding(
                        ValidationSeverity.WARNING,
                        "missing_evidence",
                        f"{coverage.audit_id}: required photo evidence missing for {status.label}.",
                        sheet_name="Photo Index",
                        audit_id=coverage.audit_id,
                        machine_number=coverage.machine,
                        column_name="Related Audit ID",
                        current_value=status.status,
                        expected_behavior="Required photo evidence categories should have at least one indexed local photo before the audit is treated as complete.",
                        recommended_action="Create an audit intake folder, capture the missing evidence, and intake/index the photos locally.",
                        source_validator="photo_evidence",
                    )
                )
        findings.extend(_specific_photo_evidence_findings(coverage, row))
    return findings


def pm_bom_evidence_status(project_root: str | Path, audit_id: str) -> dict[str, Any]:
    coverage = evidence_coverage_for_audit(project_root, audit_id)
    if coverage is None:
        return {"audit_id": audit_id, "missing_evidence": True, "missing_categories": []}
    missing_categories = [status.category for status in coverage.statuses if status.required and not status.present]
    return {
        "audit_id": coverage.audit_id,
        "machine": coverage.machine,
        "missing_evidence": bool(missing_categories),
        "missing_categories": missing_categories,
        "missing_required_count": coverage.missing_required_count,
    }


def _coverage_status_for_category(
    row: dict[str, Any],
    category: PhotoEvidenceCategory,
    photo_rows: list[dict[str, Any]],
) -> EvidenceCoverageStatus:
    applies = _category_applies(row, category.key)
    required = applies and _category_required(row, category.key)
    recommended = applies and _category_recommended(row, category.key)
    matching = _photo_rows_for_category(photo_rows, category.key)
    photo_count = len(matching)
    present = photo_count > 0
    if not applies:
        status = STATUS_NOT_APPLICABLE
    elif present:
        status = STATUS_COMPLETE
    elif required:
        status = STATUS_MISSING
    elif recommended:
        status = STATUS_FOLLOW_UP
    else:
        status = STATUS_NOT_APPLICABLE
    warning = f"Missing required evidence: {category.label}." if required and not present else ""
    return EvidenceCoverageStatus(
        audit_id=_text(row.get("Audit ID")),
        category=category.key,
        label=category.label,
        applies=applies,
        required=required,
        present=present,
        photo_count=photo_count,
        status=status,
        warning=warning,
    )


def _category_applies(row: dict[str, Any], key: str) -> bool:
    if _is_compatible_row(row):
        return False
    if key in {"overall_eoat", "robot_connection", "mounting_hardware", "wear_damage"}:
        return True
    if key == "eoat_pneumatic_circuits":
        return any(is_meaningful_value(row.get(field)) for field in EOAT_CIRCUIT_FIELDS) or eoat_type_uses_vacuum(row) or eoat_type_uses_gripper(row)
    if key == "sensors":
        return _is_yes_or_partial(row.get("Sensors Present?")) or any(is_meaningful_value(row.get(field)) for field in ("Sensor Type", "Sensor Brand/Model"))
    if key == "quick_disconnects":
        return _is_yes_or_partial(row.get("Quick Disconnects Present?")) or any(
            is_meaningful_value(row.get(field)) for field in ("Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type")
        )
    if key == "tubing_routing":
        return eoat_type_uses_vacuum(row) or eoat_type_uses_gripper(row) or is_meaningful_value(row.get("Tubing Condition"))
    if key == "grippers":
        return eoat_type_uses_gripper(row)
    if key == "vacuum_cups":
        return eoat_type_uses_vacuum(row)
    if key == "cable_management":
        return _is_yes_or_partial(row.get("Electrical/Wiring Present?")) or is_meaningful_value(row.get("Cable Management Condition"))
    if key == "process_binder_reference":
        return is_meaningful_value(row.get("Process Binder Complete?")) or is_meaningful_value(row.get("Photo Folder/Link"))
    return False


def _category_required(row: dict[str, Any], key: str) -> bool:
    complete = _is_complete_or_pilot(row)
    if key in {"overall_eoat", "robot_connection", "mounting_hardware"}:
        return complete
    if key == "eoat_pneumatic_circuits":
        return complete and any(is_meaningful_value(row.get(field)) for field in EOAT_CIRCUIT_FIELDS)
    if key == "sensors":
        return _is_yes(row.get("Sensors Present?"))
    if key == "quick_disconnects":
        return _is_yes(row.get("Quick Disconnects Present?"))
    if key == "tubing_routing":
        return complete and (eoat_type_uses_vacuum(row) or eoat_type_uses_gripper(row))
    if key == "grippers":
        return complete and eoat_type_uses_gripper(row)
    if key == "vacuum_cups":
        return complete and eoat_type_uses_vacuum(row)
    if key == "cable_management":
        return complete and _category_applies(row, key)
    if key == "wear_damage":
        return _has_issue_or_damage(row)
    if key == "process_binder_reference":
        return _is_yes(row.get("Process Binder Complete?"))
    return False


def _category_recommended(row: dict[str, Any], key: str) -> bool:
    if key in {"overall_eoat", "robot_connection", "mounting_hardware", "wear_damage"}:
        return True
    return _category_applies(row, key)


def _specific_photo_evidence_findings(coverage: AuditEvidenceCoverage, row: dict[str, Any] | None) -> list[ValidationFinding]:
    if row is None:
        return []
    status_by_key = {status.category: status for status in coverage.statuses}
    findings: list[ValidationFinding] = []
    if _is_complete_or_audited(row) and any(status.required and not status.present for status in coverage.statuses):
        findings.append(
            _photo_finding(
                coverage,
                "Audit is marked complete/audited but required photo evidence is missing.",
                "Status",
                row.get("Status"),
            )
        )
    if _is_pilot_candidate(row) and not _any_present(coverage):
        findings.append(_photo_finding(coverage, "Pilot candidate lacks before photo evidence.", "Pilot Candidate?", row.get("Pilot Candidate?")))
    if _has_meaningful_issue(row) and not _any_present(coverage):
        findings.append(_photo_finding(coverage, "Audit issue has no supporting photo evidence.", "Known Issues", row.get("Known Issues")))
    if _documentation_marked_complete(row) and not (_text(row.get("Photo Folder/Link")) or status_by_key.get("process_binder_reference", _empty_status()).present):
        findings.append(
            _photo_finding(
                coverage,
                "Documentation is marked complete but no document/photo reference is recorded.",
                "Photo Folder/Link",
                row.get("Photo Folder/Link"),
            )
        )
    sensor_status = status_by_key.get("sensors")
    if _is_yes(row.get("Sensors Present?")) and sensor_status and not sensor_status.present:
        findings.append(_photo_finding(coverage, "Sensors Present? is Yes but no sensor photo is indexed.", "Sensors Present?", row.get("Sensors Present?")))
    qd_status = status_by_key.get("quick_disconnects")
    if _is_yes(row.get("Quick Disconnects Present?")) and qd_status and not qd_status.present:
        findings.append(
            _photo_finding(
                coverage,
                "Quick Disconnects Present? is Yes but no quick disconnect photo is indexed.",
                "Quick Disconnects Present?",
                row.get("Quick Disconnects Present?"),
            )
        )
    return findings


def _photo_finding(coverage: AuditEvidenceCoverage, message: str, column_name: str, current_value: Any) -> ValidationFinding:
    return make_finding(
        ValidationSeverity.WARNING,
        "missing_evidence",
        f"{coverage.audit_id}: {message}",
        sheet_name="EOAT Inventory",
        audit_id=coverage.audit_id,
        machine_number=coverage.machine,
        column_name=column_name,
        current_value=current_value,
        expected_behavior="Evidence-sensitive audit decisions should have local photo or document references.",
        recommended_action="Use the Photos page to create an audit intake folder, capture evidence, and intake/index the photos locally.",
        source_validator="photo_evidence",
    )


def _photo_rows_for_audit(photo_rows: list[dict[str, Any]], row: dict[str, Any]) -> list[dict[str, Any]]:
    audit_id = _text(row.get("Audit ID")).casefold()
    machine = _text(row.get("Press/Machine #")).casefold()
    matches: list[dict[str, Any]] = []
    for photo in photo_rows:
        related_audit = _text(photo.get("Related Audit ID")).casefold()
        photo_machine = _text(photo.get("Press/Machine #")).casefold()
        if audit_id and related_audit == audit_id:
            matches.append(photo)
        elif machine and not related_audit and photo_machine == machine:
            matches.append(photo)
    return matches


def _photo_rows_for_category(photo_rows: list[dict[str, Any]], category_key: str) -> list[dict[str, Any]]:
    aliases = PHOTO_CATEGORY_ALIASES.get(category_key, ())
    matches: list[dict[str, Any]] = []
    for row in photo_rows:
        haystack = _photo_search_text(row)
        if any(alias.casefold() in haystack for alias in aliases):
            matches.append(row)
    return matches


def _photo_search_text(row: dict[str, Any]) -> str:
    fields = ["EOAT Area Shown", "Description", "Photo Filename", "Folder Path", "Notes"]
    return " ".join(_text(row.get(field)).casefold() for field in fields)


def _photo_rows(project_root: str | Path) -> list[dict[str, Any]]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    return row_dicts(paths.master_workbook, "Photo Index")


def _find_audit_row(project_root: str | Path, audit_id: str) -> dict[str, Any] | None:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return None
    target = _text(audit_id).casefold()
    for row in row_dicts(paths.master_workbook, "EOAT Inventory"):
        if _text(row.get("Audit ID")).casefold() == target:
            return row
    return None


def _is_compatible_row(row: dict[str, Any]) -> bool:
    return _text(row.get(ENTRY_TYPE_FIELD)).casefold() == ENTRY_TYPE_COMPATIBLE.casefold()


def _is_complete_or_audited(row: dict[str, Any]) -> bool:
    status = _text(row.get("Status")).casefold()
    return status in {"complete", "audited"}


def _is_complete_or_pilot(row: dict[str, Any]) -> bool:
    return _is_complete_or_audited(row) or _is_pilot_candidate(row)


def _is_pilot_candidate(row: dict[str, Any]) -> bool:
    return _text(row.get("Pilot Candidate?")).casefold() in {"yes", "maybe", "candidate for pilot"}


def _is_yes(value: Any) -> bool:
    return _text(value).casefold() == "yes"


def _is_yes_or_partial(value: Any) -> bool:
    return _text(value).casefold() in {"yes", "partial"}


def _has_issue_or_damage(row: dict[str, Any]) -> bool:
    condition_fields = ["Tubing Condition", "Cable Management Condition", "Mounting Hardware Condition", "EOAT Alignment Condition"]
    bad_tokens = ("worn", "damage", "damaged", "poor", "loose", "missing", "misaligned", "follow-up", "follow up")
    return _has_meaningful_issue(row) or any(any(token in _text(row.get(field)).casefold() for token in bad_tokens) for field in condition_fields)


def _has_meaningful_issue(row: dict[str, Any]) -> bool:
    issue = _text(row.get("Known Issues")).casefold()
    if not issue:
        return False
    return issue not in {"none", "no", "n/a", "na", "no issue observed.", "no issues observed", "unknown / not checked", "unknown"}


def _documentation_marked_complete(row: dict[str, Any]) -> bool:
    return _is_yes(row.get("Process Binder Complete?")) or _is_yes(row.get("Drawing/CAD Available?")) or _is_yes(row.get("BOM Available?"))


def _any_present(coverage: AuditEvidenceCoverage) -> bool:
    return any(status.present for status in coverage.statuses)


def _empty_status() -> EvidenceCoverageStatus:
    return EvidenceCoverageStatus("", "", "", False, False, False, 0, STATUS_NOT_APPLICABLE)


def _safe_folder_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._-") or "Unassigned_Audit"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "AuditEvidenceCoverage",
    "EvidenceCoverageStatus",
    "PHOTO_EVIDENCE_CATEGORIES",
    "PhotoEvidenceCategory",
    "audit_photo_intake_folder",
    "audit_photo_intake_root",
    "build_photo_checklist_markdown",
    "create_audit_photo_intake_folder",
    "evidence_coverage_for_audit",
    "evidence_coverage_for_project",
    "export_photo_checklist",
    "missing_evidence_findings",
    "photo_evidence_categories",
    "pm_bom_evidence_status",
    "validate_photo_evidence",
]
