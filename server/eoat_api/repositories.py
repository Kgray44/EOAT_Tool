from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import ceil
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from .contracts import (
    DocumentMetadata,
    EOATProfile,
    EOATSummary,
    HistoryEvent,
    LookupValue,
    MachineProfile,
    MachineSummary,
    PaginatedHistory,
    PaginationMetadata,
    PhotoMetadata,
    RelationshipSummary,
    SearchResult,
    ToolProfile,
    ToolSummary,
)
from .database import models as db
from .errors import APIError
from .location_resolver import resolve_eoat_locations

LOOKUP_MODELS = {
    "eoat_types": db.EOATType,
    "connection_types": db.ConnectionType,
    "cleanroom_classifications": db.CleanroomClassification,
    "asset_statuses": db.AssetStatus,
    "compatibility_statuses": db.CompatibilityStatus,
    "compatibility_sources": db.CompatibilitySource,
    "document_types": db.DocumentType,
    "history_event_types": db.HistoryEventType,
}


def _optional_text(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


class AtlasRepository:
    def __init__(self, session: Session):
        self.session = session

    def lookups(self, lookup_type: str | None = None) -> dict[str, list[LookupValue]]:
        models = {lookup_type: LOOKUP_MODELS[lookup_type]} if lookup_type else LOOKUP_MODELS
        return {
            name: [
                LookupValue(
                    code=row.code, display_name=row.display_name, description=row.description, sort_order=row.sort_order
                )
                for row in self.session.scalars(
                    select(model).where(model.is_active.is_(True)).order_by(model.sort_order, model.display_name)
                )
            ]
            for name, model in models.items()
        }

    def list_eoats(
        self,
        *,
        search: str = "",
        page: int = 1,
        page_size: int = 50,
        active: bool | None = True,
        eoat_type: str | None = None,
        area: str | None = None,
        cleanroom: str | None = None,
        sort: str = "business_identifier",
    ) -> tuple[list[EOATSummary], PaginationMetadata]:
        type_l = aliased(db.EOATType)
        conn_l = aliased(db.ConnectionType)
        clean_l = aliased(db.CleanroomClassification)
        status_l = aliased(db.AssetStatus)
        stmt = (
            select(db.EOAT, type_l.display_name, conn_l.display_name, clean_l.display_name, status_l.display_name)
            .outerjoin(type_l, db.EOAT.eoat_type_id == type_l.id)
            .outerjoin(conn_l, db.EOAT.connection_type_id == conn_l.id)
            .outerjoin(clean_l, db.EOAT.cleanroom_classification_id == clean_l.id)
            .outerjoin(status_l, db.EOAT.status_id == status_l.id)
        )
        if active is not None:
            stmt = stmt.where(db.EOAT.is_active.is_(active))
        if search:
            stmt = stmt.where(
                or_(
                    db.EOAT.business_identifier.contains(search),
                    db.EOAT.legacy_identifier.contains(search),
                    db.EOAT.display_name.contains(search),
                    db.EOAT.description.contains(search),
                )
            )
        if eoat_type:
            stmt = stmt.where(type_l.code == eoat_type)
        if cleanroom:
            stmt = stmt.where(clean_l.code == cleanroom)
        if area:
            stmt = (
                stmt.join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.eoat_id == db.EOAT.id)
                .join(db.Machine, db.Machine.id == db.EOATMachineCompatibility.machine_id)
                .join(db.Area, db.Area.id == db.Machine.area_id)
                .where(or_(db.Area.area_code == area, db.Area.area_name == area))
                .distinct()
            )
        total = self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        order = db.EOAT.updated_at.desc() if sort == "updated_desc" else db.EOAT.business_identifier
        rows = self.session.execute(stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)).all()
        locations = resolve_eoat_locations(self.session, [row[0].id for row in rows])
        items = [
            EOATSummary(
                business_identifier=e.business_identifier,
                physical_uuid=e.physical_uuid,
                design_family_identifier=e.design_family_identifier,
                legacy_identifier=e.legacy_identifier,
                display_name=e.display_name,
                eoat_type=t,
                connection_type=c,
                cleanroom_classification=cl,
                status=s,
                number_of_parts_picked=e.number_of_parts_picked,
                is_active=e.is_active,
                row_version=e.row_version,
                current_location=locations[e.id].display,
                current_location_detail=locations[e.id],
            )
            for e, t, c, cl, s in rows
        ]
        return items, PaginationMetadata(
            page=page, page_size=page_size, total=total, pages=ceil(total / page_size) if total else 0
        )

    def eoat(self, identifier: str) -> EOATProfile | None:
        items, _ = self.list_eoats(search=identifier, active=None, page_size=100)
        summary = next(
            (
                item
                for item in items
                if item.business_identifier.casefold() == identifier.casefold()
                or (item.legacy_identifier or "").casefold() == identifier.casefold()
            ),
            None,
        )
        if summary is None:
            return None
        entity = self.session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == summary.business_identifier))
        return EOATProfile(
            **summary.model_dump(),
            description=entity.description,
            revision=entity.revision,
            number_of_vacuum_cups=entity.number_of_vacuum_cups,
            number_of_grippers=entity.number_of_grippers,
            vacuum_present=entity.vacuum_present,
            sensors_present=entity.sensors_present,
            part_present_sensor_present=entity.part_present_sensor_present,
            vacuum_confirmation_sensor_present=entity.vacuum_confirmation_sensor_present,
            quick_disconnect_present=entity.quick_disconnect_present,
            cup_material=entity.cup_material,
            notes=entity.notes,
            relationships=self.eoat_relationships(summary.business_identifier),
            audit_evidence=[
                audit.details_json or {}
                for audit in self.session.scalars(
                    select(db.AuditRecord)
                    .where(db.AuditRecord.eoat_id == entity.id)
                    .order_by(db.AuditRecord.source_row_number)
                )
            ],
        )

    def eoat_relationships(self, identifier: str) -> list[RelationshipSummary]:
        eoat = self.session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == identifier))
        results: list[RelationshipSummary] = []
        if eoat is None:
            return results
        for machine, status in self.session.execute(
            select(db.Machine, db.CompatibilityStatus.display_name)
            .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.machine_id == db.Machine.id)
            .join(
                db.CompatibilityStatus, db.CompatibilityStatus.id == db.EOATMachineCompatibility.compatibility_status_id
            )
            .where(db.EOATMachineCompatibility.eoat_id == eoat.id, db.EOATMachineCompatibility.is_active.is_(True))
        ):
            results.append(
                RelationshipSummary(
                    relationship_type="machine",
                    identifier=machine.machine_number,
                    display_name=machine.machine_name,
                    status=status,
                )
            )
        for tool, status in self.session.execute(
            select(db.Tool, db.CompatibilityStatus.display_name)
            .join(db.EOATToolCompatibility, db.EOATToolCompatibility.tool_id == db.Tool.id)
            .join(db.CompatibilityStatus, db.CompatibilityStatus.id == db.EOATToolCompatibility.compatibility_status_id)
            .where(db.EOATToolCompatibility.eoat_id == eoat.id, db.EOATToolCompatibility.is_active.is_(True))
        ):
            results.append(
                RelationshipSummary(
                    relationship_type="tool",
                    identifier=tool.business_identifier,
                    display_name=tool.display_name,
                    status=status,
                )
            )
        return results

    def list_machines(
        self, *, search: str = "", page: int = 1, page_size: int = 50, active: bool | None = True
    ) -> tuple[list[MachineSummary], PaginationMetadata]:
        area_l = aliased(db.Area)
        clean_l = aliased(db.CleanroomClassification)
        status_l = aliased(db.AssetStatus)
        stmt = (
            select(db.Machine, db.Plant.plant_code, area_l.area_name, clean_l.display_name, status_l.display_name)
            .join(db.Plant, db.Machine.plant_id == db.Plant.id)
            .outerjoin(area_l, db.Machine.area_id == area_l.id)
            .outerjoin(clean_l, db.Machine.cleanroom_classification_id == clean_l.id)
            .outerjoin(status_l, db.Machine.status_id == status_l.id)
        )
        if active is not None:
            stmt = stmt.where(db.Machine.is_active.is_(active))
        if search:
            stmt = stmt.where(
                or_(
                    db.Machine.machine_number.contains(search),
                    db.Machine.machine_name.contains(search),
                    db.Machine.model.contains(search),
                )
            )
        total = self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        rows = self.session.execute(
            stmt.order_by(cast(db.Machine.machine_number, String)).offset((page - 1) * page_size).limit(page_size)
        ).all()
        all_eoat_ids = list(self.session.scalars(select(db.EOAT.id).where(db.EOAT.is_active.is_(True))))
        installed_by_machine: dict[str, list[str]] = defaultdict(list)
        if all_eoat_ids:
            identifiers = dict(
                self.session.execute(
                    select(db.EOAT.id, db.EOAT.business_identifier).where(db.EOAT.id.in_(all_eoat_ids))
                ).all()
            )
            for eoat_id, location in resolve_eoat_locations(self.session, all_eoat_ids).items():
                if location.state == "INSTALLED" and location.machine_number:
                    installed_by_machine[location.machine_number].append(identifiers[eoat_id])
        return [
            MachineSummary(
                plant_code=plant_code,
                machine_number=m.machine_number,
                machine_name=m.machine_name,
                area=a,
                manufacturer=m.manufacturer,
                model=m.model,
                cleanroom_classification=c,
                status=s,
                is_active=m.is_active,
                row_version=m.row_version,
                current_eoat=(", ".join(sorted(installed_by_machine.get(m.machine_number, []))) or "NONE_OBSERVED"),
            )
            for m, plant_code, a, c, s in rows
        ], PaginationMetadata(
            page=page, page_size=page_size, total=total, pages=ceil(total / page_size) if total else 0
        )

    def machine(self, number: str, *, plant_code: str | None = None) -> MachineProfile | None:
        statement = select(db.Machine).where(db.Machine.machine_number == number)
        if plant_code:
            statement = statement.join(db.Plant, db.Plant.id == db.Machine.plant_id).where(
                db.Plant.plant_code == plant_code
            )
        entities = list(self.session.scalars(statement.order_by(db.Machine.id)).all())
        if len(entities) > 1:
            raise APIError(409, "AMBIGUOUS_MACHINE", "plant_code is required for this machine number.")
        if not entities:
            return None
        entity = entities[0]
        summary = next(
            (
                item
                for item in self.list_machines(search=number, active=None, page_size=100)[0]
                if item.machine_number == number and item.plant_code == self.session.scalar(
                    select(db.Plant.plant_code).where(db.Plant.id == entity.plant_id)
                )
            ),
            None,
        )
        if summary is None:
            return None
        relationships = [
            RelationshipSummary(
                relationship_type="eoat", identifier=e.business_identifier, display_name=e.display_name, status=s
            )
            for e, s in self.session.execute(
                select(db.EOAT, db.CompatibilityStatus.display_name)
                .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.eoat_id == db.EOAT.id)
                .join(
                    db.CompatibilityStatus,
                    db.CompatibilityStatus.id == db.EOATMachineCompatibility.compatibility_status_id,
                )
                .where(
                    db.EOATMachineCompatibility.machine_id == entity.id, db.EOATMachineCompatibility.is_active.is_(True)
                )
            )
        ]
        relationships += [
            RelationshipSummary(
                relationship_type="tool", identifier=t.business_identifier, display_name=t.display_name, status=s
            )
            for t, s in self.session.execute(
                select(db.Tool, db.CompatibilityStatus.display_name)
                .join(db.ToolMachineCompatibility, db.ToolMachineCompatibility.tool_id == db.Tool.id)
                .join(
                    db.CompatibilityStatus,
                    db.CompatibilityStatus.id == db.ToolMachineCompatibility.compatibility_status_id,
                )
                .where(
                    db.ToolMachineCompatibility.machine_id == entity.id, db.ToolMachineCompatibility.is_active.is_(True)
                )
            )
        ]
        robots = [
            RelationshipSummary(
                relationship_type="robot", identifier=r.robot_number, display_name=r.robot_name, status="ASSIGNED"
            )
            for r in self.session.scalars(
                select(db.Robot)
                .join(db.MachineRobotAssignment, db.MachineRobotAssignment.robot_id == db.Robot.id)
                .where(
                    db.MachineRobotAssignment.machine_id == entity.id, db.MachineRobotAssignment.removed_at.is_(None)
                )
            )
        ]
        return MachineProfile(
            **summary.model_dump(),
            controller_type=entity.controller_type,
            press_capacity_tons=float(entity.press_capacity_tons) if entity.press_capacity_tons else None,
            notes=entity.notes,
            relationships=relationships,
            robots=robots,
        )

    def list_tools(
        self, *, search: str = "", page: int = 1, page_size: int = 50, active: bool | None = True
    ) -> tuple[list[ToolSummary], PaginationMetadata]:
        status_l = aliased(db.AssetStatus)
        stmt = select(db.Tool, status_l.display_name).outerjoin(status_l, db.Tool.status_id == status_l.id)
        if active is not None:
            stmt = stmt.where(db.Tool.is_active.is_(active))
        if search:
            stmt = stmt.where(
                or_(
                    db.Tool.business_identifier.contains(search),
                    db.Tool.tool_number.contains(search),
                    db.Tool.mold_number.contains(search),
                    db.Tool.display_name.contains(search),
                )
            )
        total = self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        rows = self.session.execute(
            stmt.order_by(db.Tool.business_identifier).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return [
            ToolSummary(
                business_identifier=t.business_identifier,
                tool_number=t.tool_number,
                mold_number=t.mold_number,
                display_name=t.display_name,
                status=s,
                is_active=t.is_active,
                row_version=t.row_version,
            )
            for t, s in rows
        ], PaginationMetadata(
            page=page, page_size=page_size, total=total, pages=ceil(total / page_size) if total else 0
        )

    def tool(self, identifier: str) -> ToolProfile | None:
        entity = self.session.scalar(
            select(db.Tool).where(or_(db.Tool.business_identifier == identifier, db.Tool.tool_number == identifier))
        )
        if entity is None:
            return None
        summary = next(
            (
                item
                for item in self.list_tools(search=identifier, active=None, page_size=100)[0]
                if item.business_identifier == entity.business_identifier
            ),
            None,
        )
        relationships = [
            RelationshipSummary(
                relationship_type="eoat", identifier=e.business_identifier, display_name=e.display_name, status=s
            )
            for e, s in self.session.execute(
                select(db.EOAT, db.CompatibilityStatus.display_name)
                .join(db.EOATToolCompatibility, db.EOATToolCompatibility.eoat_id == db.EOAT.id)
                .join(
                    db.CompatibilityStatus,
                    db.CompatibilityStatus.id == db.EOATToolCompatibility.compatibility_status_id,
                )
                .where(db.EOATToolCompatibility.tool_id == entity.id, db.EOATToolCompatibility.is_active.is_(True))
            )
        ]
        relationships += [
            RelationshipSummary(
                relationship_type="machine", identifier=m.machine_number, display_name=m.machine_name, status=s
            )
            for m, s in self.session.execute(
                select(db.Machine, db.CompatibilityStatus.display_name)
                .join(db.ToolMachineCompatibility, db.ToolMachineCompatibility.machine_id == db.Machine.id)
                .join(
                    db.CompatibilityStatus,
                    db.CompatibilityStatus.id == db.ToolMachineCompatibility.compatibility_status_id,
                )
                .where(
                    db.ToolMachineCompatibility.tool_id == entity.id, db.ToolMachineCompatibility.is_active.is_(True)
                )
            )
        ]
        return ToolProfile(
            **summary.model_dump(),
            description=entity.description,
            tool_type=entity.tool_type,
            customer=entity.customer,
            program_name=entity.program_name,
            notes=entity.notes,
            relationships=relationships,
            audit_evidence=[
                audit.details_json or {}
                for audit in self.session.scalars(
                    select(db.AuditRecord)
                    .where(db.AuditRecord.tool_id == entity.id)
                    .order_by(db.AuditRecord.source_row_number)
                )
            ],
        )

    def history_page(
        self,
        entity_type: str,
        entity_id: int,
        *,
        eoat_identifier: str | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_order: str = "desc",
        event_category: str | None = None,
        event_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str = "",
    ) -> PaginatedHistory:
        stmt = (
            select(db.EntityHistoryEvent, db.HistoryEventType, db.User, db.ApplicationInstance)
            .join(db.HistoryEventType, db.HistoryEventType.id == db.EntityHistoryEvent.event_type_id)
            .outerjoin(db.User, db.User.id == db.EntityHistoryEvent.actor_user_id)
            .outerjoin(db.ApplicationInstance, db.ApplicationInstance.id == db.EntityHistoryEvent.application_instance_id)
            .where(db.EntityHistoryEvent.entity_type == entity_type, db.EntityHistoryEvent.entity_id == entity_id)
        )
        if event_category:
            stmt = stmt.where(func.upper(db.EntityHistoryEvent.event_category) == event_category.upper())
        if event_type:
            requested_type = event_type.upper()
            persisted_type = {
                "EOAT_CREATED": "RECORD_CREATED",
                "EOAT_UPDATED": "RECORD_EDITED",
                "EOAT_ARCHIVED": "RECORD_ARCHIVED",
                "EOAT_RESTORED": "RECORD_RESTORED",
                "EOAT_INSTALLED_ON_MACHINE": "INSTALLED",
                "EOAT_MOVED_TO_MACHINE": "INSTALLED",
                "EOAT_REMOVED_FROM_MACHINE": "REMOVED",
                "EOAT_MOVED_TO_STORAGE": "MOVED_TO_STORAGE",
                "EOAT_LOCATION_MARKED_UNKNOWN": "LOCATION_UNKNOWN",
            }.get(requested_type, requested_type)
            stmt = stmt.where(func.upper(db.HistoryEventType.code) == persisted_type)
            if requested_type == "EOAT_MOVED_TO_MACHINE":
                stmt = stmt.where(
                    cast(db.EntityHistoryEvent.metadata_json, String).ilike('%"movement_kind": "moved_to_machine"%')
                )
            elif requested_type == "EOAT_INSTALLED_ON_MACHINE":
                stmt = stmt.where(
                    or_(
                        db.EntityHistoryEvent.metadata_json.is_(None),
                        cast(db.EntityHistoryEvent.metadata_json, String).not_ilike('%"movement_kind": "moved_to_machine"%'),
                    )
                )
        if date_from:
            stmt = stmt.where(db.EntityHistoryEvent.occurred_at >= date_from)
        if date_to:
            stmt = stmt.where(db.EntityHistoryEvent.occurred_at <= date_to)
        query = search.strip()
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(
                    db.EntityHistoryEvent.summary.ilike(pattern),
                    db.EntityHistoryEvent.description.ilike(pattern),
                    db.EntityHistoryEvent.reason.ilike(pattern),
                    db.EntityHistoryEvent.notes.ilike(pattern),
                    db.HistoryEventType.display_name.ilike(pattern),
                    db.User.display_name.ilike(pattern),
                    cast(db.EntityHistoryEvent.metadata_json, String).ilike(pattern),
                )
            )
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(self.session.scalar(count_stmt) or 0)
        direction = db.EntityHistoryEvent.occurred_at.asc() if sort_order.casefold() == "asc" else db.EntityHistoryEvent.occurred_at.desc()
        tie_direction = (
            db.EntityHistoryEvent.event_uuid.asc()
            if sort_order.casefold() == "asc"
            else db.EntityHistoryEvent.event_uuid.desc()
        )
        rows = self.session.execute(
            stmt.order_by(direction, tie_direction).offset((page - 1) * page_size).limit(page_size)
        ).all()
        items = [
            self._history_event(event, kind, actor, instance, eoat_identifier=eoat_identifier)
            for event, kind, actor, instance in rows
        ]
        return PaginatedHistory(
            items=items,
            pagination=PaginationMetadata(
                page=page,
                page_size=page_size,
                total=total,
                pages=ceil(total / page_size) if total else 0,
            ),
        )

    def history(self, entity_type: str, entity_id: int) -> list[HistoryEvent]:
        return self.history_page(entity_type, entity_id, page_size=200).items

    def eoat_history_snapshot(self) -> list[HistoryEvent]:
        rows = self.session.execute(
            select(db.EntityHistoryEvent, db.HistoryEventType, db.User, db.ApplicationInstance, db.EOAT)
            .join(db.HistoryEventType, db.HistoryEventType.id == db.EntityHistoryEvent.event_type_id)
            .join(db.EOAT, db.EOAT.id == db.EntityHistoryEvent.entity_id)
            .outerjoin(db.User, db.User.id == db.EntityHistoryEvent.actor_user_id)
            .outerjoin(db.ApplicationInstance, db.ApplicationInstance.id == db.EntityHistoryEvent.application_instance_id)
            .where(db.EntityHistoryEvent.entity_type == "eoat")
            .order_by(
                db.EOAT.business_identifier,
                db.EntityHistoryEvent.occurred_at.desc(),
                db.EntityHistoryEvent.event_uuid.desc(),
            )
        ).all()
        return [
            self._history_event(event, kind, actor, instance, eoat_identifier=eoat.business_identifier)
            for event, kind, actor, instance, eoat in rows
        ]

    @staticmethod
    def _history_event(
        event: db.EntityHistoryEvent,
        kind: db.HistoryEventType,
        actor: db.User | None,
        instance: db.ApplicationInstance | None,
        *,
        eoat_identifier: str | None,
    ) -> HistoryEvent:
        metadata: dict[str, Any] = dict(event.metadata_json or {})
        application_instance = None
        if instance is not None:
            application_instance = instance.installation_name or instance.computer_name or instance.instance_uuid
        event_type = kind.code.upper()
        if event.entity_type == "eoat":
            event_type = {
                "RECORD_CREATED": "EOAT_CREATED",
                "RECORD_EDITED": "EOAT_UPDATED",
                "RECORD_ARCHIVED": "EOAT_ARCHIVED",
                "RECORD_RESTORED": "EOAT_RESTORED",
                "INSTALLED": "EOAT_INSTALLED_ON_MACHINE",
                "REMOVED": "EOAT_REMOVED_FROM_MACHINE",
                "MOVED_TO_STORAGE": "EOAT_MOVED_TO_STORAGE",
                "LOCATION_UNKNOWN": "EOAT_LOCATION_MARKED_UNKNOWN",
            }.get(event_type, event_type)
            if event_type == "EOAT_INSTALLED_ON_MACHINE" and metadata.get("movement_kind") == "moved_to_machine":
                event_type = "EOAT_MOVED_TO_MACHINE"
        return HistoryEvent(
            event_id=event.event_uuid,
            eoat_identifier=eoat_identifier,
            event_type=event_type,
            event_category=event.event_category,
            occurred_at=event.occurred_at,
            summary=event.summary,
            description=event.description or event.details,
            actor=actor.display_name if actor is not None else None,
            application_instance=application_instance,
            source_record_type=event.source_table,
            source_record_id=str(event.source_record_id) if event.source_record_id is not None else None,
            related_machine=_optional_text(metadata.get("related_machine") or metadata.get("machine_number")),
            related_tool=_optional_text(metadata.get("related_tool") or metadata.get("tool_number")),
            related_robot=_optional_text(metadata.get("related_robot") or metadata.get("robot_number")),
            related_storage_location=_optional_text(metadata.get("related_storage_location") or metadata.get("storage_location")),
            related_document=_optional_text(metadata.get("related_document") or metadata.get("document_uuid")),
            related_photo=_optional_text(metadata.get("related_photo") or metadata.get("photo_id")),
            reason=event.reason,
            notes=event.notes,
            previous_values=event.previous_values_json,
            new_values=event.new_values_json,
            metadata=metadata or None,
        )

    def documents(
        self, entity_type: str | None = None, entity_id: int | None = None, *, photos_only: bool = False
    ) -> list[DocumentMetadata | PhotoMetadata]:
        stmt = select(db.Document, db.Photo).outerjoin(db.Photo, db.Photo.document_id == db.Document.id)
        if entity_type is not None and entity_id is not None:
            stmt = stmt.join(db.DocumentLink, db.DocumentLink.document_id == db.Document.id).where(
                db.DocumentLink.entity_type == entity_type, db.DocumentLink.entity_id == entity_id
            )
        if photos_only:
            stmt = stmt.where(db.Photo.id.is_not(None))
        document_rows = self.session.execute(stmt.order_by(db.Document.file_name)).all()
        document_ids = [document.id for document, _photo in document_rows]
        links_by_document: dict[int, list[db.DocumentLink]] = defaultdict(list)
        if document_ids:
            for link in self.session.scalars(
                select(db.DocumentLink).where(db.DocumentLink.document_id.in_(document_ids))
            ):
                links_by_document[link.document_id].append(link)
        identifiers: dict[tuple[str, int], str] = {}
        for entity_type, model, column in (
            ("eoat", db.EOAT, db.EOAT.business_identifier),
            ("machine", db.Machine, db.Machine.machine_number),
            ("tool", db.Tool, db.Tool.business_identifier),
        ):
            ids = {
                link.entity_id
                for values in links_by_document.values()
                for link in values
                if link.entity_type == entity_type
            }
            if ids:
                identifiers.update(
                    {
                        (entity_type, row_id): value
                        for row_id, value in self.session.execute(select(model.id, column).where(model.id.in_(ids)))
                    }
                )
        results = []
        for document, photo in document_rows:
            links = [
                RelationshipSummary(
                    relationship_type=link.entity_type,
                    identifier=identifiers.get((link.entity_type, link.entity_id), str(link.entity_id)),
                    status="LINKED",
                    reason=link.relationship_type,
                )
                for link in links_by_document.get(document.id, [])
            ]
            common = dict(
                document_uuid=document.document_uuid,
                document_number=document.document_number,
                title=document.title,
                description=document.description,
                file_name=document.file_name,
                storage_path=document.storage_path,
                mime_type=document.mime_type,
                related_entities=links,
            )
            results.append(
                PhotoMetadata(
                    **common,
                    photo_view_type=photo.photo_view_type,
                    captured_at=photo.captured_at,
                    caption=photo.caption,
                    is_profile_photo=photo.is_profile_photo,
                )
                if photo
                else DocumentMetadata(**common)
            )
        return results

    def snapshot_profiles(self) -> tuple[list[EOATProfile], list[MachineProfile], list[ToolProfile]]:
        """Build all profile payloads with a bounded query count."""
        eoat_summaries, _ = self.list_eoats(active=None, page_size=10_000)
        machine_summaries, _ = self.list_machines(active=None, page_size=10_000)
        tool_summaries, _ = self.list_tools(active=None, page_size=10_000)
        eoats = {row.id: row for row in self.session.scalars(select(db.EOAT))}
        machines = {row.id: row for row in self.session.scalars(select(db.Machine))}
        tools = {row.id: row for row in self.session.scalars(select(db.Tool))}
        eoat_by_identifier = {row.business_identifier: row for row in eoats.values()}
        machine_by_identifier = {row.machine_number: row for row in machines.values()}
        tool_by_identifier = {row.business_identifier: row for row in tools.values()}

        eoat_relationships: dict[int, list[RelationshipSummary]] = defaultdict(list)
        machine_relationships: dict[int, list[RelationshipSummary]] = defaultdict(list)
        tool_relationships: dict[int, list[RelationshipSummary]] = defaultdict(list)
        for relation, status in self.session.execute(
            select(db.EOATMachineCompatibility, db.CompatibilityStatus.display_name)
            .join(
                db.CompatibilityStatus, db.CompatibilityStatus.id == db.EOATMachineCompatibility.compatibility_status_id
            )
            .where(db.EOATMachineCompatibility.is_active.is_(True))
        ):
            eoat, machine = eoats.get(relation.eoat_id), machines.get(relation.machine_id)
            if eoat and machine:
                eoat_relationships[eoat.id].append(
                    RelationshipSummary(
                        relationship_type="machine",
                        identifier=machine.machine_number,
                        display_name=machine.machine_name,
                        status=status,
                    )
                )
                machine_relationships[machine.id].append(
                    RelationshipSummary(
                        relationship_type="eoat",
                        identifier=eoat.business_identifier,
                        display_name=eoat.display_name,
                        status=status,
                    )
                )
        for relation, status in self.session.execute(
            select(db.EOATToolCompatibility, db.CompatibilityStatus.display_name)
            .join(db.CompatibilityStatus, db.CompatibilityStatus.id == db.EOATToolCompatibility.compatibility_status_id)
            .where(db.EOATToolCompatibility.is_active.is_(True))
        ):
            eoat, tool = eoats.get(relation.eoat_id), tools.get(relation.tool_id)
            if eoat and tool:
                eoat_relationships[eoat.id].append(
                    RelationshipSummary(
                        relationship_type="tool",
                        identifier=tool.business_identifier,
                        display_name=tool.display_name,
                        status=status,
                    )
                )
                tool_relationships[tool.id].append(
                    RelationshipSummary(
                        relationship_type="eoat",
                        identifier=eoat.business_identifier,
                        display_name=eoat.display_name,
                        status=status,
                    )
                )
        for relation, status in self.session.execute(
            select(db.ToolMachineCompatibility, db.CompatibilityStatus.display_name)
            .join(
                db.CompatibilityStatus, db.CompatibilityStatus.id == db.ToolMachineCompatibility.compatibility_status_id
            )
            .where(db.ToolMachineCompatibility.is_active.is_(True))
        ):
            tool, machine = tools.get(relation.tool_id), machines.get(relation.machine_id)
            if tool and machine:
                tool_relationships[tool.id].append(
                    RelationshipSummary(
                        relationship_type="machine",
                        identifier=machine.machine_number,
                        display_name=machine.machine_name,
                        status=status,
                    )
                )
                machine_relationships[machine.id].append(
                    RelationshipSummary(
                        relationship_type="tool",
                        identifier=tool.business_identifier,
                        display_name=tool.display_name,
                        status=status,
                    )
                )
        machine_robots: dict[int, list[RelationshipSummary]] = defaultdict(list)
        for assignment, robot in self.session.execute(
            select(db.MachineRobotAssignment, db.Robot)
            .join(db.Robot, db.Robot.id == db.MachineRobotAssignment.robot_id)
            .where(db.MachineRobotAssignment.removed_at.is_(None))
        ):
            machine_robots[assignment.machine_id].append(
                RelationshipSummary(
                    relationship_type="robot",
                    identifier=robot.robot_number,
                    display_name=robot.robot_name,
                    status="ASSIGNED",
                )
            )
        audit_by_eoat: dict[int, list[dict]] = defaultdict(list)
        audit_by_machine: dict[int, list[dict]] = defaultdict(list)
        audit_by_tool: dict[int, list[dict]] = defaultdict(list)
        for audit in self.session.scalars(select(db.AuditRecord).order_by(db.AuditRecord.source_row_number)):
            details = audit.details_json or {}
            if audit.eoat_id:
                audit_by_eoat[audit.eoat_id].append(details)
            if audit.machine_id:
                audit_by_machine[audit.machine_id].append(details)
            if audit.tool_id:
                audit_by_tool[audit.tool_id].append(details)

        eoat_profiles = []
        for summary in eoat_summaries:
            entity = eoat_by_identifier[summary.business_identifier]
            eoat_profiles.append(
                EOATProfile(
                    **summary.model_dump(),
                    description=entity.description,
                    revision=entity.revision,
                    number_of_vacuum_cups=entity.number_of_vacuum_cups,
                    number_of_grippers=entity.number_of_grippers,
                    vacuum_present=entity.vacuum_present,
                    sensors_present=entity.sensors_present,
                    part_present_sensor_present=entity.part_present_sensor_present,
                    vacuum_confirmation_sensor_present=entity.vacuum_confirmation_sensor_present,
                    quick_disconnect_present=entity.quick_disconnect_present,
                    cup_material=entity.cup_material,
                    notes=entity.notes,
                    relationships=eoat_relationships[entity.id],
                    audit_evidence=audit_by_eoat[entity.id],
                )
            )
        machine_profiles = []
        for summary in machine_summaries:
            entity = machine_by_identifier[summary.machine_number]
            machine_profiles.append(
                MachineProfile(
                    **summary.model_dump(),
                    controller_type=entity.controller_type,
                    press_capacity_tons=float(entity.press_capacity_tons) if entity.press_capacity_tons else None,
                    notes=entity.notes,
                    relationships=machine_relationships[entity.id],
                    robots=machine_robots[entity.id],
                    audit_evidence=audit_by_machine[entity.id],
                )
            )
        tool_profiles = []
        for summary in tool_summaries:
            entity = tool_by_identifier[summary.business_identifier]
            tool_profiles.append(
                ToolProfile(
                    **summary.model_dump(),
                    description=entity.description,
                    tool_type=entity.tool_type,
                    customer=entity.customer,
                    program_name=entity.program_name,
                    notes=entity.notes,
                    relationships=tool_relationships[entity.id],
                    audit_evidence=audit_by_tool[entity.id],
                )
            )
        return eoat_profiles, machine_profiles, tool_profiles

    def search(self, query: str, limit: int = 50) -> list[SearchResult]:
        results: list[SearchResult] = []
        eoats, _ = self.list_eoats(search=query, active=None, page_size=limit)
        results.extend(
            SearchResult(
                category="eoat",
                identifier=e.business_identifier,
                title=e.display_name or e.business_identifier,
                subtitle=e.eoat_type or "EOAT",
                matched_field="identifier/name/description",
            )
            for e in eoats
        )
        machines, _ = self.list_machines(search=query, active=None, page_size=limit)
        results.extend(
            SearchResult(
                category="machine",
                identifier=m.machine_number,
                title=m.machine_name or m.machine_number,
                subtitle=m.area or "Machine",
                matched_field="number/name/model",
            )
            for m in machines
        )
        tools, _ = self.list_tools(search=query, active=None, page_size=limit)
        results.extend(
            SearchResult(
                category="tool",
                identifier=t.business_identifier,
                title=t.display_name or t.business_identifier,
                subtitle=t.mold_number or "Tool",
                matched_field="identifier/tool/mold/name",
            )
            for t in tools
        )
        return results[:limit]
