from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .taxonomy import AuditAction, AuditResult, AuditSource


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
    results: list[AuditResult]
    sources: list[AuditSource]


class AdminOverviewContract(BaseModel):
    api_version: str
    schema_revision: str | None = None
    audit_schema_version: int = 1
    observation_time_utc: datetime
    writes_enabled: bool
