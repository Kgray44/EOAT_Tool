from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .contracts import (
    FitCheckRequest,
    FitCheckResult,
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
EXPECTED_SCHEMA_REVISION = "20260811_0007"
SERVER_REVISION = "mysql-cutover-rehearsal-rc1"


class AtlasService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = AtlasRepository(session)

    def schema_revision(self) -> str | None:
        return self.session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))

    def fit_check(self, request: FitCheckRequest) -> FitCheckResult:
        machine = self.session.scalar(select(db.Machine).where(db.Machine.machine_number == request.machine_number))
        tool = self.session.scalar(
            select(db.Tool).where(
                (db.Tool.business_identifier == request.tool_number) | (db.Tool.tool_number == request.tool_number)
            )
        )
        eoat = self.session.scalar(
            select(db.EOAT).where(
                (db.EOAT.business_identifier == request.eoat_identifier)
                | (db.EOAT.legacy_identifier == request.eoat_identifier)
            )
        )
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

        def pair_result(model: type, *criteria) -> PairCompatibility:
            record = self.session.scalar(select(model).where(*criteria, model.is_active.is_(True)))
            pair_name = model.__tablename__
            if record is None:
                return PairCompatibility(
                    pair=pair_name,
                    result="UNKNOWN",
                    reason="No verified relationship is recorded; absence is not incompatibility.",
                )
            status = (
                self.session.scalar(
                    select(db.CompatibilityStatus.code).where(
                        db.CompatibilityStatus.id == record.compatibility_status_id
                    )
                )
                or "unknown"
            )
            if status in {"incompatible", "failed", "not_compatible"}:
                return PairCompatibility(
                    pair=pair_name,
                    result="INCOMPATIBLE",
                    reason=record.reason or "Relationship is explicitly incompatible.",
                )
            return PairCompatibility(
                pair=pair_name,
                result="COMPATIBLE",
                reason=record.reason or "Relationship is recorded in the authoritative data.",
            )

        machine_tool = pair_result(
            db.ToolMachineCompatibility,
            db.ToolMachineCompatibility.machine_id == machine.id,
            db.ToolMachineCompatibility.tool_id == tool.id,
        )
        machine_eoat = pair_result(
            db.EOATMachineCompatibility,
            db.EOATMachineCompatibility.machine_id == machine.id,
            db.EOATMachineCompatibility.eoat_id == eoat.id,
        )
        tool_eoat = pair_result(
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
        alternative_ids = self.session.scalars(
            select(db.EOAT.business_identifier)
            .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.eoat_id == db.EOAT.id)
            .join(db.EOATToolCompatibility, db.EOATToolCompatibility.eoat_id == db.EOAT.id)
            .where(
                db.EOATMachineCompatibility.machine_id == machine.id,
                db.EOATToolCompatibility.tool_id == tool.id,
                db.EOAT.is_active.is_(True),
            )
            .order_by(db.EOAT.business_identifier)
        ).all()
        return FitCheckResult(
            overall_result=overall,
            machine_tool_result=machine_tool,
            machine_eoat_result=machine_eoat,
            tool_eoat_result=tool_eoat,
            reasons=[pair.reason for pair in pairs],
            warnings=["One or more relationships are unknown; verify before setup."] if unknowns else [],
            unknown_relationships=unknowns,
            alternative_compatible_eoats=[value for value in alternative_ids if value != eoat.business_identifier],
        )

    def persist_fit_check(
        self, request: FitCheckRequest, result: FitCheckResult, actor: ActorContext
    ) -> FitCheckResult:
        if result.overall_result == "INVALID_INPUT":
            return result
        machine = self.session.scalar(select(db.Machine).where(db.Machine.machine_number == request.machine_number))
        tool = self.session.scalar(
            select(db.Tool).where(
                or_(db.Tool.business_identifier == request.tool_number, db.Tool.tool_number == request.tool_number)
            )
        )
        eoat = self.session.scalar(
            select(db.EOAT).where(
                or_(
                    db.EOAT.business_identifier == request.eoat_identifier,
                    db.EOAT.legacy_identifier == request.eoat_identifier,
                )
            )
        )
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
