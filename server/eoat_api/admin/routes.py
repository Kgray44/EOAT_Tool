# ruff: noqa: B008
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database.session import get_runtime_session
from ..security import ActorContext, require_admin
from ..services import API_VERSION, AtlasService
from .contracts import AdminOverviewContract, AuditActor, AuditCatalogResponse, AuditEntity, AuditEventResponse, AuditListResponse
from .repository import AuditEventRepository
from .taxonomy import AuditAction, AuditResult, AuditSource

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _event_response(row) -> AuditEventResponse:
    return AuditEventResponse(
        event_id=row.event_id,
        occurred_at_utc=row.occurred_at_utc,
        actor=AuditActor(
            type=row.actor_type,
            id=row.actor_id,
            display_name=row.actor_display_name,
            directory_name=row.actor_directory_name,
        ),
        action=AuditAction(row.action),
        entity=AuditEntity(type=row.entity_type, id=row.entity_id, display_id=row.entity_display_id),
        changed_fields=row.changed_fields_json or [],
        before=row.before_state_json,
        after=row.after_state_json,
        reason_or_note=row.reason_or_note,
        source_client=AuditSource(row.source_client),
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        transaction_id=row.transaction_id,
        operation=row.operation,
        result=AuditResult(row.result),
        metadata=row.metadata_json,
        schema_version=row.schema_version,
    )


@router.get("/overview", response_model=AdminOverviewContract)
def overview(
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin("admin.area.view")),
):
    service = AtlasService(session)
    return AdminOverviewContract(
        api_version=API_VERSION,
        schema_revision=service.schema_revision(),
        observation_time_utc=datetime.now(timezone.utc),
        writes_enabled=os.getenv("EOAT_API_WRITES_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"},
    )


@router.get("/audit/catalog", response_model=AuditCatalogResponse)
def audit_catalog(_actor: ActorContext = Depends(require_admin("admin.audit.view"))):
    return AuditCatalogResponse(actions=list(AuditAction), results=list(AuditResult), sources=list(AuditSource))


@router.get("/audit/events", response_model=AuditListResponse)
def list_audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    start: datetime | None = None,
    end: datetime | None = None,
    actor: str | None = Query(None, max_length=255),
    action: AuditAction | None = None,
    entity_type: str | None = Query(None, max_length=64),
    entity_id: str | None = Query(None, max_length=255),
    result: AuditResult | None = None,
    source: AuditSource | None = None,
    request_id: str | None = Query(None, max_length=64),
    correlation_id: str | None = Query(None, max_length=64),
    search: str | None = Query(None, max_length=200),
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin("admin.audit.view")),
):
    rows, total = AuditEventRepository(session).list(
        page=page,
        page_size=page_size,
        start=start,
        end=end,
        actor=actor,
        action=action.value if action else None,
        entity_type=entity_type,
        entity_id=entity_id,
        result=result.value if result else None,
        source=source.value if source else None,
        request_id=request_id,
        correlation_id=correlation_id,
        search=search,
    )
    return AuditListResponse(items=[_event_response(row) for row in rows], page=page, page_size=page_size, total=total, sort="occurred_at_utc:desc,event_id:desc")


@router.get("/audit/events/{event_id}", response_model=AuditEventResponse)
def audit_event_detail(
    event_id: str,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin("admin.audit.view")),
):
    from ..errors import APIError

    row = AuditEventRepository(session).get(event_id)
    if row is None:
        raise APIError(404, "AUDIT_EVENT_NOT_FOUND", "The audit event was not found.")
    return _event_response(row)
