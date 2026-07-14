from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    """Base for validated domain objects; contains no persistence concerns."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VersionedEntity(DomainModel):
    id: int | None = None
    row_version: int = Field(default=1, ge=1)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    archived_at: datetime | None = None
    source_system: str = "eoat_atlas"
    source_import_batch_id: int | None = None

    @field_validator("created_at", "updated_at", "archived_at")
    @classmethod
    def timestamps_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class Plant(VersionedEntity):
    plant_code: str = Field(min_length=1, max_length=32)
    plant_name: str = Field(min_length=1, max_length=160)
    description: str | None = None


class Area(VersionedEntity):
    plant_id: int
    area_code: str = Field(min_length=1, max_length=64)
    area_name: str = Field(min_length=1, max_length=160)
    area_type: str | None = None
    cleanroom_classification: str | None = None


class EOAT(VersionedEntity):
    business_identifier: str = Field(min_length=1, max_length=64)
    legacy_identifier: str | None = None
    display_name: str | None = None
    description: str | None = None
    eoat_type_code: str | None = None
    connection_type_code: str | None = None
    cleanroom_classification_code: str | None = None
    status_code: str | None = None
    revision: str | None = None
    number_of_parts_picked: int | None = Field(default=None, ge=0)
    number_of_vacuum_cups: int | None = Field(default=None, ge=0)
    number_of_grippers: int | None = Field(default=None, ge=0)
    vacuum_present: bool | None = None
    sensors_present: bool | None = None
    part_present_sensor_present: bool | None = None
    vacuum_confirmation_sensor_present: bool | None = None
    quick_disconnect_present: bool | None = None
    frame_material: str | None = None
    weight_kg: Decimal | None = Field(default=None, ge=0)
    maximum_payload_kg: Decimal | None = Field(default=None, ge=0)
    drawing_number: str | None = None
    manufacturer: str | None = None
    notes: str | None = None


class Machine(VersionedEntity):
    plant_id: int
    area_id: int | None = None
    machine_number: str = Field(min_length=1, max_length=64)
    machine_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    machine_type: str | None = None
    press_capacity_tons: Decimal | None = Field(default=None, gt=0)
    controller_type: str | None = None
    cleanroom_classification_code: str | None = None
    status_code: str | None = None
    notes: str | None = None


class Robot(VersionedEntity):
    plant_id: int
    area_id: int | None = None
    robot_number: str = Field(min_length=1, max_length=64)
    robot_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    controller_model: str | None = None
    serial_number: str | None = None
    payload_capacity_kg: Decimal | None = Field(default=None, gt=0)
    reach_mm: Decimal | None = Field(default=None, gt=0)
    notes: str | None = None


class Tool(VersionedEntity):
    business_identifier: str = Field(min_length=1, max_length=96)
    tool_number: str | None = None
    mold_number: str | None = None
    display_name: str | None = None
    description: str | None = None
    cavity_count: int | None = Field(default=None, ge=0)
    customer: str | None = None
    program_name: str | None = None
    status_code: str | None = None
    notes: str | None = None


class Part(VersionedEntity):
    part_number: str = Field(min_length=1, max_length=96)
    part_name: str | None = None
    part_family: str | None = None
    customer: str | None = None
    material: str | None = None
    resin_type: str | None = None
    color: str | None = None
    cleanroom_required: bool | None = None
    status_code: str | None = None
    notes: str | None = None


class CompatibilityRelationship(VersionedEntity):
    compatibility_status_code: str
    verified_at: datetime | None = None
    verification_source_code: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    reason: str | None = None
    conditions: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def valid_effective_range(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be earlier than effective_from")
        return self


class EOATMachineCompatibility(CompatibilityRelationship):
    eoat_id: int
    machine_id: int


class EOATToolCompatibility(CompatibilityRelationship):
    eoat_id: int
    tool_id: int


class ToolMachineCompatibility(CompatibilityRelationship):
    tool_id: int
    machine_id: int


class EOATInstallation(DomainModel):
    id: int | None = None
    eoat_id: int
    machine_id: int
    tool_id: int | None = None
    robot_id: int | None = None
    installed_at: datetime
    removed_at: datetime | None = None
    installation_reason: str | None = None
    removal_reason: str | None = None
    installation_notes: str | None = None
    removal_notes: str | None = None
    row_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def removal_follows_install(self):
        if self.removed_at and self.removed_at < self.installed_at:
            raise ValueError("removed_at cannot be earlier than installed_at")
        return self


class FitCheckRecord(DomainModel):
    id: int | None = None
    machine_id: int
    tool_id: int
    eoat_id: int
    overall_status_code: str
    evaluation_engine_version: str
    performed_at: datetime = Field(default_factory=utc_now)
    request_id: UUID
    result_summary: str | None = None
    result_details: dict[str, Any] = Field(default_factory=dict)


class AuditRecord(VersionedEntity):
    audit_identifier: str
    eoat_id: int | None = None
    machine_id: int | None = None
    tool_id: int | None = None
    robot_id: int | None = None
    audit_date: datetime | None = None
    status_code: str | None = None
    source_sheet: str | None = None
    source_row_number: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DocumentRecord(VersionedEntity):
    document_uuid: UUID
    document_type_code: str
    document_number: str | None = None
    title: str
    revision: str | None = None
    storage_path: str
    checksum_sha256: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    mime_type: str | None = None


class PhotoRecord(DomainModel):
    id: int | None = None
    document_id: int
    photo_view_type: str | None = None
    captured_at: datetime | None = None
    caption: str | None = None
    is_profile_photo: bool = False
    sort_order: int = 0


class ApplicationInstance(DomainModel):
    id: int | None = None
    instance_uuid: UUID
    computer_name: str
    installation_name: str | None = None
    application_version: str
    registered_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime | None = None
    is_active: bool = True


class UserIdentity(VersionedEntity):
    external_identity: str | None = None
    username: str
    display_name: str
    email: str | None = None
    authentication_provider: str | None = None


class ChangeAuditEvent(DomainModel):
    event_uuid: UUID
    request_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    entity_type: str
    entity_id: int
    action: str
    previous_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    changed_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    source: str
    success: bool


class SystemSetting(VersionedEntity):
    setting_key: str
    setting_value: Any
    value_type: str
    description: str | None = None
    is_sensitive: bool = False
