# ruff: noqa: B008
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import models as db
from ..database.session import get_runtime_session, get_write_session
from ..errors import APIError
from ..security import ActorContext, issue_danger_step_up, require_admin, require_admin_mutation
from ..write_services import idempotent
from .operation_contracts import DangerCommitRequest, DangerPreviewRequest, DangerStepUpRequest, ExportRequest, IntegrityScanRequest, SupportBundleRequest
from .operations import OP_FIXTURE_RECOVERY, RISK_HIGH, audit_export, danger_commit, danger_preview, latest_integrity_summary, operation_view, require_operation_ledger, run_integrity_scan, support_bundle

router = APIRouter(prefix="/api/v1/admin", tags=["admin-phase4"])


@router.post("/integrity/scans")
def start_integrity_scan(
    _payload: IntegrityScanRequest,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.integrity.run")),
):
    require_operation_ledger(session)
    return run_integrity_scan(session, actor)


@router.get("/integrity/latest")
def latest_integrity_scan(
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin("admin.area.view")),
):
    return latest_integrity_summary(session)


@router.get("/operations/{operation_id}")
def operation_status(
    operation_id: str,
    session: Session = Depends(get_runtime_session),
    _actor: ActorContext = Depends(require_admin("admin.area.view")),
):
    row = session.scalar(select(db.AdminOperation).where(db.AdminOperation.operation_id == operation_id))
    if row is None:
        raise APIError(404, "ADMIN_OPERATION_NOT_FOUND", "The administrative operation was not found.")
    return operation_view(row)


@router.post("/audit/exports")
def create_audit_export(
    payload: ExportRequest,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.export.audit")),
):
    allowed = {"start", "end", "actor", "action", "action_category", "entity_type", "entity_id", "result", "source", "request_id", "correlation_id", "search", "security_events_only", "administrative_events_only"}
    if not set(payload.filters).issubset(allowed):
        raise APIError(422, "EXPORT_FILTER_INVALID", "The export includes an unsupported audit filter.")
    filters = {key: value for key, value in payload.filters.items() if value not in (None, "")}
    # Repository filters are already controlled; export never accepts SQL or arbitrary sort values.
    for flag in ("security_events_only", "administrative_events_only"):
        if flag in filters and not isinstance(filters[flag], bool):
            raise APIError(422, "EXPORT_FILTER_INVALID", "Audit filter flags must be boolean.")
    for boundary in ("start", "end"):
        value = filters.get(boundary)
        if value is None:
            continue
        if not isinstance(value, str):
            raise APIError(422, "EXPORT_FILTER_INVALID", "Audit time boundaries must be ISO-8601 UTC timestamps.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise APIError(422, "EXPORT_FILTER_INVALID", "Audit time boundaries must be ISO-8601 UTC timestamps.") from exc
        if parsed.tzinfo is None:
            raise APIError(422, "EXPORT_FILTER_INVALID", "Audit time boundaries must include a UTC offset.")
        filters[boundary] = parsed.astimezone(timezone.utc)
    payload_bytes, media_type, manifest = audit_export(session, actor, filters, payload.format)
    suffix = "csv" if payload.format == "csv" else "json"
    filename = f"EOAT_Atlas_Audit_export_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{manifest['export_id']}.{suffix}"
    return Response(content=payload_bytes, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-EOAT-Export-Id": manifest["export_id"], "X-EOAT-Export-Checksum": manifest["sha256"]})


@router.post("/support-bundles")
def create_support_bundle(
    payload: SupportBundleRequest,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.export.support")),
):
    body, manifest = support_bundle(session, actor, payload.sections, payload.request_id)
    filename = f"EOAT_Atlas_Support_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{manifest['bundle_id']}.json"
    return Response(content=body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-EOAT-Support-Bundle-Id": manifest["bundle_id"], "X-EOAT-Support-Checksum": manifest["sha256"]})


@router.post("/danger-zone/fixture-recovery/step-up")
def danger_step_up(
    request: Request,
    payload: DangerStepUpRequest,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.danger.execute")),
):
    require_operation_ledger(session)
    proof = issue_danger_step_up(request, session, actor, operation_type=OP_FIXTURE_RECOVERY, risk_class=RISK_HIGH, rehearsal_step_up_secret=payload.rehearsal_step_up_secret)
    return {"step_up_reference": proof.step_up_reference, "expires_at": proof.expires_at, "operation_type": proof.operation_type, "environment": os.getenv("EOAT_API_ENVIRONMENT", "development"), "rehearsal_only": True}


@router.post("/danger-zone/fixture-recovery/preview")
def preview_fixture_recovery(
    payload: DangerPreviewRequest,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.danger.execute")),
):
    require_operation_ledger(session)
    return danger_preview(session, actor, payload.fixture_namespace)


@router.post("/danger-zone/fixture-recovery/commit")
def commit_fixture_recovery(
    request: Request,
    payload: DangerCommitRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require_admin_mutation("admin.danger.execute")),
):
    require_operation_ledger(session)
    return idempotent(session, actor, OP_FIXTURE_RECOVERY, idempotency_key, payload.model_dump(), lambda: danger_commit(session, request, actor, payload.preview_reference, payload.confirmation, payload.reason))
