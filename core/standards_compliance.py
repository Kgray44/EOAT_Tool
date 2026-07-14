from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import table_from_rows, write_timestamped_csv, write_timestamped_report
from .audit_constants import (
    AUDIT_CONTEXT_BENCH,
    AUDIT_CONTEXT_COMPATIBILITY,
    AUDIT_CONTEXT_FIELD,
    AUDIT_CONTEXT_INSTALLED,
    COMPATIBILITY_CONFIDENCE_FIELD,
    ENTRY_TYPE_FIELD,
)
from .audit_context import infer_audit_context
from .audit_field_rules import eoat_type_uses_gripper, eoat_type_uses_vacuum, is_meaningful_value, is_na_value
from .audit_scores import calculate_split_scores
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
STATUS_NOT_OBSERVABLE = "not observable"
STATUS_FOLLOW_UP_REQUIRED = "follow-up required"

STATUS_SCORES = {
    STATUS_COMPLIANT: 100,
    STATUS_WARNING: 60,
    STATUS_FAIL: 0,
    STATUS_UNKNOWN: 40,
    STATUS_NOT_OBSERVABLE: None,
    STATUS_FOLLOW_UP_REQUIRED: None,
}

ISSUE_TRUE_FAILURE = "true_standard_failure"
ISSUE_DOCUMENTATION_GAP = "documentation_gap"
ISSUE_INSTALLATION_FOLLOW_UP = "installation_follow_up"
ISSUE_COMPATIBILITY_DATA = "compatibility_data_issue"
ISSUE_UNKNOWN_REVIEW = "unknown_needs_review"
ISSUE_NOT_OBSERVABLE = "not_observable_due_to_context"


