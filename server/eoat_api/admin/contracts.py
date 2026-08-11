from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .taxonomy import AuditAction, AuditActionCategory, AuditResult, AuditSource


class AuditActor(BaseModel):
    type: str
    id: str | None = None
    display_name: str | None = None
    directory_name: str | None = None


class AuditEntity(BaseModel):
    type: str
    id: str
    display_id: str | None = None


class AuditEventResponse(BaseModel):
    event_id: str
    occurred_at_utc: datetime
    actor: AuditActor
    action: AuditAction
    action_category: AuditActionCategory
    entity: AuditEntity
    changed_fields: list[str] = Field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason_or_note: str | None = None
    source_client: AuditSource
    request_id: str | None = None
    correlation_id: str | None = None
    transaction_id: str | None = None
    operation: str | None = None
    result: AuditResult
    metadata: dict[str, Any] | None = None
    schema_version: int


class AuditListResponse(BaseModel):
    items: list[AuditEventResponse]
    page: int
    page_size: int
    total: int
    sort: str


class AuditCatalogResponse(BaseModel):
    actions: list[AuditAction]
    action_categories: list[AuditActionCategory]
    results: list[AuditResult]
    sources: list[AuditSource]


class AdminOverviewContract(BaseModel):
    api_version: str
    schema_revision: str | None = None
    audit_schema_version: int = 1
    observation_time_utc: datetime
    writes_enabled: bool


class AdminDataIntegrityContract(BaseModel):
    observation_time_utc: datetime
    invalid_relationship_count: int | None = None
    orphan_document_count: int | None = None
    status: str


class AdminAccessStateContract(BaseModel):
    authentication_provider: str | None = None
    administrator_group_mapping_configured: bool
    status: str


class AdminDiagnosticsContract(BaseModel):
    observation_time_utc: datetime
    api_status: str
    database_status: str
    audit_status: str


class AdminSettingsContract(BaseModel):
    key: str
    value: Any | None = None
    secret_configured: bool | None = None


class AdminOperationContract(BaseModel):
    operation_id: str
    operation_type: str
    status: str
    correlation_id: str | None = None


class AdminErrorContract(BaseModel):
    error_code: str
    message: str
    request_id: str | None = None
    diagnostic_context: dict[str, Any] | None = None
