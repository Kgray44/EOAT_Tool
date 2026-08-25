from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PaginationMetadata(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class HealthResult(BaseModel):
    api_reachable: bool = True
    database_reachable: bool
    current_schema_revision: str | None
    expected_schema_revision: str
    compatible: bool
    environment: str
    writes_enabled: bool
    api_version: str
    server_timestamp: datetime


class DataStatus(BaseModel):
    """Read-only freshness evidence for the normal browser shell."""

    status: Literal["available"] = "available"
    data_last_modified_at: datetime
    server_time: datetime
    data_revision: int = Field(ge=0)


class LookupValue(BaseModel):
    code: str
    display_name: str
    description: str | None = None
    sort_order: int = 0


class RelationshipSummary(BaseModel):
    relationship_type: str
    identifier: str
    display_name: str | None = None
    status: str = "UNKNOWN"
    reason: str | None = None


class CurrentEOATLocation(BaseModel):
    """Safe, current-location presentation where source evidence is limited."""

    state: Literal["INSTALLED", "STORED", "UNKNOWN", "INACTIVE", "CONFLICTING"]
    source: Literal["OBSERVATION", "LIFECYCLE_EVENT", "RESOLVER", "NONE"]
    machine_number: str | None = None
    storage_location: str | None = None
    observed_at: datetime | None = None
    confidence: str = "UNKNOWN"
    resolution_status: Literal["CURRENT", "SUPERSEDED", "REVIEW_REQUIRED"] = "CURRENT"
    evidence: str = "Current read-model state"


class PhysicalAuditConfiguration(BaseModel):
    """Known configuration observed during one physical audit, never a current-location claim."""

    description: str | None = None
    eoat_type: str | None = None
    connection_type: str | None = None
    cleanroom_classification: str | None = None
    parts_picked: int | None = None
    vacuum_cup_count: int | None = None
    gripper_count: int | None = None
    cup_material: str | None = None
    cup_size: str | None = None
    vacuum_generator: str | None = None
    vacuum_circuits: int | None = None
    pressure_circuits: int | None = None
    gripper_type: str | None = None
    gripper_model: str | None = None
    sensors_present: bool | None = None
    part_present_sensor_present: bool | None = None
    vacuum_confirmation_sensor_present: bool | None = None
    quick_disconnect_present: bool | None = None
    pneumatic_disconnect_type: str | None = None
    electrical_disconnect_type: str | None = None
    electrical_wiring_present: bool | None = None


class PhysicalAuditObservation(BaseModel):
    """A dated physical-audit observation with its source identity intact."""

    audit_identifier: str
    observed_on: date | None = None
    observed_machine: str | None = None
    observed_tool: str | None = None
    verified: bool | None = None
    evidence: str = "Physical audit"
    configuration: PhysicalAuditConfiguration


class EOATSummary(BaseModel):
    business_identifier: str
    legacy_identifier: str | None = None
    display_name: str | None = None
    eoat_type: str | None = None
    connection_type: str | None = None
    cleanroom_classification: str | None = None
    status: str | None = None
    number_of_parts_picked: int | None = None
    is_active: bool
    row_version: int
    current_location: str = "UNKNOWN_NOT_VERIFIED"
    current_location_detail: CurrentEOATLocation | None = None
    photo_document_uuid: str | None = None
    photo_available_through_web: bool = False


class EOATProfile(EOATSummary):
    description: str | None = None
    revision: str | None = None
    number_of_vacuum_cups: int | None = None
    number_of_grippers: int | None = None
    vacuum_present: bool | None = None
    sensors_present: bool | None = None
    part_present_sensor_present: bool | None = None
    vacuum_confirmation_sensor_present: bool | None = None
    quick_disconnect_present: bool | None = None
    cup_material: str | None = None
    frame_material: str | None = None
    weight_kg: float | None = None
    maximum_payload_kg: float | None = None
    drawing_number: str | None = None
    manufacturer: str | None = None
    date_built: str | None = None
    date_commissioned: str | None = None
    notes: str | None = None
    part_status: str = "NOT_YET_VERIFIED"
    relationships: list[RelationshipSummary] = Field(default_factory=list)
    audit_evidence: list[dict[str, Any]] = Field(default_factory=list)
    latest_physical_audit: PhysicalAuditObservation | None = None


class MachineSummary(BaseModel):
    plant_code: str | None = None
    machine_number: str
    machine_name: str | None = None
    area: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    cleanroom_classification: str | None = None
    status: str | None = None
    current_eoat: str = "UNKNOWN_NOT_VERIFIED"
    is_active: bool
    row_version: int


class MachineProfile(MachineSummary):
    controller_type: str | None = None
    press_capacity_tons: float | None = None
    serial_number: str | None = None
    machine_type: str | None = None
    installation_date: str | None = None
    notes: str | None = None
    relationships: list[RelationshipSummary] = Field(default_factory=list)
    robots: list[RelationshipSummary] = Field(default_factory=list)
    audit_evidence: list[dict[str, Any]] = Field(default_factory=list)
    latest_physical_audit: PhysicalAuditObservation | None = None


class ToolSummary(BaseModel):
    business_identifier: str
    tool_number: str | None = None
    mold_number: str | None = None
    display_name: str | None = None
    status: str | None = None
    part_status: str = "NOT_YET_VERIFIED"
    is_active: bool
    row_version: int


class ToolProfile(ToolSummary):
    description: str | None = None
    cavity_count: int | None = None
    tool_type: str | None = None
    customer: str | None = None
    program_name: str | None = None
    notes: str | None = None
    relationships: list[RelationshipSummary] = Field(default_factory=list)
    audit_evidence: list[dict[str, Any]] = Field(default_factory=list)
    latest_physical_audit: PhysicalAuditObservation | None = None


class HistoryEvent(BaseModel):
    event_id: str
    eoat_identifier: str | None = None
    event_type: str
    event_category: str
    occurred_at: datetime | None = None
    summary: str
    description: str | None = None
    actor: str | None = None
    application_instance: str | None = None
    source_record_type: str | None = None
    source_record_id: str | None = None
    related_machine: str | None = None
    related_tool: str | None = None
    related_robot: str | None = None
    related_storage_location: str | None = None
    related_document: str | None = None
    related_photo: str | None = None
    reason: str | None = None
    notes: str | None = None
    previous_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class DocumentMetadata(BaseModel):
    document_uuid: str
    document_number: str | None = None
    title: str
    description: str | None = None
    file_name: str
    storage_path: str
    mime_type: str | None = None
    path_available: bool | None = None
    related_entities: list[RelationshipSummary] = Field(default_factory=list)


class PhotoMetadata(DocumentMetadata):
    photo_view_type: str | None = None
    captured_at: datetime | None = None
    caption: str | None = None
    is_profile_photo: bool = False


class WebDocumentMetadata(BaseModel):
    """Browser-safe document metadata; storage paths are never serialized."""

    document_uuid: str
    document_number: str | None = None
    title: str
    description: str | None = None
    file_name: str
    mime_type: str | None = None
    related_entities: list[RelationshipSummary] = Field(default_factory=list)
    content_delivery_state: Literal["AVAILABLE", "NOT_AVAILABLE_THROUGH_WEB"] = "NOT_AVAILABLE_THROUGH_WEB"


class WebPhotoMetadata(WebDocumentMetadata):
    photo_view_type: str | None = None
    captured_at: datetime | None = None
    caption: str | None = None
    is_profile_photo: bool = False


class SearchResult(BaseModel):
    category: Literal["eoat", "machine", "tool"]
    identifier: str
    title: str
    subtitle: str = ""
    matched_field: str


class PairCompatibility(BaseModel):
    pair: str
    result: Literal["COMPATIBLE", "INCOMPATIBLE", "UNKNOWN", "NOT_EVALUATED"]
    reason: str
    evidence_source: str | None = None


class FitCheckEntity(BaseModel):
    entity_type: Literal["machine", "tool", "eoat"]
    identifier: str
    label: str
    secondary: str | None = None


class FitCheckCriterion(BaseModel):
    """A server-evaluated desktop-equivalent Fit Check requirement."""

    code: str
    label: str
    result: Literal["COMPATIBLE", "INCOMPATIBLE", "NEEDS_REVIEW", "NOT_APPLICABLE"]
    reason: str
    evidence_source: str | None = None
    pair: str | None = None


class FitCheckWarning(BaseModel):
    severity: Literal["info", "warning", "critical"]
    title: str
    message: str


class FitCheckAlternative(BaseModel):
    entity: FitCheckEntity
    status: Literal["best", "available", "verify", "missing_data", "not_recommended", "current", "incompatible"]
    status_label: str
    reason: str


class FitCheckDetailSection(BaseModel):
    title: str
    entries: list[str] = Field(default_factory=list)


class FitCheckResult(BaseModel):
    overall_result: Literal["COMPATIBLE", "INCOMPATIBLE", "NEEDS_REVIEW", "INVALID_INPUT"]
    machine_tool_result: PairCompatibility
    machine_eoat_result: PairCompatibility
    tool_eoat_result: PairCompatibility
    reasons: list[str]
    warnings: list[str]
    unknown_relationships: list[str]
    alternative_compatible_eoats: list[str]
    decision_summary: str = ""
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    selected_entities: list[FitCheckEntity] = Field(default_factory=list)
    requirements: list[FitCheckCriterion] = Field(default_factory=list)
    structured_warnings: list[FitCheckWarning] = Field(default_factory=list)
    alternative_machines: list[FitCheckAlternative] = Field(default_factory=list)
    alternative_eoats: list[FitCheckAlternative] = Field(default_factory=list)
    detail_sections: list[FitCheckDetailSection] = Field(default_factory=list)
    recommended_eoat: FitCheckAlternative | None = None
    setup_packet_available: bool = False
    evaluation_engine_version: str = "mysql-read-v1"
    stored: bool = False


class FitCheckRequest(BaseModel):
    machine_number: str
    tool_number: str
    eoat_identifier: str
    plant_code: str | None = None
    persist: bool = False


class FitCheckOption(BaseModel):
    """A browser-safe selectable asset for the read-only Fit Check."""

    identifier: str
    label: str
    plant_code: str | None = None


class WebFitCheckOptions(BaseModel):
    """Effective, compatible candidates for a partial normal-browser Fit Check."""

    machines: list[FitCheckOption] = Field(default_factory=list)
    tools: list[FitCheckOption] = Field(default_factory=list)
    eoats: list[FitCheckOption] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unresolved_inputs: list[Literal["machine", "tool", "eoat"]] = Field(default_factory=list)
    query_mode: Literal["recommendations", "global_catalog"] = "recommendations"
    query_slot: Literal["machine", "tool", "eoat"] | None = None


class SyncStatus(BaseModel):
    api_version: str
    schema_revision: str | None
    server_revision: str
    current_cursor: int
    compatible: bool


class SyncChange(BaseModel):
    cursor: int
    entity_type: str
    entity_id: int
    operation: str
    row_version: int
    changed_at: datetime


class SyncChangeBatch(BaseModel):
    after_cursor: int
    next_cursor: int
    changes: list[SyncChange]


class SyncSnapshot(BaseModel):
    server_revision: str
    schema_revision: str | None
    cursor: int
    generated_at: datetime
    lookups: dict[str, list[LookupValue]]
    eoats: list[EOATProfile]
    machines: list[MachineProfile]
    tools: list[ToolProfile]
    documents: list[DocumentMetadata]
    photos: list[PhotoMetadata]
    eoat_history: list[HistoryEvent] = Field(default_factory=list)


class PaginatedEOATs(BaseModel):
    items: list[EOATSummary]
    pagination: PaginationMetadata


class PaginatedMachines(BaseModel):
    items: list[MachineSummary]
    pagination: PaginationMetadata


class PaginatedTools(BaseModel):
    items: list[ToolSummary]
    pagination: PaginationMetadata


class PaginatedHistory(BaseModel):
    items: list[HistoryEvent]
    pagination: PaginationMetadata
