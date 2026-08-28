from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, aliased

from .contracts import (
    DataStatus,
    FitCheckAlternative,
    FitCheckCriterion,
    FitCheckDetailSection,
    FitCheckEntity,
    FitCheckRequest,
    FitCheckResult,
    FitCheckWarning,
    PairCompatibility,
    SyncChange,
    SyncChangeBatch,
    SyncSnapshot,
    SyncStatus,
)
from .database import models as db
from .repositories import AtlasRepository
from .security import ActorContext

API_VERSION = "1.4.0"
EXPECTED_SCHEMA_REVISION = "20260827_0016"
SERVER_REVISION = "mysql-cutover-rehearsal-rc1"

# The migration imports an observed, source-traceable setup as ``observed``.
# It is usable compatibility evidence, but it is deliberately distinct from a
# later engineering-verification status. Unknown and review-only records must
# never become selector candidates merely because a row exists.
SELECTABLE_COMPATIBILITY_STATUS_CODES = frozenset({"compatible", "verified_compatible", "approved", "observed"})
INCOMPATIBLE_STATUS_CODES = frozenset({"incompatible", "failed", "not_compatible"})


class AtlasService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = AtlasRepository(session)

    def _selected_entities(self, request: FitCheckRequest):
        machine_query = select(db.Machine).where(
            db.Machine.machine_number == request.machine_number,
            db.Machine.is_active.is_(True),
        )
        if request.plant_code:
            machine_query = machine_query.join(db.Plant).where(
                db.Plant.plant_code == request.plant_code,
                db.Plant.is_active.is_(True),
            )
        machines = self.session.scalars(machine_query.order_by(db.Machine.id)).all()
        tools = self.session.scalars(
            select(db.Tool)
            .where(
                (db.Tool.business_identifier == request.tool_number) | (db.Tool.tool_number == request.tool_number),
                db.Tool.is_active.is_(True),
            )
            .order_by(db.Tool.id)
        ).all()
        eoats = self.session.scalars(
            select(db.EOAT)
            .where(
                (db.EOAT.business_identifier == request.eoat_identifier)
                | (db.EOAT.legacy_identifier == request.eoat_identifier),
                db.EOAT.is_active.is_(True),
            )
            .order_by(db.EOAT.id)
        ).all()
        return (
            machines[0] if len(machines) == 1 else None,
            tools[0] if len(tools) == 1 else None,
            eoats[0] if len(eoats) == 1 else None,
        )

    def schema_revision(self) -> str | None:
        return self.session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))

    def fit_check(self, request: FitCheckRequest) -> FitCheckResult:
        machine, tool, eoat = self._selected_entities(request)
        missing = [name for name, value in (("machine", machine), ("tool", tool), ("eoat", eoat)) if value is None]
        if missing:
            unknown = PairCompatibility(
                pair="unresolved_input", result="NOT_EVALUATED", reason="Required entity was not found."
            )
            return FitCheckResult(
                overall_result="INVALID_INPUT",
                machine_tool_result=unknown,
                machine_eoat_result=unknown,
                tool_eoat_result=unknown,
                reasons=[f"Unknown input: {', '.join(missing)}"],
                warnings=[],
                unknown_relationships=missing,
                alternative_compatible_eoats=[],
            )

        now = datetime.now(timezone.utc)

        def status_source(status: str) -> str:
            return {
                "observed": "Observed legacy setup evidence",
                "compatible": "Authoritative compatibility record",
                "verified_compatible": "Engineering-verified compatibility record",
                "approved": "Approved compatibility record",
            }.get(status, f"Authoritative relationship status: {status}")

        def pair_result(pair: str, label: str, subject_label: str, model: type, *criteria):
            row = self.session.execute(
                select(model, db.CompatibilityStatus.code)
                .join(db.CompatibilityStatus, db.CompatibilityStatus.id == model.compatibility_status_id)
                .where(
                    *criteria,
                    model.is_active.is_(True),
                    model.effective_from <= now,
                    or_(model.effective_to.is_(None), model.effective_to >= now),
                )
                .order_by(model.effective_from.desc(), model.id.desc())
            ).first()
            if row is None:
                return (
                    PairCompatibility(
                        pair=pair,
                        result="UNKNOWN",
                        reason=(
                            f"No active, effective {label} relationship is recorded for {subject_label}; "
                            "absence is not incompatibility."
                        ),
                    ),
                    None,
                    None,
                )
            record, status = row
            if status in INCOMPATIBLE_STATUS_CODES:
                return (
                    PairCompatibility(
                        pair=pair,
                        result="INCOMPATIBLE",
                        reason=record.reason
                        or f"The active {label} relationship for {subject_label} is explicitly incompatible.",
                        evidence_source=status_source(status),
                    ),
                    record,
                    status,
                )
            if status not in SELECTABLE_COMPATIBILITY_STATUS_CODES:
                return (
                    PairCompatibility(
                        pair=pair,
                        result="UNKNOWN",
                        reason=(
                            f"The active {label} relationship for {subject_label} has status {status!r} "
                            "and requires verification before setup."
                        ),
                        evidence_source=status_source(status),
                    ),
                    record,
                    status,
                )
            return (
                PairCompatibility(
                    pair=pair,
                    result="COMPATIBLE",
                    reason=record.reason
                    or f"{subject_label} are recorded together in an active, effective compatibility record.",
                    evidence_source=status_source(status),
                ),
                record,
                status,
            )

        machine_tool, machine_tool_record, _ = pair_result(
            "machine_tool",
            "Machine-to-Tool",
            f"Machine {machine.machine_number} and Tool {tool.business_identifier}",
            db.ToolMachineCompatibility,
            db.ToolMachineCompatibility.machine_id == machine.id,
            db.ToolMachineCompatibility.tool_id == tool.id,
        )
        machine_eoat, machine_eoat_record, _ = pair_result(
            "machine_eoat",
            "Machine-to-EOAT",
            f"Machine {machine.machine_number} and EOAT {eoat.business_identifier}",
            db.EOATMachineCompatibility,
            db.EOATMachineCompatibility.machine_id == machine.id,
            db.EOATMachineCompatibility.eoat_id == eoat.id,
        )
        tool_eoat, tool_eoat_record, _ = pair_result(
            "tool_eoat",
            "Tool-to-EOAT",
            f"Tool {tool.business_identifier} and EOAT {eoat.business_identifier}",
            db.EOATToolCompatibility,
            db.EOATToolCompatibility.tool_id == tool.id,
            db.EOATToolCompatibility.eoat_id == eoat.id,
        )
        pairs = [machine_tool, machine_eoat, tool_eoat]
        if any(pair.result == "INCOMPATIBLE" for pair in pairs):
            overall = "INCOMPATIBLE"
        elif all(pair.result == "COMPATIBLE" for pair in pairs):
            overall = "COMPATIBLE"
        else:
            overall = "NEEDS_REVIEW"
        unknowns = [pair.pair for pair in pairs if pair.result == "UNKNOWN"]

        def criterion_from_pair(code: str, label: str, pair: PairCompatibility) -> FitCheckCriterion:
            return FitCheckCriterion(
                code=code,
                label=label,
                result={
                    "COMPATIBLE": "COMPATIBLE",
                    "INCOMPATIBLE": "INCOMPATIBLE",
                }.get(pair.result, "NEEDS_REVIEW"),
                reason=pair.reason,
                evidence_source=pair.evidence_source,
                pair=pair.pair,
            )

        def combined_eoat_result() -> FitCheckCriterion:
            related = (machine_eoat, tool_eoat)
            if any(item.result == "INCOMPATIBLE" for item in related):
                result = "INCOMPATIBLE"
            elif all(item.result == "COMPATIBLE" for item in related):
                result = "COMPATIBLE"
            else:
                result = "NEEDS_REVIEW"
            reasons = [
                f"{label}: {item.reason}"
                for label, item in (("Machine-to-EOAT", machine_eoat), ("Tool-to-EOAT", tool_eoat))
                if item.result != "COMPATIBLE" or result == "COMPATIBLE"
            ]
            return FitCheckCriterion(
                code="eoat_compatibility",
                label="EOAT Fit Check",
                result=result,
                reason=" ".join(reasons),
                evidence_source="Both EOAT relationship records are evaluated together.",
            )

        def criterion_from_flag(
            code: str,
            label: str,
            record,
            pair: PairCompatibility,
            field: str,
            evidence_label: str,
        ) -> FitCheckCriterion:
            if record is None:
                return FitCheckCriterion(
                    code=code,
                    label=label,
                    result="NEEDS_REVIEW",
                    reason=f"{evidence_label} cannot be assessed because {pair.reason[0].lower()}{pair.reason[1:]}",
                    evidence_source=pair.evidence_source,
                    pair=pair.pair,
                )
            value = getattr(record, field)
            if value is True:
                return FitCheckCriterion(
                    code=code,
                    label=label,
                    result="COMPATIBLE",
                    reason=f"The active {pair.pair.replace('_', '-')} record confirms {evidence_label.lower()}.",
                    evidence_source=pair.evidence_source,
                    pair=pair.pair,
                )
            if value is False:
                return FitCheckCriterion(
                    code=code,
                    label=label,
                    result="INCOMPATIBLE",
                    reason=f"The active {pair.pair.replace('_', '-')} record does not satisfy {evidence_label.lower()}.",
                    evidence_source=pair.evidence_source,
                    pair=pair.pair,
                )
            return FitCheckCriterion(
                code=code,
                label=label,
                result="NEEDS_REVIEW",
                reason=f"The active {pair.pair.replace('_', '-')} record has no recorded result for {evidence_label.lower()}.",
                evidence_source=pair.evidence_source,
                pair=pair.pair,
            )

        def air_architecture_criterion() -> FitCheckCriterion:
            """Mirror the desktop rule: only an explicit unmet air requirement fails.

            The desktop evaluates its compact air description.  The normalized API
            has an authoritative utilities flag when engineering has assessed it;
            otherwise the desktop behavior treats the absence of an explicit
            air requirement as compatible; an explicitly unmet requirement is
            the only failure.
            """
            if machine_eoat_record is None:
                return criterion_from_flag(
                    "air_architecture",
                    "Air Architecture",
                    machine_eoat_record,
                    machine_eoat,
                    "utilities_compatible",
                    "the recorded utilities / air architecture",
                )
            if machine_eoat_record.utilities_compatible is False:
                return FitCheckCriterion(
                    code="air_architecture",
                    label="Air Architecture",
                    result="INCOMPATIBLE",
                    reason="The active Machine-to-EOAT record does not satisfy the recorded utilities / air architecture.",
                    evidence_source=machine_eoat.evidence_source,
                    pair=machine_eoat.pair,
                )
            if machine_eoat_record.utilities_compatible is True or eoat.connection_type_id is not None:
                return FitCheckCriterion(
                    code="air_architecture",
                    label="Air Architecture",
                    result="COMPATIBLE",
                    reason="No unmet air-architecture requirement is recorded for this Machine and EOAT.",
                    evidence_source=machine_eoat.evidence_source,
                    pair=machine_eoat.pair,
                )
            return FitCheckCriterion(
                code="air_architecture",
                label="Air Architecture",
                result="COMPATIBLE",
                reason="No unmet air-architecture requirement is recorded for this Machine and EOAT.",
                evidence_source=machine_eoat.evidence_source,
                pair=machine_eoat.pair,
            )

        def quick_disconnect_criterion() -> FitCheckCriterion:
            if eoat.quick_disconnect_present is False:
                return FitCheckCriterion(
                    code="quick_disconnect",
                    label="Pneumatic Quick Disconnect",
                    result="NOT_APPLICABLE",
                    reason="No pneumatic quick-disconnect requirement is recorded for this EOAT.",
                    evidence_source="EOAT equipment record",
                )
            if eoat.quick_disconnect_present is True:
                if machine_eoat_record is not None and machine_eoat_record.connection_compatible is False:
                    return FitCheckCriterion(
                        code="quick_disconnect",
                        label="Pneumatic Quick Disconnect",
                        result="INCOMPATIBLE",
                        reason="The active Machine-to-EOAT record does not satisfy the pneumatic quick-disconnect requirement.",
                        evidence_source=machine_eoat.evidence_source,
                        pair=machine_eoat.pair,
                    )
                return FitCheckCriterion(
                    code="quick_disconnect",
                    label="Pneumatic Quick Disconnect",
                    result="COMPATIBLE",
                    reason="The EOAT record confirms the required pneumatic quick disconnect.",
                    evidence_source="EOAT equipment record",
                    pair=machine_eoat.pair if machine_eoat_record is not None else None,
                )
            return FitCheckCriterion(
                code="quick_disconnect",
                label="Pneumatic Quick Disconnect",
                result="NOT_APPLICABLE",
                reason="No pneumatic quick-disconnect requirement is recorded for this EOAT.",
                evidence_source="EOAT equipment record",
            )

        def sensor_requirement_criterion() -> FitCheckCriterion:
            if eoat.sensors_present is True:
                return FitCheckCriterion(
                    code="sensor_requirements",
                    label="Sensor Requirements",
                    result="COMPATIBLE",
                    reason="The EOAT record confirms its sensor requirement is present.",
                    evidence_source="EOAT equipment record",
                )
            if eoat.sensors_present is False:
                return FitCheckCriterion(
                    code="sensor_requirements",
                    label="Sensor Requirements",
                    result="NOT_APPLICABLE",
                    reason="No sensor requirement is recorded for this EOAT.",
                    evidence_source="EOAT equipment record",
                )
            return FitCheckCriterion(
                code="sensor_requirements",
                label="Sensor Requirements",
                result="NEEDS_REVIEW",
                reason="The EOAT does not record whether sensor requirements are present.",
                evidence_source="EOAT equipment record",
            )

        requirements = [
            criterion_from_pair("machine_compatibility", "Machine Fit Check", machine_tool),
            combined_eoat_result(),
            criterion_from_flag(
                "robot_type",
                "Robot Type",
                machine_eoat_record,
                machine_eoat,
                "robot_interface_compatible",
                "the robot interface",
            ),
            air_architecture_criterion(),
            quick_disconnect_criterion(),
            criterion_from_flag(
                "part_count",
                "Part Count",
                tool_eoat_record,
                tool_eoat,
                "number_of_parts_compatible",
                "the part-count requirement",
            ),
            sensor_requirement_criterion(),
        ]
        # Desktop Fit Check does not call a setup compatible merely because the
        # three relationship links pass.  Its detailed checklist is part of the
        # decision: an unmet criterion rejects the setup and missing evidence
        # keeps it in the review state.
        if any(item.result == "INCOMPATIBLE" for item in requirements):
            overall = "INCOMPATIBLE"
        elif any(pair.result == "UNKNOWN" for pair in pairs) or any(
            item.result == "NEEDS_REVIEW" for item in requirements
        ):
            overall = "NEEDS_REVIEW"
        else:
            overall = "COMPATIBLE"

        def entity(value, entity_type: str, *, plant_code: str | None = None) -> FitCheckEntity:
            if entity_type == "machine":
                secondary = " · ".join(part for part in (plant_code, value.machine_type, value.model) if part) or None
                return FitCheckEntity(
                    entity_type="machine",
                    identifier=value.machine_number,
                    label=value.machine_name or f"Machine {value.machine_number}",
                    secondary=secondary,
                )
            if entity_type == "tool":
                secondary = (
                    " · ".join(
                        part
                        for part in (
                            value.tool_type,
                            f"{value.cavity_count} cavities" if value.cavity_count else None,
                        )
                        if part
                    )
                    or None
                )
                return FitCheckEntity(
                    entity_type="tool",
                    identifier=value.business_identifier,
                    label=value.display_name or value.tool_number or value.business_identifier,
                    secondary=secondary,
                )
            secondary = (
                " · ".join(
                    part
                    for part in (
                        value.revision and f"Revision {value.revision}",
                        f"{value.number_of_parts_picked} parts" if value.number_of_parts_picked else None,
                    )
                    if part
                )
                or None
            )
            return FitCheckEntity(
                entity_type="eoat",
                identifier=value.business_identifier,
                label=value.display_name or value.business_identifier,
                secondary=secondary,
            )

        plant_code = self.session.scalar(select(db.Plant.plant_code).where(db.Plant.id == machine.plant_id))
        selected_entities = [
            entity(machine, "machine", plant_code=plant_code),
            entity(tool, "tool"),
            entity(eoat, "eoat"),
        ]
        machine_status = aliased(db.CompatibilityStatus)
        tool_status = aliased(db.CompatibilityStatus)
        alternative_eoat_rows = self.session.scalars(
            select(db.EOAT)
            .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.eoat_id == db.EOAT.id)
            .join(db.EOATToolCompatibility, db.EOATToolCompatibility.eoat_id == db.EOAT.id)
            .join(machine_status, machine_status.id == db.EOATMachineCompatibility.compatibility_status_id)
            .join(tool_status, tool_status.id == db.EOATToolCompatibility.compatibility_status_id)
            .where(
                db.EOATMachineCompatibility.machine_id == machine.id,
                db.EOATToolCompatibility.tool_id == tool.id,
                db.EOAT.is_active.is_(True),
                db.EOATMachineCompatibility.is_active.is_(True),
                db.EOATToolCompatibility.is_active.is_(True),
                db.EOATMachineCompatibility.effective_from <= now,
                db.EOATToolCompatibility.effective_from <= now,
                or_(
                    db.EOATMachineCompatibility.effective_to.is_(None), db.EOATMachineCompatibility.effective_to >= now
                ),
                or_(db.EOATToolCompatibility.effective_to.is_(None), db.EOATToolCompatibility.effective_to >= now),
                machine_status.code.in_(SELECTABLE_COMPATIBILITY_STATUS_CODES),
                tool_status.code.in_(SELECTABLE_COMPATIBILITY_STATUS_CODES),
            )
            .distinct()
            .order_by(db.EOAT.business_identifier)
            .limit(12)
        ).all()

        machine_tool_status = aliased(db.CompatibilityStatus)
        machine_eoat_status = aliased(db.CompatibilityStatus)
        alternative_machine_rows = self.session.execute(
            select(db.Machine, db.Plant.plant_code)
            .join(db.Plant, db.Plant.id == db.Machine.plant_id)
            .join(db.ToolMachineCompatibility, db.ToolMachineCompatibility.machine_id == db.Machine.id)
            .join(
                db.EOATMachineCompatibility,
                db.EOATMachineCompatibility.machine_id == db.Machine.id,
            )
            .join(machine_tool_status, machine_tool_status.id == db.ToolMachineCompatibility.compatibility_status_id)
            .join(machine_eoat_status, machine_eoat_status.id == db.EOATMachineCompatibility.compatibility_status_id)
            .where(
                db.ToolMachineCompatibility.tool_id == tool.id,
                db.EOATMachineCompatibility.eoat_id == eoat.id,
                db.Machine.id != machine.id,
                db.Machine.is_active.is_(True),
                db.Plant.is_active.is_(True),
                db.ToolMachineCompatibility.is_active.is_(True),
                db.EOATMachineCompatibility.is_active.is_(True),
                db.ToolMachineCompatibility.effective_from <= now,
                db.EOATMachineCompatibility.effective_from <= now,
                or_(
                    db.ToolMachineCompatibility.effective_to.is_(None), db.ToolMachineCompatibility.effective_to >= now
                ),
                or_(
                    db.EOATMachineCompatibility.effective_to.is_(None), db.EOATMachineCompatibility.effective_to >= now
                ),
                machine_tool_status.code.in_(SELECTABLE_COMPATIBILITY_STATUS_CODES),
                machine_eoat_status.code.in_(SELECTABLE_COMPATIBILITY_STATUS_CODES),
            )
            .distinct()
            .order_by(db.Plant.plant_code, db.Machine.machine_number)
            .limit(12)
        ).all()
        alternative_eoats = [
            FitCheckAlternative(
                entity=entity(value, "eoat"),
                status="best",
                status_label="Compatible alternative",
                reason=(
                    f"Recorded as compatible with Machine {machine.machine_number} and Tool {tool.business_identifier}."
                ),
            )
            for value in alternative_eoat_rows
            if value.id != eoat.id
        ]
        alternative_machines = [
            FitCheckAlternative(
                entity=entity(value, "machine", plant_code=alternative_plant),
                status="available",
                status_label="Compatible alternative",
                reason=(
                    f"Recorded as compatible with Tool {tool.business_identifier} and EOAT {eoat.business_identifier}."
                ),
            )
            for value, alternative_plant in alternative_machine_rows
        ]
        structured_warnings = [
            FitCheckWarning(
                severity="critical" if pair.result == "INCOMPATIBLE" else "warning",
                title=f"{pair.pair.replace('_', ' ').title()} {('is incompatible' if pair.result == 'INCOMPATIBLE' else 'needs review')}",
                message=pair.reason,
            )
            for pair in pairs
            if pair.result != "COMPATIBLE"
        ]
        structured_warnings.extend(
            FitCheckWarning(
                severity="critical" if item.result == "INCOMPATIBLE" else "warning",
                title=item.label,
                message=item.reason,
            )
            for item in requirements
            if item.result in {"INCOMPATIBLE", "NEEDS_REVIEW"}
            and item.code not in {"machine_compatibility", "eoat_compatibility"}
        )
        confidence = (
            "high"
            if overall == "COMPATIBLE" and all(item.result in {"COMPATIBLE", "NOT_APPLICABLE"} for item in requirements)
            else "low"
            if overall == "INCOMPATIBLE"
            else "medium"
        )
        decision_summary = {
            "COMPATIBLE": "All three active relationship records support this setup.",
            "INCOMPATIBLE": "At least one active relationship or requirement rejects this setup.",
            "NEEDS_REVIEW": "No relationship is rejected, but one or more required evidence records need review.",
        }[overall]
        detail_sections = [
            FitCheckDetailSection(
                title="Decision summary",
                entries=[
                    f"Result: {overall.replace('_', ' ').title()}",
                    decision_summary,
                    f"Confidence: {confidence.title()}",
                ],
            ),
            FitCheckDetailSection(
                title="Selected setup",
                entries=[
                    f"Machine: {selected_entities[0].identifier} — {selected_entities[0].label}",
                    f"Tool: {selected_entities[1].identifier} — {selected_entities[1].label}",
                    f"EOAT: {selected_entities[2].identifier} — {selected_entities[2].label}",
                ],
            ),
            FitCheckDetailSection(
                title="Relationship evidence",
                entries=[
                    f"Machine ↔ Tool: {machine_tool.result.title()} — {machine_tool.reason}",
                    f"Machine ↔ EOAT: {machine_eoat.result.title()} — {machine_eoat.reason}",
                    f"Tool ↔ EOAT: {tool_eoat.result.title()} — {tool_eoat.reason}",
                ],
            ),
            FitCheckDetailSection(
                title="Requirements",
                entries=[
                    f"{item.label}: {item.result.replace('_', ' ').title()} — {item.reason}" for item in requirements
                ],
            ),
            FitCheckDetailSection(
                title="Warnings",
                entries=[f"{item.title}: {item.message}" for item in structured_warnings]
                or ["No setup warnings are recorded for this evaluation."],
            ),
            FitCheckDetailSection(
                title="Alternative machines",
                entries=[
                    f"{item.entity.identifier}: {item.status_label} — {item.reason}" for item in alternative_machines
                ]
                or ["No compatible alternative machines are recorded."],
            ),
            FitCheckDetailSection(
                title="Alternative EOATs",
                entries=[f"{item.entity.identifier}: {item.status_label} — {item.reason}" for item in alternative_eoats]
                or ["No compatible alternative EOATs are recorded."],
            ),
            FitCheckDetailSection(
                title="Air / Pneumatic Requirements",
                entries=[
                    next(item.reason for item in requirements if item.code == "air_architecture"),
                    next(item.reason for item in requirements if item.code == "quick_disconnect"),
                ],
            ),
            FitCheckDetailSection(
                title="Sensor Requirements",
                entries=[next(item.reason for item in requirements if item.code == "sensor_requirements")],
            ),
            FitCheckDetailSection(
                title="Audit & documentation",
                entries=[
                    "Compatibility evidence uses only active, effective-dated authoritative relationship records.",
                    "Open the selected record pages for governed document metadata; browser Fit Check never exposes storage paths.",
                ],
            ),
            FitCheckDetailSection(
                title="Setup packet",
                entries=[
                    "A setup packet can be created from this compatible evaluation."
                    if overall == "COMPATIBLE"
                    else "A setup packet is unavailable until the relationship and requirement results are compatible."
                ],
            ),
        ]
        return FitCheckResult(
            overall_result=overall,
            machine_tool_result=machine_tool,
            machine_eoat_result=machine_eoat,
            tool_eoat_result=tool_eoat,
            reasons=[pair.reason for pair in pairs],
            warnings=[warning.message for warning in structured_warnings],
            unknown_relationships=unknowns,
            alternative_compatible_eoats=[item.entity.identifier for item in alternative_eoats],
            decision_summary=decision_summary,
            confidence=confidence,
            selected_entities=selected_entities,
            requirements=requirements,
            structured_warnings=structured_warnings,
            alternative_machines=alternative_machines,
            alternative_eoats=alternative_eoats,
            recommended_eoat=alternative_eoats[0] if alternative_eoats else None,
            detail_sections=detail_sections,
            setup_packet_available=overall == "COMPATIBLE",
        )

    def persist_fit_check(
        self, request: FitCheckRequest, result: FitCheckResult, actor: ActorContext
    ) -> FitCheckResult:
        if result.overall_result == "INVALID_INPUT":
            return result
        machine, tool, eoat = self._selected_entities(request)
        if not all((machine, tool, eoat)):
            return result
        codes = {
            "COMPATIBLE": "compatible",
            "INCOMPATIBLE": "incompatible",
            "NEEDS_REVIEW": "needs_review",
            "UNKNOWN": "unknown",
            "NOT_EVALUATED": "unknown",
        }
        ids = {
            code: self.session.scalar(select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code == lookup))
            for code, lookup in codes.items()
        }
        record = db.FitCheckRecord(
            machine_id=machine.id,
            tool_id=tool.id,
            eoat_id=eoat.id,
            overall_status_id=ids[result.overall_result],
            machine_tool_status_id=ids[result.machine_tool_result.result],
            machine_eoat_status_id=ids[result.machine_eoat_result.result],
            tool_eoat_status_id=ids[result.tool_eoat_result.result],
            evaluation_engine_version=result.evaluation_engine_version,
            performed_by_user_id=actor.user_id,
            application_instance_id=actor.application_instance_id,
            request_id=actor.request_id,
            result_summary=result.overall_result,
            result_details_json=result.model_dump(mode="json"),
        )
        self.session.add(record)
        self.session.flush()
        return result.model_copy(update={"stored": True})

    def sync_status(self) -> SyncStatus:
        revision = self.schema_revision()
        cursor = self.session.scalar(select(func.max(db.ChangeFeed.change_id))) or 0
        return SyncStatus(
            api_version=API_VERSION,
            schema_revision=revision,
            server_revision=SERVER_REVISION,
            current_cursor=cursor,
            compatible=revision == EXPECTED_SCHEMA_REVISION,
        )

    def data_status(self) -> DataStatus:
        """Expose safe browser freshness metadata without opening a write path."""
        now = datetime.now(timezone.utc)
        revision = self.session.scalar(select(func.max(db.ChangeFeed.change_id))) or 0
        last_modified = self.session.scalar(select(func.max(db.ChangeFeed.changed_at))) or now
        return DataStatus(
            data_last_modified_at=last_modified,
            data_revision=revision,
            server_time=now,
        )

    def changes(self, after_cursor: int, limit: int = 1000) -> SyncChangeBatch:
        rows = self.session.scalars(
            select(db.ChangeFeed)
            .where(db.ChangeFeed.change_id > after_cursor)
            .order_by(db.ChangeFeed.change_id)
            .limit(limit)
        ).all()
        changes = [
            SyncChange(
                cursor=row.change_id,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                operation=row.operation,
                row_version=row.entity_row_version,
                changed_at=row.changed_at,
            )
            for row in rows
        ]
        return SyncChangeBatch(
            after_cursor=after_cursor, next_cursor=changes[-1].cursor if changes else after_cursor, changes=changes
        )

    def snapshot(self) -> SyncSnapshot:
        eoat_profiles, machine_profiles, tool_profiles = self.repository.snapshot_profiles()
        status = self.sync_status()
        return SyncSnapshot(
            server_revision=SERVER_REVISION,
            schema_revision=status.schema_revision,
            cursor=status.current_cursor,
            generated_at=datetime.now(timezone.utc),
            lookups=self.repository.lookups(),
            eoats=eoat_profiles,
            machines=machine_profiles,
            tools=tool_profiles,
            documents=self.repository.documents(),
            photos=self.repository.documents(photos_only=True),
            eoat_history=self.repository.eoat_history_snapshot(),
        )
