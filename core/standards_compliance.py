from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import table_from_rows, write_timestamped_csv, write_timestamped_report
from .audit_constants import ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from .audit_field_rules import eoat_type_uses_gripper, eoat_type_uses_vacuum, is_meaningful_value, is_na_value
from .gripper_fields import CUP_COUNT_FIELD, GRIPPER_COUNT_FIELD, GRIPPER_MODEL_FIELD, GRIPPER_TYPE_FIELD
from .logging import log_tool_run
from .paths import resolve_project_paths
from .photo_evidence import evidence_coverage_for_audit
from .pm_bom_coverage import is_bom_available, is_spare_parts_info_missing, missing_documentation_fields
from .result import ToolResult
from .safe_files import ensure_directory
from .workbook_cache import row_dicts_cached as row_dicts

STATUS_COMPLIANT = "compliant"
STATUS_WARNING = "warning"
STATUS_FAIL = "fail"
STATUS_NOT_APPLICABLE = "not applicable"
STATUS_UNKNOWN = "unknown"

STATUS_SCORES = {
    STATUS_COMPLIANT: 100,
    STATUS_WARNING: 60,
    STATUS_FAIL: 0,
    STATUS_UNKNOWN: 40,
}


@dataclass(frozen=True)
class ComplianceCategoryResult:
    key: str
    label: str
    status: str
    score: int | None
    reason: str
    recommended_action: str
    related_fields: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditComplianceResult:
    audit_id: str
    machine: str
    plant_area: str
    eoat_type: str
    overall_score: int
    category_results: tuple[ComplianceCategoryResult, ...]

    @property
    def failed_standards(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(result for result in self.category_results if result.status == STATUS_FAIL)

    @property
    def warnings(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(result for result in self.category_results if result.status == STATUS_WARNING)

    @property
    def unknown_items(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(result for result in self.category_results if result.status == STATUS_UNKNOWN)

    @property
    def recommended_actions(self) -> tuple[str, ...]:
        actions = [
            result.recommended_action
            for result in self.category_results
            if result.recommended_action and result.status != STATUS_COMPLIANT
        ]
        return tuple(dict.fromkeys(actions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "machine": self.machine,
            "plant_area": self.plant_area,
            "eoat_type": self.eoat_type,
            "overall_score": self.overall_score,
            "failed_standards": [result.label for result in self.failed_standards],
            "warnings": [result.label for result in self.warnings],
            "unknown_items": [result.label for result in self.unknown_items],
            "recommended_actions": list(self.recommended_actions),
            "category_results": [result.to_dict() for result in self.category_results],
        }


@dataclass(frozen=True)
class PressComplianceRollup:
    machine: str
    audit_count: int
    average_compliance_score: int
    worst_category: str
    open_standards_issues: int
    pilot_candidate_relevance: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StandardsComplianceSummary:
    audits: tuple[AuditComplianceResult, ...]
    press_rollups: tuple[PressComplianceRollup, ...]
    metrics: dict[str, Any]

    def to_markdown(self) -> str:
        rows = [
            {
                "Audit ID": audit.audit_id,
                "Press/Machine #": audit.machine,
                "EOAT Type": audit.eoat_type,
                "Score": audit.overall_score,
                "Fails": len(audit.failed_standards),
                "Warnings": len(audit.warnings),
                "Unknown": len(audit.unknown_items),
            }
            for audit in self.audits
        ]
        rollups = [
            {
                "Press/Machine #": rollup.machine,
                "Audits": rollup.audit_count,
                "Average Score": rollup.average_compliance_score,
                "Worst Category": rollup.worst_category,
                "Open Standards Issues": rollup.open_standards_issues,
                "Pilot Relevance": rollup.pilot_candidate_relevance,
            }
            for rollup in self.press_rollups
        ]
        lines = [
            "# Standards Compliance Summary",
            "",
            "## Executive Summary",
            f"- Audits scored: {self.metrics.get('audits_scored', 0)}",
            f"- Average compliance score: {self.metrics.get('average_compliance_score', 0)}",
            f"- Failed standards: {self.metrics.get('failed_standard_count', 0)}",
            f"- Unknown/follow-up standards: {self.metrics.get('unknown_standard_count', 0)}",
            "",
            "## Audit Compliance",
            *table_from_rows(
                rows, ["Audit ID", "Press/Machine #", "EOAT Type", "Score", "Fails", "Warnings", "Unknown"]
            ),
            "",
            "## Press / Cell Rollup",
            *table_from_rows(
                rollups,
                [
                    "Press/Machine #",
                    "Audits",
                    "Average Score",
                    "Worst Category",
                    "Open Standards Issues",
                    "Pilot Relevance",
                ],
            ),
            "",
            "## Method Notes",
            "- Unknown / Not Checked lowers confidence and is not treated as verified complete.",
            "- Valid N/A is excluded from score math when the category does not physically apply.",
            "- Scores summarize readiness for review; they are not final engineering approval.",
        ]
        return "\n".join(lines) + "\n"


def score_audit_compliance(project_root: str | Path, row: dict[str, Any]) -> AuditComplianceResult:
    categories = (
        _classification_complete(row),
        _tooling_details_complete(row),
        _pneumatic_routing(row),
        _sensor_standards(row),
        _quick_disconnect_standards(row),
        _cable_management(row),
        _mechanical_mounting(row),
        _safety_concerns(row),
        _documentation_completeness(row),
        _pm_readiness(row),
        _bom_spare_parts_readiness(row),
        _photo_evidence_readiness(project_root, row),
    )
    scored = [result.score for result in categories if result.score is not None]
    overall = round(sum(scored) / len(scored)) if scored else 0
    return AuditComplianceResult(
        audit_id=_text(row.get("Audit ID")),
        machine=_text(row.get("Press/Machine #")),
        plant_area=_text(row.get("Plant/Area")),
        eoat_type=_text(row.get("EOAT Type")),
        overall_score=overall,
        category_results=categories,
    )


def analyze_standards_compliance(
    project_root: str | Path,
) -> tuple[StandardsComplianceSummary | None, ToolResult | None]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return None, ToolResult.fail(
            "standards_compliance",
            "Standards Compliance Analysis",
            "Master workbook is missing.",
            errors=[str(paths.master_workbook)],
        )
    try:
        rows = row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception as exc:
        return None, ToolResult.fail(
            "standards_compliance", "Standards Compliance Analysis", "Could not read EOAT Inventory.", errors=[str(exc)]
        )
    audits = tuple(score_audit_compliance(project_root, row) for row in rows if _is_physical_audit(row))
    rollups = tuple(rollup_compliance_by_press(audits))
    scores = [audit.overall_score for audit in audits]
    summary = StandardsComplianceSummary(
        audits=audits,
        press_rollups=rollups,
        metrics={
            "audits_scored": len(audits),
            "average_compliance_score": round(sum(scores) / len(scores)) if scores else 0,
            "failed_standard_count": sum(len(audit.failed_standards) for audit in audits),
            "warning_standard_count": sum(len(audit.warnings) for audit in audits),
            "unknown_standard_count": sum(len(audit.unknown_items) for audit in audits),
            "press_rollup_count": len(rollups),
        },
    )
    return summary, None


def rollup_compliance_by_press(
    audits: tuple[AuditComplianceResult, ...] | list[AuditComplianceResult],
) -> list[PressComplianceRollup]:
    by_machine: dict[str, list[AuditComplianceResult]] = defaultdict(list)
    for audit in audits:
        by_machine[audit.machine or "Unassigned / Missing Press"].append(audit)
    rollups: list[PressComplianceRollup] = []
    for machine, machine_audits in by_machine.items():
        scores = [audit.overall_score for audit in machine_audits]
        categories: Counter[str] = Counter()
        open_issues = 0
        pilot_values: list[str] = []
        for audit in machine_audits:
            categories.update(result.label for result in audit.failed_standards + audit.warnings + audit.unknown_items)
            open_issues += len(audit.failed_standards) + len(audit.warnings) + len(audit.unknown_items)
        worst = categories.most_common(1)[0][0] if categories else "None"
        rollups.append(
            PressComplianceRollup(
                machine=machine,
                audit_count=len(machine_audits),
                average_compliance_score=round(sum(scores) / len(scores)) if scores else 0,
                worst_category=worst,
                open_standards_issues=open_issues,
                pilot_candidate_relevance=_pilot_relevance(machine_audits, pilot_values),
            )
        )
    return sorted(rollups, key=lambda rollup: rollup.machine.casefold())


def generate_standards_compliance_report(project_root: str | Path, *, log_activity: bool = True) -> ToolResult:
    started = time.perf_counter()
    summary, error = analyze_standards_compliance(project_root)
    if error:
        return error
    assert summary is not None
    paths = resolve_project_paths(project_root)
    folder = ensure_directory(paths.documentation_gap_reports)
    rows = [
        {
            "Audit ID": audit.audit_id,
            "Press/Machine #": audit.machine,
            "EOAT Type": audit.eoat_type,
            "Overall Score": audit.overall_score,
            "Failed Standards": "; ".join(result.label for result in audit.failed_standards),
            "Warnings": "; ".join(result.label for result in audit.warnings),
            "Unknown Items": "; ".join(result.label for result in audit.unknown_items),
        }
        for audit in summary.audits
    ]
    try:
        report = write_timestamped_report(folder, "Standards_Compliance_Summary", summary.to_markdown())
        files = [str(report)]
        if rows:
            files.append(str(write_timestamped_csv(folder, "Standards_Compliance_Table", rows)))
    except Exception as exc:
        return ToolResult.fail(
            "standards_compliance",
            "Standards Compliance Analysis",
            "Could not write compliance report.",
            errors=[str(exc)],
        )
    result = ToolResult.ok(
        "standards_compliance",
        "Standards Compliance Analysis",
        "Generated standards compliance summary.",
        details=[f"Report: {report}"],
        files_created=files,
        output_reports=files,
        metrics=summary.metrics,
        duration_seconds=time.perf_counter() - started,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _classification_complete(row: dict[str, Any]) -> ComplianceCategoryResult:
    eoat_type = _text(row.get("EOAT Type"))
    if _unknown(eoat_type):
        return _result(
            "eoat_classification_complete",
            "EOAT classification complete",
            STATUS_UNKNOWN,
            "EOAT Type is unknown or blank.",
            "Verify the physical EOAT type.",
            ("EOAT Type",),
        )
    return _result(
        "eoat_classification_complete",
        "EOAT classification complete",
        STATUS_COMPLIANT,
        f"EOAT Type is documented as {eoat_type}.",
        "",
        ("EOAT Type",),
    )


def _tooling_details_complete(row: dict[str, Any]) -> ComplianceCategoryResult:
    if _unknown(row.get("EOAT Type")):
        return _result(
            "tooling_details_complete",
            "Tooling details complete",
            STATUS_UNKNOWN,
            "Tooling requirements depend on unknown EOAT type.",
            "Verify EOAT Type before judging tooling details.",
            ("EOAT Type",),
        )
    required: list[str] = ["Number of Parts Picked"]
    if eoat_type_uses_vacuum(row):
        required.extend([CUP_COUNT_FIELD, "Cup Type/Material", "Cup Diameter/Size", "Vacuum Generator Type"])
    if eoat_type_uses_gripper(row):
        required.extend([GRIPPER_COUNT_FIELD, GRIPPER_TYPE_FIELD, GRIPPER_MODEL_FIELD])
    missing = [field for field in required if _unknown(row.get(field)) or is_na_value(row.get(field))]
    if missing:
        return _result(
            "tooling_details_complete",
            "Tooling details complete",
            STATUS_WARNING,
            f"Missing or unknown tooling fields: {', '.join(missing)}.",
            "Complete applicable tooling details or mark true N/A through the audit workflow.",
            tuple(required),
        )
    return _result(
        "tooling_details_complete",
        "Tooling details complete",
        STATUS_COMPLIANT,
        "Applicable tooling details are documented.",
        "",
        tuple(required),
    )


def _pneumatic_routing(row: dict[str, Any]) -> ComplianceCategoryResult:
    if not (eoat_type_uses_vacuum(row) or eoat_type_uses_gripper(row)):
        return _result(
            "pneumatic_routing",
            "Pneumatic routing condition",
            STATUS_NOT_APPLICABLE,
            "Pneumatic routing is not applicable to this EOAT classification.",
            "",
            ("Tubing Condition",),
        )
    return _condition_result(
        "pneumatic_routing",
        "Pneumatic routing condition",
        row.get("Tubing Condition"),
        "Tubing Condition",
        good={"ok", "good"},
        warning_tokens={"needs follow-up", "follow-up", "worn"},
        fail_tokens={"damaged", "poor routing", "poor", "leak", "kink"},
        action="Review tubing routing and document corrective action before treating the standard as met.",
    )


def _sensor_standards(row: dict[str, Any]) -> ComplianceCategoryResult:
    present = _text(row.get("Sensors Present?"))
    fields = (
        "Sensors Present?",
        "Sensor Type",
        "Sensor Brand/Model",
        "Part-Present Detection Present?",
        "Vacuum Confirmation Present?",
    )
    if _unknown(present):
        return _result(
            "sensor_standards",
            "Sensor standard/documentation",
            STATUS_UNKNOWN,
            "Sensor presence is unknown.",
            "Verify whether sensors are present.",
            fields,
        )
    if _no(present):
        return _result(
            "sensor_standards",
            "Sensor standard/documentation",
            STATUS_NOT_APPLICABLE,
            "Sensors are documented as not present.",
            "",
            fields,
        )
    missing = [field for field in fields[1:] if _unknown(row.get(field)) and not is_na_value(row.get(field))]
    if missing:
        return _result(
            "sensor_standards",
            "Sensor standard/documentation",
            STATUS_WARNING,
            f"Sensor details need review: {', '.join(missing)}.",
            "Document sensor type, model, and confirmation method.",
            fields,
        )
    return _result(
        "sensor_standards",
        "Sensor standard/documentation",
        STATUS_COMPLIANT,
        "Sensor presence and detail fields are documented.",
        "",
        fields,
    )


def _quick_disconnect_standards(row: dict[str, Any]) -> ComplianceCategoryResult:
    present = _text(row.get("Quick Disconnects Present?"))
    fields = ("Quick Disconnects Present?", "Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type")
    if _unknown(present):
        return _result(
            "quick_disconnect_standards",
            "Quick disconnect standard",
            STATUS_UNKNOWN,
            "Quick disconnect presence is unknown.",
            "Verify whether quick disconnects are present.",
            fields,
        )
    if _no(present):
        return _result(
            "quick_disconnect_standards",
            "Quick disconnect standard",
            STATUS_NOT_APPLICABLE,
            "Quick disconnects are documented as not present.",
            "",
            fields,
        )
    if present.casefold() == "partial":
        return _result(
            "quick_disconnect_standards",
            "Quick disconnect standard",
            STATUS_WARNING,
            "Quick disconnects are only partially documented.",
            "Identify pneumatic/electrical quick disconnect standards or document the exception.",
            fields,
        )
    if not any(is_meaningful_value(row.get(field)) for field in fields[1:]):
        return _result(
            "quick_disconnect_standards",
            "Quick disconnect standard",
            STATUS_WARNING,
            "Quick disconnects are present but type fields are missing.",
            "Document the applicable quick disconnect type(s).",
            fields,
        )
    return _result(
        "quick_disconnect_standards",
        "Quick disconnect standard",
        STATUS_COMPLIANT,
        "Quick disconnect presence and type information are documented.",
        "",
        fields,
    )


def _cable_management(row: dict[str, Any]) -> ComplianceCategoryResult:
    return _condition_result(
        "cable_management",
        "Cable management",
        row.get("Cable Management Condition"),
        "Cable Management Condition",
        good={"ok", "good"},
        warning_tokens={"needs follow-up", "follow-up", "loose"},
        fail_tokens={"damaged", "poor routing", "pinched", "rubbing"},
        action="Review cable routing and document corrective action.",
    )


def _mechanical_mounting(row: dict[str, Any]) -> ComplianceCategoryResult:
    fields = ("Mounting Hardware Condition", "EOAT Alignment Condition", "Fastener/Locking Hardware Present?")
    bad = []
    unknown = []
    for field_name in fields:
        value = _text(row.get(field_name))
        if _unknown(value):
            unknown.append(field_name)
        elif any(token in value.casefold() for token in ("loose", "missing", "damaged", "misaligned")) or _no(value):
            bad.append(field_name)
    if bad:
        return _result(
            "mechanical_mounting",
            "Mechanical mounting",
            STATUS_FAIL,
            f"Mechanical mounting/alignment issue fields: {', '.join(bad)}.",
            "Inspect mounting, locking hardware, and alignment before approving the standard.",
            fields,
        )
    if unknown:
        return _result(
            "mechanical_mounting",
            "Mechanical mounting",
            STATUS_UNKNOWN,
            f"Mechanical mounting fields are unknown: {', '.join(unknown)}.",
            "Verify mechanical mounting and alignment condition.",
            fields,
        )
    return _result(
        "mechanical_mounting",
        "Mechanical mounting",
        STATUS_COMPLIANT,
        "Mechanical mounting and alignment fields are documented without flagged issues.",
        "",
        fields,
    )


def _safety_concerns(row: dict[str, Any]) -> ComplianceCategoryResult:
    fields = ("Known Issues", "Scrap/Quality Concern?", "Cycle Time Concern?", "Follow-Up Needed")
    issue = _text(row.get("Known Issues"))
    if _yes(row.get("Follow-Up Needed")) or _yes(row.get("Scrap/Quality Concern?")):
        return _result(
            "safety_concerns",
            "Safety concerns",
            STATUS_WARNING,
            "Follow-up, scrap, or quality concern is flagged.",
            "Review safety/quality risk before closing this audit.",
            fields,
        )
    if issue and issue.casefold() not in {
        "none",
        "no",
        "n/a",
        "na",
        "no issue observed.",
        "no issues observed",
        "unknown / not checked",
        "unknown",
    }:
        status = STATUS_FAIL if "safety" in issue.casefold() else STATUS_WARNING
        return _result(
            "safety_concerns",
            "Safety concerns",
            status,
            "Known Issues contains a documented concern.",
            "Review the issue and decide whether it belongs in open items or FMEA.",
            fields,
        )
    if _unknown(issue):
        return _result(
            "safety_concerns",
            "Safety concerns",
            STATUS_UNKNOWN,
            "Known Issues has not been checked.",
            "Confirm whether safety or reliability concerns exist.",
            fields,
        )
    return _result(
        "safety_concerns",
        "Safety concerns",
        STATUS_COMPLIANT,
        "No documented safety concern in current audit fields.",
        "",
        fields,
    )


def _documentation_completeness(row: dict[str, Any]) -> ComplianceCategoryResult:
    missing = missing_documentation_fields(row)
    fields = ("Drawing/CAD Available?", "BOM Available?", "Process Binder Complete?", "Spare Parts Identified?")
    if not missing:
        return _result(
            "documentation_completeness",
            "Documentation completeness",
            STATUS_COMPLIANT,
            "Documentation status fields are complete or partial where allowed.",
            "",
            fields,
        )
    unknown = [field for field in missing if _unknown(row.get(field))]
    if unknown:
        return _result(
            "documentation_completeness",
            "Documentation completeness",
            STATUS_UNKNOWN,
            f"Documentation status unknown: {', '.join(unknown)}.",
            "Verify documentation availability rather than treating blanks as complete.",
            fields,
        )
    return _result(
        "documentation_completeness",
        "Documentation completeness",
        STATUS_FAIL,
        f"Documentation gaps remain: {', '.join(missing)}.",
        "Find documentation or record the gap as intentional follow-up.",
        fields,
    )


def _pm_readiness(row: dict[str, Any]) -> ComplianceCategoryResult:
    fields = ("Maintenance Frequency", "Process Binder Complete?", "Photos Taken?")
    if _unknown(row.get("Maintenance Frequency")):
        return _result(
            "pm_readiness",
            "PM readiness",
            STATUS_UNKNOWN,
            "Maintenance frequency is unknown.",
            "Confirm PM frequency or document why it is unavailable.",
            fields,
        )
    if _no(row.get("Process Binder Complete?")):
        return _result(
            "pm_readiness",
            "PM readiness",
            STATUS_WARNING,
            "Process binder is not complete.",
            "Complete binder references before calling PM readiness complete.",
            fields,
        )
    return _result(
        "pm_readiness",
        "PM readiness",
        STATUS_COMPLIANT,
        "Maintenance frequency and binder readiness are documented.",
        "",
        fields,
    )


def _bom_spare_parts_readiness(row: dict[str, Any]) -> ComplianceCategoryResult:
    fields = ("BOM Available?", "Spare Parts Identified?")
    if _unknown(row.get("BOM Available?")) or _unknown(row.get("Spare Parts Identified?")):
        return _result(
            "bom_spare_parts_readiness",
            "BOM/spare parts readiness",
            STATUS_UNKNOWN,
            "BOM or spare parts status is unknown.",
            "Verify BOM and spare-parts status.",
            fields,
        )
    if not is_bom_available(row) or is_spare_parts_info_missing(row):
        return _result(
            "bom_spare_parts_readiness",
            "BOM/spare parts readiness",
            STATUS_FAIL,
            "BOM and spare-parts readiness is not complete.",
            "Confirm BOM and spare-parts availability before standardization handoff.",
            fields,
        )
    return _result(
        "bom_spare_parts_readiness",
        "BOM/spare parts readiness",
        STATUS_COMPLIANT,
        "BOM and spare-parts readiness fields are documented as available.",
        "",
        fields,
    )


def _photo_evidence_readiness(project_root: str | Path, row: dict[str, Any]) -> ComplianceCategoryResult:
    audit_id = _text(row.get("Audit ID"))
    coverage = evidence_coverage_for_audit(project_root, audit_id, row=row) if audit_id else None
    if coverage is None:
        return _result(
            "photo_evidence_readiness",
            "Photo evidence readiness",
            STATUS_UNKNOWN,
            "Photo evidence coverage could not be evaluated.",
            "Create or load an audit row before judging photo evidence.",
            ("Photos Taken?", "Photo Folder/Link"),
        )
    missing = [status.label for status in coverage.statuses if status.required and not status.present]
    follow_up = [status.label for status in coverage.statuses if status.status == "follow-up needed"]
    if missing:
        return _result(
            "photo_evidence_readiness",
            "Photo evidence readiness",
            STATUS_FAIL,
            f"Required photo evidence missing: {', '.join(missing)}.",
            "Capture and intake the missing local photo evidence.",
            ("Photos Taken?", "Photo Folder/Link"),
        )
    if follow_up:
        return _result(
            "photo_evidence_readiness",
            "Photo evidence readiness",
            STATUS_WARNING,
            f"Recommended evidence still needs follow-up: {', '.join(follow_up[:4])}.",
            "Capture recommended evidence where practical.",
            ("Photos Taken?", "Photo Folder/Link"),
        )
    return _result(
        "photo_evidence_readiness",
        "Photo evidence readiness",
        STATUS_COMPLIANT,
        "Required photo evidence categories are covered or not applicable.",
        "",
        ("Photos Taken?", "Photo Folder/Link"),
    )


def _condition_result(
    key: str,
    label: str,
    value: Any,
    field_name: str,
    *,
    good: set[str],
    warning_tokens: set[str],
    fail_tokens: set[str],
    action: str,
) -> ComplianceCategoryResult:
    text = _text(value)
    folded = text.casefold()
    if _unknown(text):
        return _result(
            key, label, STATUS_UNKNOWN, f"{field_name} is unknown or blank.", f"Verify {field_name}.", (field_name,)
        )
    if folded in good:
        return _result(key, label, STATUS_COMPLIANT, f"{field_name} is documented as {text}.", "", (field_name,))
    if any(token in folded for token in fail_tokens):
        return _result(
            key, label, STATUS_FAIL, f"{field_name} indicates a standards failure: {text}.", action, (field_name,)
        )
    if any(token in folded for token in warning_tokens):
        return _result(key, label, STATUS_WARNING, f"{field_name} needs review: {text}.", action, (field_name,))
    return _result(
        key,
        label,
        STATUS_WARNING,
        f"{field_name} value is documented but not recognized as verified compliant: {text}.",
        f"Review {field_name} against the local standard.",
        (field_name,),
    )


def _result(
    key: str,
    label: str,
    status: str,
    reason: str,
    recommended_action: str,
    related_fields: tuple[str, ...],
) -> ComplianceCategoryResult:
    return ComplianceCategoryResult(
        key=key,
        label=label,
        status=status,
        score=STATUS_SCORES.get(status),
        reason=reason,
        recommended_action=recommended_action,
        related_fields=related_fields,
    )


def _is_physical_audit(row: dict[str, Any]) -> bool:
    return _text(row.get(ENTRY_TYPE_FIELD)).casefold() != ENTRY_TYPE_COMPATIBLE.casefold()


def _unknown(value: Any) -> bool:
    text = _text(value)
    folded = text.casefold()
    return (
        not text
        or folded in {"unknown / not checked", "unknown", "not checked", "unknown / needs review"}
        or folded.startswith("unknown")
    )


def _yes(value: Any) -> bool:
    return _text(value).casefold() == "yes"


def _no(value: Any) -> bool:
    return _text(value).casefold() == "no"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _pilot_relevance(audits: list[AuditComplianceResult], _unused: list[str]) -> str:
    if any(audit.overall_score < 60 for audit in audits):
        return "Review standards gaps before pilot selection"
    if any(audit.failed_standards or audit.warnings for audit in audits):
        return "Standards follow-up may affect pilot readiness"
    return "No standards blocker from scored audits"


__all__ = [
    "AuditComplianceResult",
    "ComplianceCategoryResult",
    "PressComplianceRollup",
    "StandardsComplianceSummary",
    "analyze_standards_compliance",
    "generate_standards_compliance_report",
    "rollup_compliance_by_press",
    "score_audit_compliance",
]
