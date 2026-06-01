from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .analysis_common import timestamp_for_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .workbook_io import row_dicts

TOOL_ID = "work_instruction_builder"
TOOL_NAME = "EOAT Work Instruction Builder"

INSTRUCTION_TYPES: tuple[tuple[str, str, str], ...] = (
    ("operator_inspection", "Operator EOAT Inspection Checklist", "Operator"),
    ("technician_troubleshooting", "Technician Troubleshooting Guide", "Technician"),
    ("eoat_rebuild", "EOAT Rebuild Checklist", "Maintenance / Toolroom"),
    ("part_drop_response", "What To Do On Part Drop", "Operator / Technician"),
    ("after_changeover", "After-Changeover Check", "Operator / Setup"),
    ("pm_checklist", "PM Checklist", "Maintenance"),
    ("sensor_verification", "Sensor Verification Guide", "Technician"),
    ("vacuum_gripper_troubleshooting", "Vacuum / Gripper Troubleshooting Guide", "Technician"),
)


@dataclass(frozen=True)
class WorkInstructionDocument:
    instruction_key: str
    title: str
    audience: str
    audit_id: str
    machine: str
    eoat_type: str
    markdown: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("markdown", None)
        return data


@dataclass(frozen=True)
class WorkInstructionSet:
    audit_id: str
    machine: str
    documents: tuple[WorkInstructionDocument, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "machine": self.machine,
            "document_count": len(self.documents),
            "warnings": list(self.warnings),
            "documents": [document.to_dict() for document in self.documents],
        }


def build_work_instruction_documents(
    project_root: str | Path, *, audit_id: str = "", machine: str = ""
) -> WorkInstructionSet:
    row = _select_audit_row(project_root, audit_id=audit_id, machine=machine)
    if row is None:
        warning = "No matching EOAT Inventory audit row found; work instructions were not generated."
        return WorkInstructionSet(audit_id=audit_id, machine=machine, documents=(), warnings=(warning,))
    row = repair_legacy_audit_lookup_shift(row)
    warnings = tuple(_missing_evidence_warnings(row))
    documents = tuple(
        _build_document(row, key, title, audience, warnings) for key, title, audience in INSTRUCTION_TYPES
    )
    return WorkInstructionSet(
        audit_id=_clean(row.get("Audit ID")),
        machine=_clean(row.get("Press/Machine #")),
        documents=documents,
        warnings=warnings,
    )


