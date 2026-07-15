from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExpectedVersion(WriteModel):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class EOATCreate(WriteModel):
    business_identifier: str = Field(min_length=1, max_length=64)
    legacy_identifier: str | None = Field(default=None, max_length=96)
    display_name: str | None = Field(default=None, max_length=160)
    description: str | None = None
    eoat_type: str | None = None
    connection_type: str | None = None
    cleanroom_classification: str | None = None
    status: str | None = None
    revision: str | None = None
    number_of_parts_picked: int | None = Field(default=None, ge=0)
    number_of_vacuum_cups: int | None = Field(default=None, ge=0)
    number_of_grippers: int | None = Field(default=None, ge=0)
    vacuum_present: bool | None = None
    sensors_present: bool | None = None
    part_present_sensor_present: bool | None = None
    vacuum_confirmation_sensor_present: bool | None = None
    quick_disconnect_present: bool | None = None
    cup_material: str | None = None
    frame_material: str | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    maximum_payload_kg: float | None = Field(default=None, gt=0)
    drawing_number: str | None = None
    manufacturer: str | None = None
    date_built: date | None = None
    date_commissioned: date | None = None
    notes: str | None = None


class EOATPatch(ExpectedVersion):
    legacy_identifier: str | None = Field(default=None, max_length=96)
    display_name: str | None = Field(default=None, max_length=160)
    description: str | None = None
    eoat_type: str | None = None
    connection_type: str | None = None
    cleanroom_classification: str | None = None
    status: str | None = None
    revision: str | None = None
    number_of_parts_picked: int | None = Field(default=None, ge=0)
    number_of_vacuum_cups: int | None = Field(default=None, ge=0)
    number_of_grippers: int | None = Field(default=None, ge=0)
    vacuum_present: bool | None = None
    sensors_present: bool | None = None
    part_present_sensor_present: bool | None = None
    vacuum_confirmation_sensor_present: bool | None = None
    quick_disconnect_present: bool | None = None
    cup_material: str | None = None
    frame_material: str | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    maximum_payload_kg: float | None = Field(default=None, gt=0)
    drawing_number: str | None = None
    manufacturer: str | None = None
    date_built: date | None = None
    date_commissioned: date | None = None
    notes: str | None = None


class MachineCreate(WriteModel):
    plant_code: str = Field(min_length=1, max_length=32)
    machine_number: str = Field(min_length=1, max_length=64)
    area_code: str | None = None
    machine_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    machine_type: str | None = None
    press_capacity_tons: float | None = Field(default=None, gt=0)
    controller_type: str | None = None
    cleanroom_classification: str | None = None
    status: str | None = None
    installation_date: date | None = None
    notes: str | None = None


class MachinePatch(ExpectedVersion):
    area_code: str | None = None
    machine_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    machine_type: str | None = None
    press_capacity_tons: float | None = Field(default=None, gt=0)
    controller_type: str | None = None
    cleanroom_classification: str | None = None
    status: str | None = None
    installation_date: date | None = None
    notes: str | None = None


class ToolCreate(WriteModel):
    business_identifier: str = Field(min_length=1, max_length=96)
    tool_number: str | None = None
    mold_number: str | None = None
    display_name: str | None = None
    description: str | None = None
    cavity_count: int | None = Field(default=None, ge=0)
    tool_type: str | None = None
    customer: str | None = None
    program_name: str | None = None
    status: str | None = None
    notes: str | None = None


class ToolPatch(ExpectedVersion):
    tool_number: str | None = None
    mold_number: str | None = None
    display_name: str | None = None
    description: str | None = None
    cavity_count: int | None = Field(default=None, ge=0)
    tool_type: str | None = None
    customer: str | None = None
    program_name: str | None = None
    status: str | None = None
    notes: str | None = None


class RobotCreate(WriteModel):
    plant_code: str = Field(min_length=1, max_length=32)
    robot_identifier: str = Field(min_length=1, max_length=64)
    area_code: str | None = None
    robot_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    controller_model: str | None = None
    serial_number: str | None = None
    payload_capacity_kg: float | None = Field(default=None, gt=0)
    reach_mm: float | None = Field(default=None, gt=0)
    mounting_type: str | None = None
    communication_interface: str | None = None
    status: str | None = None
    notes: str | None = None


class RobotPatch(ExpectedVersion):
    area_code: str | None = None
    robot_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    controller_model: str | None = None
    serial_number: str | None = None
    payload_capacity_kg: float | None = Field(default=None, gt=0)
    reach_mm: float | None = Field(default=None, gt=0)
    mounting_type: str | None = None
    communication_interface: str | None = None
    status: str | None = None
    notes: str | None = None


