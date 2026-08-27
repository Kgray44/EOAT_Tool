from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from .audit_profiles import latest_physical_audit
from .contracts import (
    CurrentEOATLocation,
    DocumentMetadata,
    EffectiveValueSource,
    EOATProfile,
    EOATSummary,
    HistoryEvent,
    LookupValue,
    MachineProfile,
    MachineSummary,
    PaginatedHistory,
    PaginationMetadata,
    PhotoMetadata,
    PhysicalAuditObservation,
    RelationshipSummary,
    SearchResult,
    ToolProfile,
    ToolSummary,
)
from .database import models as db
from .web_content import content_is_available

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

_NATURAL_IDENTIFIER_PARTS = re.compile(r"(\d+)")


def natural_identifier_key(value: object | None) -> tuple[tuple[int, int | str], ...]:
    """Return a deterministic, case-insensitive key for human identifiers.

    Catalog identifiers are business values rather than database sequence
    numbers. Keeping this key at the repository boundary means the API sorts
    before it applies pagination, rather than leaving individual browser views
    to produce incompatible client-side orderings.
    """

    text_value = str(value or "")
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in _NATURAL_IDENTIFIER_PARTS.split(text_value)
        if part
    )


def _page_rows(rows: list[Any], *, page: int, page_size: int) -> tuple[list[Any], PaginationMetadata]:
    total = len(rows)
    start = (page - 1) * page_size
    return rows[start : start + page_size], PaginationMetadata(
        page=page,
        page_size=page_size,
        total=total,
        pages=ceil(total / page_size) if total else 0,
    )