def generate_work_instructions(
    project_root: str | Path, *, audit_id: str = "", machine: str = "", log_activity: bool = True
) -> ToolResult:
    start = time.perf_counter()
    instruction_set = build_work_instruction_documents(project_root, audit_id=audit_id, machine=machine)
    if not instruction_set.documents:
        return ToolResult.fail(
            TOOL_ID, TOOL_NAME, "No work instructions were generated.", warnings=list(instruction_set.warnings)
        )
    output_dir = ensure_directory(
        resolve_project_paths(project_root).work_instructions
        / _slug(instruction_set.audit_id or instruction_set.machine or "EOAT")
    )
    stamp = timestamp_for_report()
    files_created: list[str] = []
    try:
        for document in instruction_set.documents:
            path = output_dir / f"{_slug(document.instruction_key)}_{stamp}.md"
            files_created.append(str(safe_write_text(path, document.markdown, overwrite=False)))
        index = _build_index_markdown(instruction_set, files_created)
        files_created.append(
            str(safe_write_text(output_dir / f"Work_Instruction_Index_{stamp}.md", index, overwrite=False))
        )
    except Exception as exc:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "Could not write work instruction files.", errors=[str(exc)])
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        f"Generated {len(instruction_set.documents)} work instruction document(s).",
        details=[
            f"Audit ID: {instruction_set.audit_id}",
            f"Machine: {instruction_set.machine}",
            f"Output folder: {output_dir}",
        ],
        warnings=list(instruction_set.warnings),
        files_created=files_created,
        output_reports=files_created,
        structured_data=instruction_set.to_dict(),
        metrics={"document_count": len(instruction_set.documents), "warning_count": len(instruction_set.warnings)},
        duration_seconds=time.perf_counter() - start,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _build_document(
    row: dict[str, Any], key: str, title: str, audience: str, warnings: tuple[str, ...]
) -> WorkInstructionDocument:
    audit_id = _clean(row.get("Audit ID")) or "N/A"
    machine = _clean(row.get("Press/Machine #")) or "N/A"
    eoat_type = _clean(row.get("EOAT Type")) or "Unknown"
    lines = [
        f"# {title}",
        "",
        f"- Audience: {audience}",
        f"- Source Audit ID: {audit_id}",
        f"- Press/Machine #: {machine}",
        f"- EOAT Type: {eoat_type}",
        f"- Robot Type: {_clean(row.get('Robot Type')) or 'Not documented'}",
        f"- Tool #: {_clean(row.get('Tool #')) or 'Not documented'}",
        f"- Part Family: {_clean(row.get('Part Family')) or 'Not documented'}",
        "",
        "## Source Audit Facts",
        *_source_fact_lines(row),
        "",
        "## Documentation And Evidence Status",
        *_documentation_status_lines(row),
        "",
        "## Procedure",
        *_procedure_steps(key, row),
        "",
        "## Stop And Escalate If",
        "- The EOAT is loose, damaged, leaking, or not repeating position.",
        "- A sensor or confirmation signal does not match the observed part condition.",
        "- A part drop, mis-pick, unexpected scrap issue, or cycle-time change occurs.",
        "- Required documentation or evidence is missing for a step that needs verification.",
    ]
    if warnings:
        lines.extend(["", "## Missing Evidence Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(
        [
            "",
            "## Use Notes",
            "- This instruction was generated from audit data and must be reviewed before controlled release.",
            "- Missing photos, CAD, BOM, or process binder entries are not treated as available evidence.",
        ]
    )
    return WorkInstructionDocument(
        instruction_key=key,
        title=title,
        audience=audience,
        audit_id=audit_id,
        machine=machine,
        eoat_type=eoat_type,
        markdown="\n".join(lines) + "\n",
        warnings=warnings,
    )


def _procedure_steps(key: str, row: dict[str, Any]) -> list[str]:
    base = [
        "- Verify the EOAT matches the documented machine, tool number, and part family before work starts.",
        "- Review known issues and follow-up notes before running the EOAT.",
    ]
    type_steps = _eoat_type_steps(row)
    procedures = {
        "operator_inspection": [
            *base,
            "- Check mounting hardware, alignment, tubing, cable management, and quick disconnect condition.",
            "- Confirm required photo/document references are available before relying on them.",
            *type_steps,
        ],
        "technician_troubleshooting": [
            *base,
            "- Start with observed symptom, then inspect routing, connections, sensors, and mechanical wear points.",
            "- Compare findings against known issues and drop/mis-pick history from the audit.",
            *type_steps,
        ],
        "eoat_rebuild": [
            *base,
            "- Confirm BOM and CAD availability before disassembly; if missing, capture actual part details during teardown.",
            "- Replace worn cups, jaws, tubing, fittings, sensors, fasteners, and labels based on verified condition.",
            "- Rebuild to the documented EOAT type, circuit count, sensor configuration, and connection style.",
            *type_steps,
        ],
        "part_drop_response": [
            "- Stop the cycle and secure the area according to plant procedure.",
            "- Record machine, tool, part, EOAT type, symptom, and first observed condition.",
            "- Inspect cups/grippers, tubing, sensors, cable management, quick disconnects, and alignment before restart.",
            "- Capture photos if evidence is missing or condition changed.",
        ],
        "after_changeover": [
            "- Verify EOAT mounted securely and connected to the documented pneumatic/electrical interfaces.",
            "- Confirm vacuum/gripper actuation, sensor operation, dry cycle, and first-part pickup before production.",
            "- Record cycle time, drop/mis-pick result, scrap/quality concerns, photos, and signoff.",
        ],
        "pm_checklist": [
            *base,
            "- Follow the documented maintenance frequency and inspect all condition fields marked fair, poor, leaking, loose, or needs verification.",
            *type_steps,
        ],
        "sensor_verification": [
            "- Confirm whether sensors are documented as present before using this guide as a release check.",
            "- Verify sensor type, brand/model, mounting, cable management, and confirmation response.",
            "- Test part-present and vacuum confirmation behavior where documented.",
        ],
        "vacuum_gripper_troubleshooting": [
            *base,
            *type_steps,
            "- For hybrid tools, verify vacuum and mechanical functions independently before combined operation.",
        ],
    }
    return procedures.get(key, base)


def _eoat_type_steps(row: dict[str, Any]) -> list[str]:
    eoat_type = _clean(row.get("EOAT Type")).casefold()
    steps: list[str] = []
    if "vacuum" in eoat_type or "hybrid" in eoat_type or not eoat_type:
        steps.extend(
            [
                f"- Verify vacuum cups: count {_display(row.get('# of Cups'))}, material {_display(row.get('Cup Type/Material'))}, size {_display(row.get('Cup Diameter/Size'))}.",
                f"- Verify vacuum generator and circuits: generator {_display(row.get('Vacuum Generator Type'))}, vacuum circuits {_display(row.get('EOAT Vacuum Circuits'))}.",
                "- Inspect vacuum tubing for leaks, kinks, abrasion, and poor bend radius.",
            ]
        )
    if "gripper" in eoat_type or "mechanical" in eoat_type or "hybrid" in eoat_type:
        steps.extend(
            [
                f"- Verify grippers: count {_display(row.get('# of Grippers'))}, type {_display(row.get('Gripper Type'))}, model {_display(row.get('Gripper Model'))}.",
                "- Inspect jaws/fingers, cylinders/actuators, pivots, pads, and mechanical stops.",
            ]
        )
    if _yes(row.get("Sensors Present?")) or _yes(row.get("Part-Present Detection Present?")):
        steps.append(
            f"- Verify sensors: type {_display(row.get('Sensor Type'))}, brand/model {_display(row.get('Sensor Brand/Model'))}."
        )
    return steps or [
        "- EOAT type is not documented; inspect vacuum, gripper, sensor, routing, and mounting systems before use."
    ]


def _source_fact_lines(row: dict[str, Any]) -> list[str]:
    fields = [
        "Known Issues",
        "Drop/Mis-Pick History",
        "Tubing Condition",
        "Tubing Routing Notes",
        "Cable Management Condition",
        "Mounting Hardware Condition",
        "EOAT Alignment Condition",
        "Maintenance Frequency",
        "Changeover Difficulty",
        "Cycle Time Concern?",
        "Scrap/Quality Concern?",
    ]
    return [f"- {field}: {_display(row.get(field))}" for field in fields]


def _documentation_status_lines(row: dict[str, Any]) -> list[str]:
    return [
        f"- Photos: {_availability(row, 'Photos Taken?', link_field='Photo Folder/Link')}",
        f"- Photo Folder/Link: {_display(row.get('Photo Folder/Link'))}",
        f"- CAD/Drawing: {_availability(row, 'Drawing/CAD Available?')}",
        f"- BOM: {_availability(row, 'BOM Available?')}",
        f"- Process Binder: {_availability(row, 'Process Binder Complete?')}",
        f"- Spare Parts: {_availability(row, 'Spare Parts Identified?')}",
    ]


def _missing_evidence_warnings(row: dict[str, Any]) -> list[str]:
    machine = _clean(row.get("Press/Machine #")) or _clean(row.get("Audit ID")) or "selected EOAT"
    warnings: list[str] = []
    for label, field in [
        ("photos", "Photos Taken?"),
        ("CAD/drawing", "Drawing/CAD Available?"),
        ("BOM", "BOM Available?"),
        ("process binder", "Process Binder Complete?"),
    ]:
        value = _clean(row.get(field)).casefold()
        if value not in {"yes", "y", "complete", "available"}:
            warnings.append(f"{machine}: {label} not documented as available.")
    if _yes(row.get("Photos Taken?")) and not _clean(row.get("Photo Folder/Link")):
        warnings.append(f"{machine}: photos marked Yes but no photo folder/link is documented.")
    return warnings


def _availability(row: dict[str, Any], field: str, *, link_field: str = "") -> str:
    value = _clean(row.get(field))
    folded = value.casefold()
    if folded in {"yes", "y", "complete", "available"}:
        if link_field and not _clean(row.get(link_field)):
            return "Available flag is Yes, but link is missing."
        return "Available per audit data."
    if folded in {"no", "n", "missing", "not available", "incomplete"}:
        return "Missing per audit data."
    return "Not documented."


def _select_audit_row(project_root: str | Path, *, audit_id: str = "", machine: str = "") -> dict[str, Any] | None:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return None
    try:
        rows = row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception:
        return None
    audit_key = audit_id.strip().casefold()
    machine_key = machine.strip().casefold()
    for row in rows:
        if audit_key and _clean(row.get("Audit ID")).casefold() == audit_key:
            return row
    for row in rows:
        if machine_key and _clean(row.get("Press/Machine #")).casefold() == machine_key:
            return row
    return rows[0] if rows and not audit_key and not machine_key else None


def _build_index_markdown(instruction_set: WorkInstructionSet, files_created: list[str]) -> str:
    lines = [
        "# Work Instruction Set Index",
        "",
        f"- Audit ID: {instruction_set.audit_id}",
        f"- Press/Machine #: {instruction_set.machine}",
        f"- Document count: {len(instruction_set.documents)}",
        "",
        "## Documents",
    ]
    lines.extend(f"- {Path(path).name}" for path in files_created)
    if instruction_set.warnings:
        lines.extend(["", "## Missing Evidence Warnings"])
        lines.extend(f"- {warning}" for warning in instruction_set.warnings)
    return "\n".join(lines) + "\n"


def _display(value: Any) -> str:
    return _clean(value) or "Not documented"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _yes(value: Any) -> bool:
    return _clean(value).casefold() in {"yes", "y", "true", "1", "available", "complete"}


def _slug(text: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in text.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "EOAT"


__all__ = [
    "INSTRUCTION_TYPES",
    "WorkInstructionDocument",
    "WorkInstructionSet",
    "build_work_instruction_documents",
    "generate_work_instructions",
]