class CompatibilityWrite(WriteModel):
    eoat_identifier: str | None = None
    machine_number: str | None = None
    tool_identifier: str | None = None
    compatibility_status: str
    verification_source: str | None = None
    verified_at: datetime | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    reason: str | None = None
    conditions: str | None = None
    notes: str | None = None
    expected_row_version: int | None = Field(default=None, ge=1)
    attributes: dict[str, bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not be before effective_from")
        return self


class MoveToMachine(WriteModel):
    machine_number: str
    expected_row_version: int = Field(ge=1)
    tool_identifier: str | None = None
    robot_identifier: str | None = None
    installed_at: datetime | None = None
    reason: str | None = None
    notes: str | None = None
    override_reason: str | None = None


class MoveToStorage(WriteModel):
    storage_location_code: str
    expected_row_version: int = Field(ge=1)
    stored_at: datetime | None = None
    reason: str | None = None
    notes: str | None = None


class MarkLocationUnknown(ExpectedVersion):
    confirm: bool

    @field_validator("confirm")
    @classmethod
    def confirmed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("explicit confirmation is required")
        return value


class InstallationClose(ExpectedVersion):
    removed_at: datetime | None = None


class AuditCreate(WriteModel):
    audit_identifier: str
    eoat_identifier: str | None = None
    machine_number: str | None = None
    tool_identifier: str | None = None
    robot_identifier: str | None = None
    audit_date: datetime | None = None
    status: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class AuditPatch(ExpectedVersion):
    audit_date: datetime | None = None
    status: str | None = None
    details: dict[str, Any] | None = None
    notes: str | None = None


class MaintenanceCreate(WriteModel):
    eoat_identifier: str | None = None
    machine_number: str | None = None
    event_type: str
    occurred_at: datetime
    downtime_minutes: int | None = Field(default=None, ge=0)
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class MaintenancePatch(ExpectedVersion):
    event_type: str | None = None
    occurred_at: datetime | None = None
    downtime_minutes: int | None = Field(default=None, ge=0)
    summary: str | None = None
    details: dict[str, Any] | None = None


class DocumentCreate(WriteModel):
    document_type: str
    document_number: str | None = None
    title: str
    description: str | None = None
    revision: str | None = None
    storage_path: str
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    mime_type: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    relationship_type: str = "attachment"


class DocumentPatch(ExpectedVersion):
    document_number: str | None = None
    title: str | None = None
    description: str | None = None
    revision: str | None = None
    storage_path: str | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    mime_type: str | None = None


class PhotoCreate(DocumentCreate):
    document_type: str = "photo"
    photo_view_type: str | None = None
    captured_at: datetime | None = None
    caption: str | None = None


class PhotoPatch(ExpectedVersion):
    photo_view_type: str | None = None
    captured_at: datetime | None = None
    caption: str | None = None
    title: str | None = None
    description: str | None = None


class TagCreate(WriteModel):
    tag_code: str
    display_name: str
    description: str | None = None
    color_key: str


class TagPatch(ExpectedVersion):
    display_name: str | None = None
    description: str | None = None
    color_key: str | None = None


class TagAssignmentWrite(WriteModel):
    expected_row_version: int | None = Field(default=None, ge=1)
    comment: str | None = None


class TagAssignmentArchiveBatch(WriteModel):
    assignment_ids: list[int] = Field(min_length=1, max_length=500)


class AnnotationCreate(WriteModel):
    annotation_type: str = "note"
    subject: str
    body: str
    importance: str = "Neutral"
    status: str | None = None
    collection: str | None = None
    follow_up_date: date | None = None


class AnnotationPatch(ExpectedVersion):
    subject: str | None = None
    body: str | None = None
    importance: str | None = None
    status: str | None = None
    collection: str | None = None
    follow_up_date: date | None = None


class ApplicationInstanceRegistration(WriteModel):
    # Existing installations use both UUIDs and stable host-derived identifiers.
    # Do not rotate either form merely to satisfy a release-registration request.
    instance_uuid: str = Field(min_length=1, max_length=36)
    computer_name: str
    application_version: str
    release_id: str
    build_id: str
    commit_sha: str | None = None
    release_channel: str = "development"
    database_schema_revision: str | None = None
    api_contract_version: str | None = None
    launcher_version: str | None = None
    installer_version: str | None = None
    operating_system: str | None = None
    plant_code: str | None = None
    area_code: str | None = None

    @model_validator(mode="after")
    def validate_release_identity(self):
        if self.release_id != f"eoat-atlas-{self.application_version}":
            raise ValueError("release_id must match application_version")
        if not self.build_id.strip():
            raise ValueError("build_id is required")
        return self


class ApplicationInstanceHeartbeat(WriteModel):
    instance_uuid: str = Field(min_length=1, max_length=36)


EntityType = Literal["eoat", "machine", "tool", "robot", "audit", "maintenance", "annotation_target"]
