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
    application_version: str
    release_id: str
    build_id: str
    api_contract_version: str
    database_schema_revision: str
    database_server_version: str = ""
    server_timestamp: datetime


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
    state: Literal["INSTALLED", "STORED", "UNKNOWN", "INACTIVE", "CONFLICTING"]
    source: Literal["OBSERVATION", "LIFECYCLE_EVENT", "RESOLVER", "NONE"]
    machine_number: str | None = None
    storage_location: str | None = None
    observed_at: datetime | None = None
    observed_on: date | None = None
    observation_precision: Literal["TIMESTAMP", "DATE"] | None = None
    confidence: str
    resolution_status: Literal["CURRENT", "SUPERSEDED", "REVIEW_REQUIRED"]
    evidence: str
    observation_uuid: str | None = None
    conflict_group_uuid: str | None = None

    @property
    def display(self) -> str:
        if self.state == "INSTALLED" and self.machine_number:
            return f"INSTALLED — Machine {self.machine_number}"
        if self.state == "STORED":
            return f"STORED — {self.storage_location or 'cabinet/location unspecified'}"
        return self.state


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
    notes: str | None = None
    part_status: str = "NOT_YET_VERIFIED"
    relationships: list[RelationshipSummary] = Field(default_factory=list)
    audit_evidence: list[dict[str, Any]] = Field(default_factory=list)


class MachineSummary(BaseModel):
    plant_code: str
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
    notes: str | None = None
    relationships: list[RelationshipSummary] = Field(default_factory=list)
    robots: list[RelationshipSummary] = Field(default_factory=list)


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
    tool_type: str | None = None
    customer: str | None = None
    program_name: str | None = None
    notes: str | None = None
    relationships: list[RelationshipSummary] = Field(default_factory=list)
    audit_evidence: list[dict[str, Any]] = Field(default_factory=list)


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
    """Browser-safe document metadata. Internal storage paths are intentionally excluded."""

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


class MachineCurrentSetup(BaseModel):
    machine_number: str
    current_eoat: str = "UNKNOWN_NOT_VERIFIED"
    current_tool: str = "UNKNOWN_NOT_VERIFIED"
    verified: bool = False
    location_semantics: str


class WebFitCheckRequest(BaseModel):
    """Read-only browser input. Persistence is deliberately not representable."""

    plant_code: str | None = None
    machine_number: str
    tool_number: str
    eoat_identifier: str


class FitCheckOption(BaseModel):
    """A browser-safe selectable asset for the read-only Fit Check."""

    identifier: str
    label: str
    plant_code: str | None = None


class WebFitCheckOptions(BaseModel):
    """Candidates backed by explicit, currently-effective compatible records only."""

    machines: list[FitCheckOption] = Field(default_factory=list)
    tools: list[FitCheckOption] = Field(default_factory=list)
    eoats: list[FitCheckOption] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unresolved_inputs: list[Literal["machine", "tool", "eoat"]] = Field(default_factory=list)


class SearchResult(BaseModel):
    category: Literal["eoat", "machine", "tool"]
    identifier: str
    title: str
    subtitle: str = ""
    matched_field: str


class PairCompatibility(BaseModel):
    pair: str
    result: Literal["COMPATIBLE", "INCOMPATIBLE", "NEEDS_REVIEW", "UNKNOWN", "NOT_EVALUATED"]
    reason: str
    status_code: str | None = None
    verification_source: str | None = None
    is_active: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class FitCheckResult(BaseModel):
    overall_result: Literal["COMPATIBLE", "INCOMPATIBLE", "NEEDS_REVIEW", "INVALID_INPUT"]
    machine_tool_result: PairCompatibility
    machine_eoat_result: PairCompatibility
    tool_eoat_result: PairCompatibility
    reasons: list[str]
    warnings: list[str]
    unknown_relationships: list[str]
    alternative_compatible_eoats: list[str]
    evaluation_engine_version: str = "mysql-read-v1"
    stored: bool = False


class FitCheckRequest(BaseModel):
    plant_code: str | None = None
    machine_number: str
    tool_number: str
    eoat_identifier: str
    persist: bool = False


class SyncStatus(BaseModel):
    api_version: str
    schema_revision: str | None
    server_revision: str
    current_cursor: int
    compatible: bool


class DataStatusResponse(BaseModel):
    """Small, server-authoritative freshness payload safe for frequent reads."""

    status: Literal["available"]
    data_revision: int = Field(ge=0)
    data_last_modified_at: datetime
    last_import_at: datetime | None = None
    last_import_source: str | None = None
    server_time: datetime
    source: Literal["mysql"]
    environment: str


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
    data_status: DataStatusResponse
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