@dataclass(frozen=True)
class ComplianceCategoryResult:
    key: str
    label: str
    status: str
    score: int | None
    reason: str
    recommended_action: str
    related_fields: tuple[str, ...] = field(default_factory=tuple)
    issue_group: str = ISSUE_TRUE_FAILURE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditComplianceResult:
    audit_id: str
    machine: str
    audit_context: str
    eoat_assembly_id: str
    tool_numbers: str
    plant_area: str
    eoat_type: str
    overall_score: int
    eoat_documentation_score: int
    installation_readiness_score: int
    installed_cell_validation_score: int | str
    true_fail_count: int
    documentation_gap_count: int
    follow_up_count: int
    unknown_count: int
    not_observable_count: int
    notes_recommended_action: str
    category_results: tuple[ComplianceCategoryResult, ...]

    @property
    def failed_standards(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(
            result
            for result in self.category_results
            if result.status == STATUS_FAIL and result.issue_group == ISSUE_TRUE_FAILURE
        )

    @property
    def warnings(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(result for result in self.category_results if result.status == STATUS_WARNING)

    @property
    def unknown_items(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(result for result in self.category_results if result.status == STATUS_UNKNOWN)

    @property
    def installation_follow_ups(self) -> tuple[ComplianceCategoryResult, ...]:
        return tuple(
            result
            for result in self.category_results
            if result.issue_group in {ISSUE_INSTALLATION_FOLLOW_UP, ISSUE_NOT_OBSERVABLE}
        )

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
            "audit_context": self.audit_context,
            "eoat_assembly_id": self.eoat_assembly_id,
            "tool_numbers": self.tool_numbers,
            "plant_area": self.plant_area,
            "eoat_type": self.eoat_type,
            "overall_score": self.overall_score,
            "eoat_documentation_score": self.eoat_documentation_score,
            "installation_readiness_score": self.installation_readiness_score,
            "installed_cell_validation_score": self.installed_cell_validation_score,
            "true_fail_count": self.true_fail_count,
            "documentation_gap_count": self.documentation_gap_count,
            "follow_up_count": self.follow_up_count,
            "unknown_count": self.unknown_count,
            "not_observable_count": self.not_observable_count,
            "notes_recommended_action": self.notes_recommended_action,
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
                "EOAT Assembly ID": audit.eoat_assembly_id,
                "Tool #s": audit.tool_numbers,
                "Press/Machine #": audit.machine,
                "Audit Context": audit.audit_context,
                "EOAT Type": audit.eoat_type,
                "EOAT Documentation Score": f"{audit.eoat_documentation_score}%",
                "Installation Readiness Score": f"{audit.installation_readiness_score}%",
                "Installed-Cell Validation Score": audit.installed_cell_validation_score,
                "True Fails": audit.true_fail_count,
                "Documentation Gaps": audit.documentation_gap_count,
                "Follow-Up": audit.follow_up_count,
                "Unknown": audit.unknown_count,
                "Notes / Recommended Action": audit.notes_recommended_action,
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
            f"- Average EOAT documentation score: {self.metrics.get('average_compliance_score', 0)}",
            f"- True standards failures: {self.metrics.get('true_standard_failure_count', 0)}",
            f"- EOAT documentation gaps: {self.metrics.get('documentation_gap_count', 0)}",
            f"- Installation follow-up items: {self.metrics.get('installation_follow_up_count', 0)}",
            f"- Fit Check/data issues: {self.metrics.get('compatibility_data_issue_count', 0)}",
            f"- Unknown / needs review: {self.metrics.get('unknown_standard_count', 0)}",
            f"- Not observable due to audit context: {self.metrics.get('not_observable_count', 0)}",
            "",
            "## Audit Compliance By EOAT",
            *table_from_rows(
                rows,
                [
                    "Audit ID",
                    "EOAT Assembly ID",
                    "Tool #s",
                    "Press/Machine #",
                    "Audit Context",
                    "EOAT Documentation Score",
                    "Installation Readiness Score",
                    "Installed-Cell Validation Score",
                    "True Fails",
                    "Documentation Gaps",
                    "Follow-Up",
                    "Unknown",
                    "Notes / Recommended Action",
                ],
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
            "- EOAT documentation, compatibility, and installed-cell validation are scored separately.",
            "- Not Observable, Not Applicable, and Follow-up Required are not collapsed into Fail.",
            "- Off-machine EOAT audits evaluate EOAT-level documentation normally and log machine-specific checks as future installed-cell follow-up.",
        ]
        return "\n".join(lines) + "\n"


def score_audit_compliance(project_root: str | Path, row: dict[str, Any]) -> AuditComplianceResult:
    audit_context = infer_audit_context(row)
    split_scores = calculate_split_scores(row)
    categories = (
        _classification_complete(row),
        _tooling_details_complete(row),
        _pneumatic_routing(row),
        _sensor_standards(row),
        _quick_disconnect_standards(row),
        _cable_management(row),
        _mechanical_mounting(row, audit_context=audit_context),
        _safety_concerns(row, audit_context=audit_context),
        _documentation_completeness(row),
        _pm_readiness(row),
        _bom_spare_parts_readiness(row),
        _photo_evidence_readiness(project_root, row),
        _installed_cell_validation_context(row, audit_context=audit_context),
        _compatibility_context(row, audit_context=audit_context),
    )
    overall = int(split_scores.eoat_documentation.score)
    true_fail_count = sum(
        1 for result in categories if result.status == STATUS_FAIL and result.issue_group == ISSUE_TRUE_FAILURE
    )
    documentation_gap_count = sum(1 for result in categories if result.issue_group == ISSUE_DOCUMENTATION_GAP)
    follow_up_count = sum(1 for result in categories if result.issue_group == ISSUE_INSTALLATION_FOLLOW_UP)
    unknown_count = sum(
        1
        for result in categories
        if result.status == STATUS_UNKNOWN or result.issue_group == ISSUE_UNKNOWN_REVIEW
    )
    not_observable_count = sum(1 for result in categories if result.issue_group == ISSUE_NOT_OBSERVABLE)
    return AuditComplianceResult(
        audit_id=_text(row.get("Audit ID")),
        machine=_text(row.get("Press/Machine #")),
        audit_context=audit_context,
        eoat_assembly_id=_text(row.get("EOAT Assembly ID")),
        tool_numbers=_text(row.get("Tool #")),
        plant_area=_text(row.get("Plant/Area")),
        eoat_type=_text(row.get("EOAT Type")),
        overall_score=overall,
        eoat_documentation_score=overall,
        installation_readiness_score=int(split_scores.installation_readiness.score),
        installed_cell_validation_score=split_scores.installed_cell_validation.score,
        true_fail_count=true_fail_count,
        documentation_gap_count=documentation_gap_count,
        follow_up_count=follow_up_count,
        unknown_count=unknown_count,
        not_observable_count=not_observable_count,
        notes_recommended_action=_recommended_action_note(audit_context),
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
    audits = tuple(score_audit_compliance(project_root, row) for row in rows if _text(row.get("Audit ID")))
    rollups = tuple(rollup_compliance_by_press(audits))
    scores = [audit.overall_score for audit in audits]
    summary = StandardsComplianceSummary(
        audits=audits,
        press_rollups=rollups,
        metrics={
            "audits_scored": len(audits),
            "average_compliance_score": round(sum(scores) / len(scores)) if scores else 0,
            "failed_standard_count": sum(len(audit.failed_standards) for audit in audits),
            "true_standard_failure_count": sum(audit.true_fail_count for audit in audits),
            "documentation_gap_count": sum(audit.documentation_gap_count for audit in audits),
            "installation_follow_up_count": sum(audit.follow_up_count for audit in audits),
            "compatibility_data_issue_count": sum(
                1
                for audit in audits
                for result in audit.category_results
                if result.issue_group == ISSUE_COMPATIBILITY_DATA and result.status != STATUS_COMPLIANT
            ),
            "not_observable_count": sum(audit.not_observable_count for audit in audits),
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
            "EOAT Assembly ID": audit.eoat_assembly_id,
            "Tool #s": audit.tool_numbers,
            "Press/Machine #": audit.machine,
            "Audit Context": audit.audit_context,
            "EOAT Type": audit.eoat_type,
            "EOAT Documentation Score": audit.eoat_documentation_score,
            "Installation Readiness Score": audit.installation_readiness_score,
            "Installed-Cell Validation Score": audit.installed_cell_validation_score,
            "True Fail Count": audit.true_fail_count,
            "Documentation Gap Count": audit.documentation_gap_count,
            "Follow-Up Count": audit.follow_up_count,
            "Unknown Count": audit.unknown_count,
            "Not Observable Count": audit.not_observable_count,
            "Notes / Recommended Action": audit.notes_recommended_action,
            "True Standards Failures": "; ".join(
                result.label for result in audit.category_results if result.issue_group == ISSUE_TRUE_FAILURE
            ),
            "EOAT Documentation Gaps": "; ".join(
                result.label for result in audit.category_results if result.issue_group == ISSUE_DOCUMENTATION_GAP
            ),
            "Installation Follow-Up Items": "; ".join(
                result.label for result in audit.category_results if result.issue_group == ISSUE_INSTALLATION_FOLLOW_UP
            ),
            "Fit Check/Data Issues": "; ".join(
                result.label for result in audit.category_results if result.issue_group == ISSUE_COMPATIBILITY_DATA
            ),
            "Unknown / Needs Review": "; ".join(
                result.label for result in audit.category_results if result.issue_group == ISSUE_UNKNOWN_REVIEW
            ),
            "Not Observable Due to Audit Context": "; ".join(
                result.label for result in audit.category_results if result.issue_group == ISSUE_NOT_OBSERVABLE
            ),
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
            ISSUE_DOCUMENTATION_GAP,
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
            ISSUE_DOCUMENTATION_GAP,
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
            ISSUE_DOCUMENTATION_GAP,
        )
    if not any(is_meaningful_value(row.get(field)) for field in fields[1:]):
        return _result(
            "quick_disconnect_standards",
            "Quick disconnect standard",
            STATUS_WARNING,
            "Quick disconnects are present but type fields are missing.",
            "Document the applicable quick disconnect type(s).",
            fields,
            ISSUE_DOCUMENTATION_GAP,
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


def _mechanical_mounting(row: dict[str, Any], *, audit_context: str) -> ComplianceCategoryResult:
    fields = (
        ("Mounting Hardware Condition", "Fastener/Locking Hardware Present?")
        if audit_context != AUDIT_CONTEXT_INSTALLED
        else ("Mounting Hardware Condition", "EOAT Alignment Condition", "Fastener/Locking Hardware Present?")
    )
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
            ISSUE_DOCUMENTATION_GAP if audit_context != AUDIT_CONTEXT_INSTALLED else ISSUE_UNKNOWN_REVIEW,
        )
    return _result(
        "mechanical_mounting",
        "Mechanical mounting",
        STATUS_COMPLIANT,
        "Mechanical mounting and alignment fields are documented without flagged issues.",
        "",
        fields,
    )


def _safety_concerns(row: dict[str, Any], *, audit_context: str) -> ComplianceCategoryResult:
    fields = (
        ("Known Issues", "Follow-Up Needed")
        if audit_context != AUDIT_CONTEXT_INSTALLED
        else ("Known Issues", "Scrap/Quality Concern?", "Cycle Time Concern?", "Follow-Up Needed")
    )
    issue = _text(row.get("Known Issues"))
    machine_specific_concern = audit_context == AUDIT_CONTEXT_INSTALLED and _yes(row.get("Scrap/Quality Concern?"))
    if _yes(row.get("Follow-Up Needed")) or machine_specific_concern:
        return _result(
            "safety_concerns",
            "Safety concerns",
            STATUS_WARNING,
            "Follow-up, scrap, or quality concern is flagged.",
            "Review safety/quality risk before closing this audit.",
            fields,
            ISSUE_INSTALLATION_FOLLOW_UP if audit_context != AUDIT_CONTEXT_INSTALLED else ISSUE_TRUE_FAILURE,
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
            ISSUE_DOCUMENTATION_GAP,
        )
    return _result(
        "documentation_completeness",
        "Documentation completeness",
        STATUS_FAIL,
        f"Documentation gaps remain: {', '.join(missing)}.",
        "Find documentation or record the gap as intentional follow-up.",
        fields,
        ISSUE_DOCUMENTATION_GAP,
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
            ISSUE_DOCUMENTATION_GAP,
        )
    if _no(row.get("Process Binder Complete?")):
        return _result(
            "pm_readiness",
            "PM readiness",
            STATUS_WARNING,
            "Process binder is not complete.",
            "Complete binder references before calling PM readiness complete.",
            fields,
            ISSUE_DOCUMENTATION_GAP,
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
            ISSUE_DOCUMENTATION_GAP,
        )
    if not is_bom_available(row) or is_spare_parts_info_missing(row):
        return _result(
            "bom_spare_parts_readiness",
            "BOM/spare parts readiness",
            STATUS_FAIL,
            "BOM and spare-parts readiness is not complete.",
            "Confirm BOM and spare-parts availability before standardization handoff.",
            fields,
            ISSUE_DOCUMENTATION_GAP,
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
            ISSUE_DOCUMENTATION_GAP,
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
            ISSUE_DOCUMENTATION_GAP,
        )
    if follow_up:
        return _result(
            "photo_evidence_readiness",
            "Photo evidence readiness",
            STATUS_WARNING,
            f"Recommended evidence still needs follow-up: {', '.join(follow_up[:4])}.",
            "Capture recommended evidence where practical.",
            ("Photos Taken?", "Photo Folder/Link"),
            ISSUE_DOCUMENTATION_GAP,
        )
    return _result(
        "photo_evidence_readiness",
        "Photo evidence readiness",
        STATUS_COMPLIANT,
        "Required photo evidence categories are covered or not applicable.",
        "",
        ("Photos Taken?", "Photo Folder/Link"),
    )


def _installed_cell_validation_context(row: dict[str, Any], *, audit_context: str) -> ComplianceCategoryResult:
    fields = ("Press/Machine #", "Robot Type", "Robot Model/Controller", "EOAT Alignment Condition")
    if audit_context == AUDIT_CONTEXT_INSTALLED:
        missing = [field for field in fields if _unknown(row.get(field)) or is_na_value(row.get(field))]
        if missing:
            return _result(
                "installed_cell_validation_context",
                "Installed-cell validation",
                STATUS_UNKNOWN,
                f"Installed-cell fields need review: {', '.join(missing)}.",
                "Complete robot and installed-cell validation details for this machine relationship.",
                fields,
                ISSUE_INSTALLATION_FOLLOW_UP,
            )
        return _result(
            "installed_cell_validation_context",
            "Installed-cell validation",
            STATUS_COMPLIANT,
            "Installed machine context is documented.",
            "",
            fields,
        )
    if audit_context == AUDIT_CONTEXT_COMPATIBILITY:
        return _result(
            "installed_cell_validation_context",
            "Installed-cell validation",
            STATUS_FOLLOW_UP_REQUIRED,
            "Fit Check row is not a physical installed-cell validation.",
            "Physically install and validate the EOAT on this machine before treating it as installed-cell verified.",
            fields,
            ISSUE_INSTALLATION_FOLLOW_UP,
        )
    if audit_context == AUDIT_CONTEXT_BENCH:
        return _result(
            "installed_cell_validation_context",
            "Installed-cell validation",
            STATUS_NOT_OBSERVABLE,
            "EOAT was audited off-machine; installed-cell checks were not observable.",
            "Follow up when the EOAT is mounted and observed on a press.",
            fields,
            ISSUE_NOT_OBSERVABLE,
        )
    return _result(
        "installed_cell_validation_context",
        "Installed-cell validation",
        STATUS_UNKNOWN,
        "Audit context needs review before installed-cell validation can be interpreted.",
        "Set Audit Context to Installed on Machine, Not Installed / Bench Audit, Fit Check row, or Historical/imported.",
        fields,
        ISSUE_UNKNOWN_REVIEW,
    )


def _compatibility_context(row: dict[str, Any], *, audit_context: str) -> ComplianceCategoryResult:
    fields = (AUDIT_CONTEXT_FIELD, ENTRY_TYPE_FIELD, "Tool #", "Press/Machine #", COMPATIBILITY_CONFIDENCE_FIELD)
    if audit_context != AUDIT_CONTEXT_COMPATIBILITY:
        return _result(
            "compatibility_context",
            "Fit Check/data context",
            STATUS_NOT_APPLICABLE,
            "This row is not a Fit Check relationship row.",
            "",
            fields,
            ISSUE_COMPATIBILITY_DATA,
        )
    missing = [field for field in ("Tool #", "Press/Machine #") if _unknown(row.get(field)) or is_na_value(row.get(field))]
    if missing:
        return _result(
            "compatibility_context",
            "Fit Check/data context",
            STATUS_WARNING,
            f"Fit Check row is missing relationship data: {', '.join(missing)}.",
            "Complete the EOAT/tool/machine relationship or mark the row Needs review.",
            fields,
            ISSUE_COMPATIBILITY_DATA,
        )
    return _result(
        "compatibility_context",
            "Fit Check/data context",
        STATUS_WARNING,
        "Compatible based on EOAT/tool data; not yet physically verified on this machine.",
        "Use this row for relationship coverage only until an installed-cell audit is completed.",
        fields,
        ISSUE_COMPATIBILITY_DATA,
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
    issue_group: str = ISSUE_TRUE_FAILURE,
) -> ComplianceCategoryResult:
    if status == STATUS_UNKNOWN and issue_group == ISSUE_TRUE_FAILURE:
        issue_group = ISSUE_UNKNOWN_REVIEW
    return ComplianceCategoryResult(
        key=key,
        label=label,
        status=status,
        score=STATUS_SCORES.get(status),
        reason=reason,
        recommended_action=recommended_action,
        related_fields=related_fields,
        issue_group=issue_group,
    )


def _is_physical_audit(row: dict[str, Any]) -> bool:
    return infer_audit_context(row) != AUDIT_CONTEXT_COMPATIBILITY


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


def _recommended_action_note(audit_context: str) -> str:
    if audit_context == AUDIT_CONTEXT_BENCH:
        return (
            "This EOAT was audited off-machine. EOAT-level documentation was evaluated normally. "
            "Machine-specific installation checks were excluded from failure scoring and logged as follow-up items "
            "for future installed-cell validation."
        )
    if audit_context == AUDIT_CONTEXT_COMPATIBILITY:
        return "Fit Check row only; use for EOAT-to-machine relationship coverage until physically verified."
    return "Review grouped findings and complete any documented follow-up."


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
