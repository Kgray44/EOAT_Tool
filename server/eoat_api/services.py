from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from core.versioning import get_version_info
from core.versioning.compatibility import EXPECTED_API_VERSION, EXPECTED_SCHEMA_REVISION

from .compatibility import COMPATIBLE_STATUS_CODES, classify_status
from .contracts import (
    DataStatusResponse,
    FitCheckRequest,
    FitCheckResult,
    PairCompatibility,
    SyncChange,
    SyncChangeBatch,
    SyncSnapshot,
    SyncStatus,
)
from .data_state import mark_data_changed
from .database import models as db
from .errors import APIError
from .repositories import AtlasRepository
from .security import ActorContext

API_VERSION = EXPECTED_API_VERSION
SERVER_REVISION = get_version_info().build_id


class AtlasService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = AtlasRepository(session)

    def schema_revision(self) -> str | None:
        return self.session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))

    def database_server_version(self) -> str:
        return str(self.session.scalar(text("SELECT VERSION()")) or "")

    def fit_check(self, request: FitCheckRequest, *, evaluated_at: datetime | None = None) -> FitCheckResult:
        evaluated_at = evaluated_at or datetime.now(timezone.utc)

        def asset_is_available(value) -> bool:
            if value is None or not value.is_active:
                return False
            if value.status_id is None:
                return True
            status_code = self.session.scalar(
                select(db.AssetStatus.code).where(db.AssetStatus.id == value.status_id)
            )
            return (status_code or "").strip().casefold() != "archived"

        def invalid_input(reason: str, unknown_relationship: str) -> FitCheckResult:
            unknown = PairCompatibility(pair="unresolved_input", result="NOT_EVALUATED", reason=reason)
            return FitCheckResult(
                overall_result="INVALID_INPUT",
                machine_tool_result=unknown,
                machine_eoat_result=unknown,
                tool_eoat_result=unknown,
                reasons=[reason],
                warnings=[],
                unknown_relationships=[unknown_relationship],
                alternative_compatible_eoats=[],
            )

        machine_query = select(db.Machine).where(db.Machine.machine_number == request.machine_number)
        if request.plant_code:
            machine_query = machine_query.join(db.Plant, db.Plant.id == db.Machine.plant_id).where(
                db.Plant.plant_code == request.plant_code,
                db.Plant.is_active.is_(True),
            )
        machine_candidates = list(self.session.scalars(machine_query.order_by(db.Machine.id)).all())
        machines = [value for value in machine_candidates if asset_is_available(value)]
        if len(machines) > 1:
            return invalid_input(
                "Machine number is ambiguous across plants; plant_code is required.",
                "machine",
            )
        machine = machines[0] if machines else None
        tool_candidates = list(
            self.session.scalars(
            select(db.Tool).where(
                (db.Tool.business_identifier == request.tool_number) | (db.Tool.tool_number == request.tool_number)
                ).order_by(db.Tool.id)
            ).all()
        )
        if len(tool_candidates) > 1:
            return invalid_input("Tool identifier is ambiguous; use its unique business identifier.", "tool")
        tool = tool_candidates[0] if tool_candidates else None
        eoat = self.repository.resolve_eoat_identity(request.eoat_identifier)
        unavailable = []
        if machine_candidates and machine is None:
            unavailable.append("machine")
        unavailable.extend(
            name for name, value in (("tool", tool), ("eoat", eoat)) if value is not None and not asset_is_available(value)
        )
        if unavailable:
            return invalid_input(
                f"Archived or inactive input: {', '.join(unavailable)}",
                unavailable[0],
            )

        missing = [name for name, value in (("machine", machine), ("tool", tool), ("eoat", eoat)) if value is None]
        if missing:
            return invalid_input(f"Unknown input: {', '.join(missing)}", missing[0])

        def pair_result(model: type, *criteria) -> PairCompatibility:
            record = self.session.scalar(
                select(model)
                .where(
                    *criteria,
                    model.is_active.is_(True),
                    model.effective_from <= evaluated_at,
                    (model.effective_to.is_(None) | (model.effective_to >= evaluated_at)),
                )
                .order_by(model.effective_from.desc(), model.id.desc())
            )
            pair_name = model.__tablename__
            if record is None:
                return PairCompatibility(
                    pair=pair_name,
                    result="UNKNOWN",
                    reason="No verified relationship is recorded; absence is not incompatibility.",
                )
            status = self.session.scalar(
                select(db.CompatibilityStatus.code).where(db.CompatibilityStatus.id == record.compatibility_status_id)
            )
            source = None
            if record.verification_source_id:
                source = self.session.scalar(
                    select(db.CompatibilitySource.code).where(db.CompatibilitySource.id == record.verification_source_id)
                )
            result = classify_status(status)
            default_reasons = {
                "COMPATIBLE": "Relationship has an explicitly compatible status and is currently effective.",
                "INCOMPATIBLE": "Relationship is explicitly incompatible.",
                "NEEDS_REVIEW": "Relationship explicitly requires review.",
                "UNKNOWN": "Relationship status is missing or unrecognized; compatibility was not inferred.",
            }
            return PairCompatibility(
                pair=pair_name,
                result=result,
                reason=record.reason or default_reasons[result],
                status_code=status or "unknown",
                verification_source=source,
                is_active=record.is_active,
                effective_from=record.effective_from,
                effective_to=record.effective_to,
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
        elif any(pair.result == "NEEDS_REVIEW" for pair in pairs):
            overall = "NEEDS_REVIEW"
        else:
            overall = "NEEDS_REVIEW"
        unknowns = [pair.pair for pair in pairs if pair.result in {"UNKNOWN", "NEEDS_REVIEW"}]
        alternative_ids: list[str] = []
        if machine_tool.result == "COMPATIBLE":
            alternative_ids = list(
                self.session.scalars(
                    select(db.EOAT.business_identifier)
                    .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.eoat_id == db.EOAT.id)
                    .join(db.EOATToolCompatibility, db.EOATToolCompatibility.eoat_id == db.EOAT.id)
                    .where(
                        db.EOATMachineCompatibility.machine_id == machine.id,
                        db.EOATToolCompatibility.tool_id == tool.id,
                        db.EOAT.is_active.is_(True),
                        or_(
                            db.EOAT.status_id.is_(None),
                            db.EOAT.status_id.not_in(
                                select(db.AssetStatus.id).where(db.AssetStatus.code == "archived")
                            ),
                        ),
                        db.EOATMachineCompatibility.is_active.is_(True),
                        db.EOATToolCompatibility.is_active.is_(True),
                        db.EOATMachineCompatibility.effective_from <= evaluated_at,
                        (db.EOATMachineCompatibility.effective_to.is_(None) | (db.EOATMachineCompatibility.effective_to >= evaluated_at)),
                        db.EOATToolCompatibility.effective_from <= evaluated_at,
                        (db.EOATToolCompatibility.effective_to.is_(None) | (db.EOATToolCompatibility.effective_to >= evaluated_at)),
                        db.EOATMachineCompatibility.compatibility_status_id.in_(
                            select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code.in_(COMPATIBLE_STATUS_CODES))
                        ),
                        db.EOATToolCompatibility.compatibility_status_id.in_(
                            select(db.CompatibilityStatus.id).where(db.CompatibilityStatus.code.in_(COMPATIBLE_STATUS_CODES))
                        ),
                    )
                    .distinct()
                    .order_by(db.EOAT.business_identifier)
                ).all()
            )
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
        machine_query = select(db.Machine).where(db.Machine.machine_number == request.machine_number)
        if request.plant_code:
            machine_query = machine_query.join(db.Plant, db.Plant.id == db.Machine.plant_id).where(
                db.Plant.plant_code == request.plant_code
            )
        machine = self.session.scalar(machine_query)
        tool = self.session.scalar(
            select(db.Tool).where(
                or_(db.Tool.business_identifier == request.tool_number, db.Tool.tool_number == request.tool_number)
            )
        )
        eoat = self.repository.resolve_eoat_identity(request.eoat_identifier)
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
        # Persisted Fit Check history is visible operational data, unlike an
        # in-memory evaluation request, so it participates in data freshness.
        mark_data_changed(self.session, actor)
        return result.model_copy(update={"stored": True})

    def data_status(self) -> DataStatusResponse:
        state = self.session.get(db.DataState, 1)
        if state is None:
            raise APIError(
                503,
                "DATA_STATE_UNAVAILABLE",
                "Authoritative data freshness metadata is not initialized.",
                retryable=True,
            )
        return DataStatusResponse(
            status="available",
            data_revision=int(state.current_revision),
            data_last_modified_at=state.data_last_modified_at,
            last_import_at=state.last_import_at,
            last_import_source=state.last_import_source,
            server_time=datetime.now(timezone.utc),
            source="mysql",
            environment=__import__("os").environ.get("EOAT_API_ENVIRONMENT", "development"),
        )

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
            data_status=self.data_status(),
            lookups=self.repository.lookups(),
            eoats=eoat_profiles,
            machines=machine_profiles,
            tools=tool_profiles,
            documents=self.repository.documents(),
            photos=self.repository.documents(photos_only=True),
            eoat_history=self.repository.eoat_history_snapshot(),
        )