def _optional_text(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value or None


@dataclass(frozen=True)
class _EOATProfilePhoto:
    """The one server-selected photo used wherever an EOAT needs a lead image."""

    document_uuid: str
    storage_path: str
    is_profile_photo: bool
    is_primary_link: bool
    sort_order: int
    file_name: str
    view_type: str | None

    @property
    def selection_key(self) -> tuple[bool, bool, int, str, str]:
        # Every candidate is already a FRONT view. A profile flag can only
        # break ties within that truthful set.
        return (
            not self.is_profile_photo,
            not self.is_primary_link,
            self.sort_order,
            self.file_name.casefold(),
            self.document_uuid,
        )


def _normalized_photo_view(value: object | None) -> str | None:
    normalized = " ".join(str(value or "").strip().upper().replace("_", " ").split())
    return "FRONT" if normalized in {"FRONT", "FRONT VIEW"} else None


def _physical_audit_contract(records: list[db.AuditRecord]) -> PhysicalAuditObservation | None:
    audit = latest_physical_audit(records)
    if audit is None:
        return None
    return PhysicalAuditObservation(
        audit_identifier=audit.audit_identifier,
        observed_at=audit.audit_date if isinstance(audit.audit_date, datetime) else None,
        observed_machine=audit.observed_machine,
        observed_tool=audit.observed_tool,
        verified=audit.verified,
        configuration=audit.configuration,
    )


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

    def _selected_eoat_profile_photos(self, eoat_ids: list[int]) -> dict[int, _EOATProfilePhoto]:
        """Select one EOAT photo with the same rule for summaries and galleries.

        A photo explicitly marked as the profile photo wins. Existing imported
        records without that flag remain useful through a stable fallback:
        primary link, then configured photo order, then filename/UUID.
        """
        if not eoat_ids:
            return {}
        rows = self.session.execute(
            select(
                db.DocumentLink.entity_id,
                db.Document.document_uuid,
                db.Document.storage_path,
                db.Document.file_name,
                db.Photo.is_profile_photo,
                db.DocumentLink.is_primary,
                db.Photo.sort_order,
                db.Photo.photo_view_type,
            )
            .join(db.Document, db.Document.id == db.DocumentLink.document_id)
            .join(db.Photo, db.Photo.document_id == db.Document.id)
            .where(
                db.DocumentLink.entity_type == "eoat",
                db.DocumentLink.entity_id.in_(eoat_ids),
                db.Document.is_active.is_(True),
            )
        ).all()
        selected: dict[int, _EOATProfilePhoto] = {}
        for entity_id, document_uuid, storage_path, file_name, is_profile, is_primary, sort_order, view_type in rows:
            if _normalized_photo_view(view_type) != "FRONT":
                # A missing front image is a documentation gap.  Do not let a
                # profile flag, source ordering, or a convenient side/back
                # shot masquerade as the EOAT's representative image.
                continue
            candidate = _EOATProfilePhoto(
                document_uuid=document_uuid,
                storage_path=storage_path,
                is_profile_photo=bool(is_profile),
                is_primary_link=bool(is_primary),
                sort_order=int(sort_order or 0),
                file_name=file_name,
                view_type=view_type,
            )
            current = selected.get(entity_id)
            if current is None or candidate.selection_key < current.selection_key:
                selected[entity_id] = candidate
        return selected

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
        rows = list(self.session.execute(stmt).all())
        if sort == "updated_desc":
            rows.sort(
                key=lambda row: (
                    row[0].updated_at,
                    natural_identifier_key(row[0].business_identifier),
                ),
                reverse=True,
            )
        elif sort == "status":
            rows.sort(
                key=lambda row: (
                    str(row[4] or "").casefold(),
                    natural_identifier_key(row[0].business_identifier),
                )
            )
        elif sort in {"business_identifier_desc", "machine_number_desc"}:
            rows.sort(
                key=lambda row: natural_identifier_key(row[0].business_identifier),
                reverse=True,
            )
        else:
            rows.sort(key=lambda row: natural_identifier_key(row[0].business_identifier))
        rows, pagination = _page_rows(rows, page=page, page_size=page_size)
        selected_photos = self._selected_eoat_profile_photos([entity.id for entity, *_values in rows])
        items = []
        for e, t, c, cl, s in rows:
            selected_photo = selected_photos.get(e.id)
            items.append(
                EOATSummary(
                    business_identifier=e.business_identifier,
                    legacy_identifier=e.legacy_identifier,
                    display_name=e.display_name,
                    eoat_type=t,
                    connection_type=c,
                    cleanroom_classification=cl,
                    status=s,
                    number_of_parts_picked=e.number_of_parts_picked,
                    is_active=e.is_active,
                    row_version=e.row_version,
                    photo_document_uuid=selected_photo.document_uuid if selected_photo else None,
                    photo_available_through_web=(
                        content_is_available(
                            selected_photo.storage_path, document_uuid=selected_photo.document_uuid, photo=True
                        )
                        if selected_photo
                        else False
                    ),
                )
            )
        return items, pagination

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
        audits = list(self.session.scalars(
            select(db.AuditRecord)
            .where(db.AuditRecord.eoat_id == entity.id)
            .order_by(db.AuditRecord.audit_date, db.AuditRecord.source_row_number)
        ))
        physical_audit = _physical_audit_contract(audits)
        observed = physical_audit.configuration if physical_audit and physical_audit.verified else {}

        def effective(name: str, canonical: Any) -> Any:
            return canonical if canonical is not None else observed.get(name)

        source_pairs = {
            "description": (entity.description, "description"),
            "eoat_type": (summary.eoat_type, "eoat_type"),
            "connection_type": (summary.connection_type, "connection_type"),
            "cleanroom_classification": (summary.cleanroom_classification, "cleanroom_classification"),
            "number_of_parts_picked": (entity.number_of_parts_picked, "parts_picked"),
            "number_of_vacuum_cups": (entity.number_of_vacuum_cups, "vacuum_cup_count"),
            "number_of_grippers": (entity.number_of_grippers, "gripper_count"),
            "sensors_present": (entity.sensors_present, "sensors_present"),
            "quick_disconnect_present": (entity.quick_disconnect_present, "quick_disconnect_present"),
            "cup_material": (entity.cup_material, "cup_material"),
        }
        sources = {
            name: EffectiveValueSource(
                source="CANONICAL" if canonical is not None else "VERIFIED_PHYSICAL_AUDIT",
                audit_identifier=None if canonical is not None else physical_audit.audit_identifier,
                observed_at=None if canonical is not None else physical_audit.observed_at,
            )
            for name, (canonical, observed_name) in source_pairs.items()
            if canonical is not None or observed.get(observed_name) is not None
        }
        summary_payload = summary.model_dump()
        current_location = self.current_eoat_location(summary.business_identifier)
        summary_payload.update(
            eoat_type=effective("eoat_type", summary.eoat_type),
            connection_type=effective("connection_type", summary.connection_type),
            cleanroom_classification=effective("cleanroom_classification", summary.cleanroom_classification),
            number_of_parts_picked=effective("parts_picked", entity.number_of_parts_picked),
            current_location=current_location.state if current_location else summary.current_location,
            current_location_detail=current_location,
        )
        return EOATProfile(
            **summary_payload,
            description=effective("description", entity.description),
            revision=entity.revision,
            number_of_vacuum_cups=effective("vacuum_cup_count", entity.number_of_vacuum_cups),
            number_of_grippers=effective("gripper_count", entity.number_of_grippers),
            vacuum_present=entity.vacuum_present if entity.vacuum_present is not None else (
                True if observed.get("vacuum_cup_count") or observed.get("vacuum_generator") or observed.get("vacuum_circuits") else None
            ),
            sensors_present=effective("sensors_present", entity.sensors_present),
            part_present_sensor_present=effective("part_present_sensor_present", entity.part_present_sensor_present),
            vacuum_confirmation_sensor_present=effective("vacuum_confirmation_sensor_present", entity.vacuum_confirmation_sensor_present),
            quick_disconnect_present=effective("quick_disconnect_present", entity.quick_disconnect_present),
            cup_material=effective("cup_material", entity.cup_material),
            frame_material=entity.frame_material,
            weight_kg=float(entity.weight_kg) if entity.weight_kg is not None else None,
            maximum_payload_kg=float(entity.maximum_payload_kg) if entity.maximum_payload_kg is not None else None,
            drawing_number=entity.drawing_number,
            manufacturer=entity.manufacturer,
            date_built=entity.date_built.isoformat() if entity.date_built else None,
            date_commissioned=entity.date_commissioned.isoformat() if entity.date_commissioned else None,
            notes=entity.notes,
            relationships=self.eoat_relationships(summary.business_identifier),
            audit_evidence=[audit.details_json or {} for audit in audits],
            latest_physical_audit=physical_audit,
            effective_value_sources=sources,
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

    def current_eoat_location(self, identifier: str):
        """Resolve present lifecycle state first, then uncontested verified audit evidence.

        Compatibility links are intentionally absent from this resolver: they
        describe fitness, not physical whereabouts.
        """
        entity = self.session.scalar(select(db.EOAT).where(db.EOAT.business_identifier == identifier))
        if entity is None:
            return None
        installed = self.session.execute(
            select(db.EOATInstallation, db.Machine.machine_number)
            .join(db.Machine, db.Machine.id == db.EOATInstallation.machine_id)
            .where(db.EOATInstallation.eoat_id == entity.id, db.EOATInstallation.removed_at.is_(None))
            .order_by(db.EOATInstallation.installed_at.desc())
            .limit(1)
        ).first()
        if installed is not None:
            installation, machine_number = installed
            return CurrentEOATLocation(
                state="INSTALLED", source="LIFECYCLE_EVENT", machine_number=machine_number,
                observed_at=installation.installed_at, confidence="CONFIRMED",
                evidence="Active governed EOAT installation record",
            )
        stored = self.session.execute(
            select(db.EOATStorageAssignment, db.StorageLocation.location_code)
            .join(db.StorageLocation, db.StorageLocation.id == db.EOATStorageAssignment.storage_location_id)
            .where(db.EOATStorageAssignment.eoat_id == entity.id, db.EOATStorageAssignment.removed_from_storage_at.is_(None))
            .order_by(db.EOATStorageAssignment.stored_at.desc())
            .limit(1)
        ).first()
        if stored is not None:
            assignment, location_code = stored
            return CurrentEOATLocation(
                state="STORED", source="LIFECYCLE_EVENT", storage_location=location_code,
                observed_at=assignment.stored_at, confidence="CONFIRMED",
                evidence="Active governed EOAT storage assignment",
            )
        audits = list(self.session.scalars(select(db.AuditRecord).where(db.AuditRecord.eoat_id == entity.id)))
        verified = [
            audit for audit in audits
            if (projection := latest_physical_audit([audit])) is not None
            and projection.verified is True
            and projection.observed_machine
        ]
        if not verified:
            return CurrentEOATLocation(
                state="UNKNOWN", source="NONE", confidence="UNKNOWN",
                evidence="No active lifecycle location or verified physical location observation is recorded.",
            )
        newest_date = max(
            (audit.audit_date.date() if audit.audit_date else datetime.min.date())
            for audit in verified
        )
        newest = [
            audit for audit in verified
            if (audit.audit_date.date() if audit.audit_date else datetime.min.date()) == newest_date
        ]
        machines = {
            latest_physical_audit([audit]).observed_machine
            for audit in newest
            if latest_physical_audit([audit]) is not None
        }
        if len(machines) != 1:
            return CurrentEOATLocation(
                state="CONFLICTING", source="OBSERVATION", confidence="UNKNOWN",
                resolution_status="REVIEW_REQUIRED",
                evidence="Conflicting equally recent verified physical-location evidence requires review.",
            )
        audit = newest[0]
        projection = latest_physical_audit([audit])
        return CurrentEOATLocation(
            state="INSTALLED", source="OBSERVATION", machine_number=projection.observed_machine,
            observed_at=audit.audit_date, confidence="VERIFIED",
            evidence=f"Physically verified in audit {projection.audit_identifier}",
        )

    def list_machines(
        self,
        *,
        search: str = "",
        page: int = 1,
        page_size: int = 50,
        active: bool | None = True,
        sort: str = "natural_identifier",
    ) -> tuple[list[MachineSummary], PaginationMetadata]:
        area_l = aliased(db.Area)
        clean_l = aliased(db.CleanroomClassification)
        status_l = aliased(db.AssetStatus)
        stmt = (
            select(db.Machine, db.Plant.plant_code, area_l.area_name, clean_l.display_name, status_l.display_name)
            .outerjoin(db.Plant, db.Plant.id == db.Machine.plant_id)
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
        rows = list(self.session.execute(stmt).all())
        if sort == "updated_desc":
            rows.sort(
                key=lambda row: (
                    row[0].updated_at,
                    natural_identifier_key(row[0].machine_number),
                    str(row[1] or "").casefold(),
                ),
                reverse=True,
            )
        elif sort == "status":
            rows.sort(
                key=lambda row: (
                    str(row[4] or "").casefold(),
                    natural_identifier_key(row[0].machine_number),
                    str(row[1] or "").casefold(),
                )
            )
        elif sort in {"machine_number_desc", "business_identifier_desc"}:
            rows.sort(
                key=lambda row: (
                    natural_identifier_key(row[0].machine_number),
                    str(row[1] or "").casefold(),
                ),
                reverse=True,
            )
        else:
            rows.sort(
                key=lambda row: (
                    natural_identifier_key(row[0].machine_number),
                    str(row[1] or "").casefold(),
                )
            )
        rows, pagination = _page_rows(rows, page=page, page_size=page_size)
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
            )
            for m, plant_code, a, c, s in rows
        ], pagination

    def machine(self, number: str, *, plant_code: str | None = None) -> MachineProfile | None:
        query = select(db.Machine).where(db.Machine.machine_number == number)
        if plant_code:
            query = query.join(db.Plant).where(db.Plant.plant_code == plant_code)
        entity = self.session.scalar(query)
        if entity is None:
            return None
        summary = next(
            (
                item
                for item in self.list_machines(search=number, active=None, page_size=100)[0]
                if item.machine_number == number and (plant_code is None or item.plant_code == plant_code)
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
            serial_number=entity.serial_number,
            machine_type=entity.machine_type,
            installation_date=entity.installation_date.isoformat() if entity.installation_date else None,
            notes=entity.notes,
            relationships=relationships,
            robots=robots,
            audit_evidence=[
                audit.details_json or {}
                for audit in self.session.scalars(
                    select(db.AuditRecord)
                    .where(db.AuditRecord.machine_id == entity.id)
                    .order_by(db.AuditRecord.source_row_number)
                )
            ],
        )

    def list_tools(
        self,
        *,
        search: str = "",
        page: int = 1,
        page_size: int = 50,
        active: bool | None = True,
        sort: str = "natural_identifier",
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
        rows = list(self.session.execute(stmt).all())
        if sort == "updated_desc":
            rows.sort(
                key=lambda row: (
                    row[0].updated_at,
                    natural_identifier_key(row[0].business_identifier),
                ),
                reverse=True,
            )
        elif sort == "status":
            rows.sort(
                key=lambda row: (
                    str(row[1] or "").casefold(),
                    natural_identifier_key(row[0].business_identifier),
                )
            )
        elif sort == "mold":
            rows.sort(
                key=lambda row: (
                    natural_identifier_key(row[0].mold_number),
                    natural_identifier_key(row[0].business_identifier),
                )
            )
        elif sort in {"business_identifier_desc", "machine_number_desc"}:
            rows.sort(
                key=lambda row: natural_identifier_key(row[0].business_identifier),
                reverse=True,
            )
        else:
            rows.sort(key=lambda row: natural_identifier_key(row[0].business_identifier))
        rows, pagination = _page_rows(rows, page=page, page_size=page_size)
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
        ], pagination

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
            cavity_count=entity.cavity_count,
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
        # Event UUIDs are identities, not chronology.  MySQL can preserve
        # multiple history writes at the same DATETIME precision, so use the
        # immutable auto-increment sequence to make tied timestamps reflect
        # actual persisted event order deterministically.
        tie_direction = (
            db.EntityHistoryEvent.id.asc()
            if sort_order.casefold() == "asc"
            else db.EntityHistoryEvent.id.desc()
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
                db.EntityHistoryEvent.id.desc(),
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
        for linked_entity_type, model, column in (
            ("eoat", db.EOAT, db.EOAT.business_identifier),
            ("machine", db.Machine, db.Machine.machine_number),
            ("tool", db.Tool, db.Tool.business_identifier),
        ):
            ids = {
                link.entity_id
                for values in links_by_document.values()
                for link in values
                if link.entity_type == linked_entity_type
            }
            if ids:
                identifiers.update(
                    {
                        (linked_entity_type, row_id): value
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
        if photos_only and entity_type == "eoat" and entity_id is not None:
            selected_photo = self._selected_eoat_profile_photos([entity_id]).get(entity_id)
            if selected_photo:
                # Keep the gallery's leading photo aligned with the Library and
                # profile hero without exposing any storage-path information.
                results.sort(key=lambda result: result.document_uuid != selected_photo.document_uuid)
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
        normalized_query = query.strip()
        category_hint = None
        for category, prefix in (("machine", "machine "), ("tool", "tool "), ("eoat", "eoat ")):
            if normalized_query.casefold().startswith(prefix):
                category_hint = category
                normalized_query = normalized_query[len(prefix) :].strip()
                break
        results: list[SearchResult] = []
        eoats, _ = self.list_eoats(search=normalized_query, active=None, page_size=limit)
        results.extend(
            SearchResult(
                category="eoat",
                identifier=e.business_identifier,
                title=e.display_name or e.business_identifier,
                subtitle=e.eoat_type or "EOAT",
                matched_field="identifier/name/description",
            )
            for e in eoats
            if category_hint in (None, "eoat")
        )
        machines, _ = self.list_machines(search=normalized_query, active=None, page_size=limit)
        results.extend(
            SearchResult(
                category="machine",
                identifier=m.machine_number,
                title=m.machine_name or m.machine_number,
                subtitle=" · ".join(value for value in (m.plant_code, m.area) if value) or "Machine",
                matched_field="number/name/model",
            )
            for m in machines
            if category_hint in (None, "machine")
        )
        tools, _ = self.list_tools(search=normalized_query, active=None, page_size=limit)
        results.extend(
            SearchResult(
                category="tool",
                identifier=t.business_identifier,
                title=t.display_name or t.business_identifier,
                subtitle=t.mold_number or "Tool",
                matched_field="identifier/tool/mold/name",
            )
            for t in tools
            if category_hint in (None, "tool")
        )
        return results[:limit]
