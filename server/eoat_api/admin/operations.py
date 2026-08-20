"""Bounded Phase 4 diagnostics, evidence, integrity, and danger operations.

This module intentionally contains typed, owned operations only.  It never
executes arbitrary SQL, an OS command, a filesystem traversal, or an uploaded
program on behalf of a browser request.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..corporate_auth import corporate_provider_state
from ..database import models as db
from ..errors import APIError
from ..security import ActorContext, require_active_danger_step_up
from ..services import API_VERSION, EXPECTED_SCHEMA_REVISION, AtlasService
from .redaction import redact
from .repository import AuditEventRepository
from .service import AuditEventWriter
from .taxonomy import AuditAction, AuditResult

OP_FIXTURE_RECOVERY = "danger.fixture-recovery-rehearsal"
RISK_HIGH = "HIGH"
PREVIEW_TTL = timedelta(minutes=10)
FIXTURE_NAMESPACE = re.compile(r"^phase4-[a-z0-9-]{6,64}$")
TEST_RECOVERY_MAX_AGE_SECONDS = 4 * 60 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def operation_ledger_writable(session: Session) -> bool:
    """Inspect the current MySQL grant shape without creating a probe row."""
    try:
        grants = [str(row[0]).upper() for row in session.execute(text("SHOW GRANTS FOR CURRENT_USER"))]
    except SQLAlchemyError:
        return False

    # Accept only the owned table grants, or their exact non-production test
    # schema equivalent.  The latter is used by the isolated staging runtime
    # account; it grants no capability outside ``eoat_atlas_test``.
    required = {
        "ADMIN_DANGER_STEP_UPS": {"INSERT"},
        "ADMIN_OPERATIONS": {"INSERT", "UPDATE"},
        "ADMIN_OPERATION_FIXTURES": {"INSERT", "DELETE"},
    }
    granted = {table: set() for table in required}
    for grant in grants:
        privilege_clause, _, target_clause = grant.partition(" ON ")
        if not target_clause:
            continue
        permissions = {part.strip() for part in privilege_clause.removeprefix("GRANT ").split(",")}
        if "ALL PRIVILEGES" in permissions:
            permissions = {"INSERT", "UPDATE", "DELETE"}
        if "`EOAT_ATLAS_TEST`.*" in target_clause:
            for table in required:
                granted[table].update(permissions)
        for table in required:
            if f"`EOAT_ATLAS_TEST`.`{table}`" in target_clause:
                granted[table].update(permissions)
    return all(required[table].issubset(granted[table]) for table in required)


def require_operation_ledger(session: Session) -> None:
    if not operation_ledger_writable(session):
        raise APIError(
            503,
            "OPERATION_LEDGER_UNAVAILABLE",
            "The runtime account cannot persist the required Phase 4 operation evidence.",
            retryable=False,
        )


def _result(
    check_id: str,
    subsystem: str,
    state: str,
    detail: str,
    hint: str,
    *,
    source: str = "server",
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "subsystem": subsystem,
        "state": state,
        "severity": "HIGH" if state in {"FAILED", "UNAVAILABLE"} else "INFO",
        "read_only": True,
        "timeout_seconds": 5,
        "safe_detail": detail,
        "remediation_hint": hint,
        "source": source,
        "observed_at_utc": _utcnow().isoformat(),
        "request_id": request_id,
    }


def diagnostic_checks(session: Session, *, request_id: str | None = None) -> list[dict[str, Any]]:
    """Run independent, non-mutating checks.  A single failure is isolated."""
    values: list[dict[str, str]] = []
    values.append(_result("api.self", "api", "HEALTHY", f"API {API_VERSION} is responding.", "Inspect the request ID if a later call fails.", request_id=request_id))
    try:
        session.execute(text("SELECT 1"))
        values.append(_result("database.connectivity", "database", "HEALTHY", "Database connectivity succeeded.", "No action required.", request_id=request_id))
    except SQLAlchemyError:
        values.append(_result("database.connectivity", "database", "UNAVAILABLE", "Database connectivity could not be verified.", "Check the approved database service and tunnel.", request_id=request_id))
    try:
        revision = AtlasService(session).schema_revision()
        state = "HEALTHY" if revision == EXPECTED_SCHEMA_REVISION else "FAILED"
        values.append(_result("schema.revision", "schema", state, f"Schema revision is {revision or 'unknown'}.", "Apply the approved migration or recover the expected schema.", request_id=request_id))
    except SQLAlchemyError:
        values.append(_result("schema.revision", "schema", "UNKNOWN", "Schema revision could not be read.", "Resolve database connectivity before a high-risk operation.", request_id=request_id))
    try:
        session.scalar(select(db.AuditEvent.id).limit(1))
        values.append(_result("audit.read", "audit", "HEALTHY", "The append-only audit ledger is readable.", "No action required.", request_id=request_id))
    except SQLAlchemyError:
        values.append(_result("audit.read", "audit", "FAILED", "Audit ledger access could not be verified.", "Do not run governed operations until audit health is restored.", request_id=request_id))
    try:
        session.scalar(select(db.AdminOperation.id).limit(1))
        state = "HEALTHY" if operation_ledger_writable(session) else "FAILED"
        detail = "Durable operation evidence is readable and writable." if state == "HEALTHY" else "Durable operation evidence is readable, but its required writes are not authorized."
        hint = "No action required." if state == "HEALTHY" else "Restore the approved least-privilege runtime access before operations are enabled."
        values.append(_result("operations.ledger", "operations", state, detail, hint, request_id=request_id))
    except SQLAlchemyError:
        values.append(_result("operations.ledger", "operations", "FAILED", "Durable operation evidence is not accessible to this runtime.", "Restore the approved least-privilege runtime access before operations are enabled.", request_id=request_id))
    provider = corporate_provider_state()
    values.append(
        _result(
            "identity.provider",
            "authentication",
            provider.state,
            provider.detail,
            "Supply the IT-approved provider decision and protected configuration; local rehearsal is never a production fallback.",
            request_id=request_id,
        )
    )
    writes_enabled = os.getenv("EOAT_API_WRITES_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
    values.append(_result("write.gate", "write_gate", "HEALTHY" if writes_enabled else "DEGRADED", "Governed writes are enabled for the local rehearsal." if writes_enabled else "Governed writes are disabled by the current environment gate.", "Enable writes only through the approved local rehearsal procedure.", request_id=request_id))
    values.append(_result("release.metadata", "release", "HEALTHY", f"API version {API_VERSION}; expected schema {EXPECTED_SCHEMA_REVISION}.", "No action required.", request_id=request_id))
    root = os.getenv("EOAT_DOCUMENT_ROOT", "").strip()
    if not root:
        values.append(_result("storage.document-root", "storage", "UNKNOWN", "No approved document root is configured for this process.", "Configure an approved storage probe; do not expose a filesystem browser.", request_id=request_id))
    elif os.path.isdir(root):
        values.append(_result("storage.document-root", "storage", "HEALTHY", "The configured document root is accessible.", "No action required.", request_id=request_id))
    else:
        values.append(_result("storage.document-root", "storage", "FAILED", "The configured document root is not accessible.", "Check the approved storage service configuration.", request_id=request_id))
    return values


def diagnostic_summary(session: Session, *, request_id: str | None = None) -> dict[str, Any]:
    checks = diagnostic_checks(session, request_id=request_id)
    by_subsystem = {item["subsystem"]: item for item in checks}
    return {"observation_time_utc": _utcnow(), "checks": checks, "by_subsystem": by_subsystem}


def _finding(category: str, severity: str, entity_type: str, entity_id: int | str, identifier: str, explanation: str, evidence: dict[str, Any], next_step: str) -> dict[str, Any]:
    digest = hashlib.sha256(f"{category}|{entity_type}|{entity_id}|{json.dumps(evidence, sort_keys=True, default=str)}".encode()).hexdigest()[:24]
    return {"finding_id": f"int-{digest}", "category": category, "severity": severity, "entity_type": entity_type, "entity_id": str(entity_id), "human_identifier": identifier, "explanation": explanation, "evidence": redact(evidence), "detected_at_utc": _utcnow().isoformat(), "repair_available": False, "recommended_next_step": next_step}


def integrity_findings(session: Session) -> list[dict[str, Any]]:
    """Inspect only supported domain invariants; do not fabricate data errors."""
    findings: list[dict[str, Any]] = []
    entity_models = {"eoat": db.EOAT, "machine": db.Machine, "tool": db.Tool}
    for link in session.scalars(select(db.DocumentLink)).all():
        model = entity_models.get((link.entity_type or "").casefold())
        if model is not None and session.get(model, link.entity_id) is None:
            findings.append(_finding("ORPHAN_DOCUMENT_LINK", "ERROR", "Document", link.document_id, str(link.document_id), "Document metadata references an entity that no longer exists.", {"link_id": link.id, "entity_type": link.entity_type, "entity_id": link.entity_id}, "Review the link through a governed corrective workflow."))
    for model, label, left, right in (
        (db.EOATMachineCompatibility, "EOAT_MACHINE", db.EOATMachineCompatibility.eoat_id, db.EOATMachineCompatibility.machine_id),
        (db.EOATToolCompatibility, "EOAT_TOOL", db.EOATToolCompatibility.eoat_id, db.EOATToolCompatibility.tool_id),
        (db.ToolMachineCompatibility, "TOOL_MACHINE", db.ToolMachineCompatibility.tool_id, db.ToolMachineCompatibility.machine_id),
    ):
        duplicates = session.execute(select(left, right, func.count(model.id)).where(model.is_active.is_(True), model.effective_to.is_(None)).group_by(left, right).having(func.count(model.id) > 1)).all()
        for left_id, right_id, count in duplicates:
            findings.append(_finding("DUPLICATE_ACTIVE_RELATIONSHIP", "WARNING", "Relationship", f"{label}:{left_id}:{right_id}", label, "More than one active open-ended relationship exists for the same pair.", {"left_id": left_id, "right_id": right_id, "count": count}, "Review the relationship records; automatic repair is intentionally unavailable."))
    for model, label in ((db.EOAT, "EOAT"), (db.Machine, "Machine"), (db.Tool, "Tool")):
        archived = session.scalars(select(model).where(model.is_active.is_(False))).all()
        for row in archived:
            identifier = getattr(row, "business_identifier", None) or getattr(row, "machine_number", None) or str(row.id)
            findings.append(_finding("ARCHIVED_ENTITY", "INFO", label, row.id, str(identifier), "The entity is archived; related assignment review remains a governed human task.", {"is_active": False}, "Use the existing archive/restore workflow if the lifecycle state is wrong."))
    return findings


def run_integrity_scan(session: Session, actor: ActorContext) -> dict[str, Any]:
    operation = db.AdminOperation(operation_id=str(uuid4()), operation_type="integrity.scan", risk_class="LOW", status="RUNNING", actor_user_id=actor.user_id, correlation_id=actor.request_id, target_json={"scope": "current_schema"}, started_at=_utcnow())
    session.add(operation)
    session.flush()
    findings = integrity_findings(session)
    operation.status = "COMPLETED"
    operation.completed_at = _utcnow()
    operation.result_json = {"finding_count": len(findings), "findings": findings}
    event_id = AuditEventWriter().write_event(session, actor, entity_type="System", entity_id=operation.id, entity_display_id=operation.operation_id, operation="admin.integrity.scan", action=AuditAction.INTEGRITY_SCAN, result=AuditResult.SUCCESS, metadata={"finding_count": len(findings), "operation_id": operation.operation_id})
    return {"operation_id": operation.operation_id, "status": operation.status, "finding_count": len(findings), "findings": findings, "audit_event_id": event_id, "correlation_id": actor.request_id}


def operation_view(row: db.AdminOperation) -> dict[str, Any]:
    return {"operation_id": row.operation_id, "operation_type": row.operation_type, "risk_class": row.risk_class, "status": row.status, "target": redact(row.target_json or {}), "correlation_id": row.correlation_id, "result": redact(row.result_json or {}), "error_code": row.error_code, "created_at": row.created_at, "started_at": row.started_at, "completed_at": row.completed_at}


def latest_integrity_summary(session: Session) -> dict[str, Any]:
    """Return a bounded prior-scan summary; never run an expensive scan on page load."""
    try:
        latest = session.scalar(
            select(db.AdminOperation)
            .where(db.AdminOperation.operation_type == "integrity.scan")
            .order_by(db.AdminOperation.created_at.desc())
        )
    except SQLAlchemyError:
        return {"status": "UNAVAILABLE", "finding_count": None, "by_severity": {}, "by_entity_type": {}, "completed_at": None}
    if latest is None:
        return {"status": "NOT_RUN", "finding_count": 0, "by_severity": {}, "by_entity_type": {}, "completed_at": None}
    findings = list((latest.result_json or {}).get("findings") or [])
    by_severity: dict[str, int] = {}
    by_entity_type: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity", "UNKNOWN"))
        entity_type = str(finding.get("entity_type", "Unknown"))
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_entity_type[entity_type] = by_entity_type.get(entity_type, 0) + 1
    return {"status": latest.status, "operation_id": latest.operation_id, "finding_count": len(findings), "by_severity": by_severity, "by_entity_type": by_entity_type, "completed_at": latest.completed_at}


def _safe_event(row: db.AuditEvent) -> dict[str, Any]:
    return redact({"event_id": row.event_id, "occurred_at_utc": row.occurred_at_utc.isoformat(), "actor": {"type": row.actor_type, "id": row.actor_id, "display_name": row.actor_display_name, "directory_name": row.actor_directory_name}, "action": row.action, "category": row.action_category, "entity": {"type": row.entity_type, "id": row.entity_id, "display_id": row.entity_display_id}, "changed_fields": row.changed_fields_json or [], "before": row.before_state_json, "after": row.after_state_json, "reason_or_note": row.reason_or_note, "source": row.source_client, "request_id": row.request_id, "correlation_id": row.correlation_id, "operation": row.operation, "result": row.result, "metadata": row.metadata_json, "schema_version": row.schema_version})


def audit_export(session: Session, actor: ActorContext, filters: dict[str, Any], export_format: str) -> tuple[bytes, str, dict[str, Any]]:
    if export_format not in {"csv", "json"}:
        raise APIError(422, "EXPORT_FORMAT_INVALID", "Export format must be csv or json.")
    rows, total = AuditEventRepository(session).list(page=1, page_size=250, **filters)
    if total > 250:
        raise APIError(422, "EXPORT_SCOPE_TOO_LARGE", "Refine the authorized filter scope before exporting more than 250 events.")
    export_id = str(uuid4())
    events = [_safe_event(row) for row in rows]
    manifest = {"export_id": export_id, "generated_at_utc": _utcnow().isoformat(), "actor": actor.identity, "format": export_format, "applied_filters": redact(filters), "event_count": len(events), "schema_version": 1, "redaction_policy_version": 1}
    if export_format == "json":
        payload = json.dumps({"manifest": manifest, "events": events}, default=str, sort_keys=True, indent=2).encode("utf-8")
        media_type = "application/json"
    else:
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=["event_id", "occurred_at_utc", "actor", "action", "category", "entity_type", "entity_id", "result", "request_id", "correlation_id", "operation"])
        writer.writeheader()
        for event in events:
            writer.writerow({"event_id": event["event_id"], "occurred_at_utc": event["occurred_at_utc"], "actor": event["actor"].get("directory_name") or event["actor"].get("display_name"), "action": event["action"], "category": event["category"], "entity_type": event["entity"]["type"], "entity_id": event["entity"]["id"], "result": event["result"], "request_id": event.get("request_id"), "correlation_id": event.get("correlation_id"), "operation": event.get("operation")})
        payload = stream.getvalue().encode("utf-8")
        media_type = "text/csv"
    manifest["sha256"] = hashlib.sha256(payload).hexdigest()
    AuditEventWriter().write_event(session, actor, entity_type="System", entity_id=export_id, entity_display_id=export_id, operation="admin.audit.export", action=AuditAction.AUDIT_EXPORT, result=AuditResult.SUCCESS, metadata=manifest)
    return payload, media_type, manifest


def support_bundle(session: Session, actor: ActorContext, sections: list[str], request_id: str | None) -> tuple[bytes, dict[str, Any]]:
    allowed = {"health", "integrity", "release", "request"}
    selected = sorted(set(sections))
    if not selected or not set(selected).issubset(allowed):
        raise APIError(422, "SUPPORT_SECTION_INVALID", "Support evidence sections must be selected from the controlled registry.")
    body: dict[str, Any] = {"bundle_id": str(uuid4()), "generated_at_utc": _utcnow().isoformat(), "sections": selected, "redaction_policy_version": 1}
    if "health" in selected:
        body["health"] = diagnostic_summary(session)
    if "integrity" in selected:
        latest = session.scalar(select(db.AdminOperation).where(db.AdminOperation.operation_type == "integrity.scan").order_by(db.AdminOperation.created_at.desc()))
        body["integrity"] = operation_view(latest) if latest else {"status": "NOT_RUN"}
    if "release" in selected:
        body["release"] = {"api_version": API_VERSION, "schema_revision": AtlasService(session).schema_revision(), "environment": os.getenv("EOAT_API_ENVIRONMENT", "development")}
    if "request" in selected and request_id:
        row = session.scalar(select(db.AuditEvent).where(db.AuditEvent.request_id == request_id).order_by(db.AuditEvent.id.desc()))
        body["request"] = _safe_event(row) if row else {"request_id": request_id, "status": "NOT_FOUND"}
    safe = redact(body)
    payload = json.dumps(safe, default=str, sort_keys=True, indent=2).encode("utf-8")
    manifest = {"bundle_id": body["bundle_id"], "generated_at_utc": body["generated_at_utc"], "actor": actor.identity, "requested_sections": selected, "files_included": ["support-evidence.json"], "redaction_status": "APPLIED", "sha256": hashlib.sha256(payload).hexdigest()}
    AuditEventWriter().write_event(session, actor, entity_type="System", entity_id=manifest["bundle_id"], entity_display_id=manifest["bundle_id"], operation="admin.support.export", action=AuditAction.ADMIN_EXPORT, result=AuditResult.SUCCESS, metadata=manifest)
    return payload, manifest


def _fixture_target(session: Session, namespace: str) -> tuple[int, str]:
    count = session.scalar(select(func.count(db.AdminOperationFixture.id)).where(db.AdminOperationFixture.fixture_namespace == namespace)) or 0
    fingerprint = hashlib.sha256(f"{namespace}:{count}".encode()).hexdigest()
    return count, fingerprint


def _recovery_point_state() -> tuple[str, str]:
    """Validate only local test-recovery metadata; never reveal its path."""
    path = os.getenv("EOAT_PHASE4_TEST_RECOVERY_POINT", "").strip()
    if not path:
        return "FAIL", "No validated Phase 4 test recovery point is configured."
    if not os.path.isfile(path):
        return "FAIL", "The configured test recovery point is unavailable."
    configured_hash = os.getenv("EOAT_PHASE4_TEST_RECOVERY_POINT_SHA256", "").strip().casefold()
    configured_revision = os.getenv("EOAT_PHASE4_TEST_RECOVERY_POINT_REVISION", "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", configured_hash):
        return "FAIL", "The test recovery point has no approved integrity metadata."
    if configured_revision != EXPECTED_SCHEMA_REVISION:
        return "FAIL", "The test recovery point does not declare the current approved schema revision."
    try:
        age = _utcnow().timestamp() - os.path.getmtime(path)
        if age > TEST_RECOVERY_MAX_AGE_SECONDS:
            return "FAIL", "The configured test recovery point is older than the rehearsal freshness limit."
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), configured_hash):
            return "FAIL", "The configured test recovery point did not match its approved integrity metadata."
    except OSError:
        return "FAIL", "The test recovery point could not be inspected safely."
    return "PASS", "A recent, integrity-verified Phase 4 test recovery point is available."


def _preconditions(session: Session, actor: ActorContext, namespace: str, *, request: Request | None = None, require_step_up: bool = False) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    checks.append({"name": "capability", "state": "PASS" if actor.permits("admin.danger.execute") else "FAIL", "detail": "Danger capability was evaluated server-side."})
    environment = os.getenv("EOAT_API_ENVIRONMENT", "development").strip().casefold()
    try:
        selected = str(session.execute(text("SELECT DATABASE()")).scalar() or "")
    except SQLAlchemyError:
        selected = ""
    environment_ok = environment in {"development", "staging_local", "staging"} and selected == "eoat_atlas_test"
    checks.append({"name": "environment", "state": "PASS" if environment_ok else "FAIL", "detail": "Test-only target verified." if environment_ok else "Operation requires eoat_atlas_test in an approved test environment."})
    recovery_state, recovery_detail = _recovery_point_state()
    checks.append({"name": "recovery_point", "state": recovery_state, "detail": recovery_detail})
    diagnostics = {check["subsystem"]: check for check in diagnostic_checks(session)}
    for subsystem in ("database", "audit", "schema", "operations"):
        check = diagnostics.get(subsystem)
        state = "PASS" if check and check["state"] == "HEALTHY" else "FAIL"
        checks.append({"name": f"{subsystem}_health", "state": state, "detail": check["safe_detail"] if check else "Status is unknown."})
    running = session.scalar(select(db.AdminOperation.id).where(db.AdminOperation.lock_key == "phase4.fixture-recovery", db.AdminOperation.status == "RUNNING"))
    checks.append({"name": "operation_lock", "state": "FAIL" if running else "PASS", "detail": "No conflicting fixture recovery is running." if not running else "Another fixture recovery operation is running."})
    writes_enabled = os.getenv("EOAT_API_WRITES_ENABLED", "false").strip().casefold() in {"1", "true", "yes", "on"}
    checks.append({"name": "write_gate", "state": "PASS" if writes_enabled else "FAIL", "detail": "The local rehearsal write gate is enabled." if writes_enabled else "The local rehearsal write gate is disabled."})
    if require_step_up and request is not None:
        try:
            require_active_danger_step_up(request, session, actor, operation_type=OP_FIXTURE_RECOVERY, risk_class=RISK_HIGH)
            checks.append({"name": "fresh_step_up", "state": "PASS", "detail": "A scoped development/test step-up proof is current."})
        except APIError as exc:
            checks.append({"name": "fresh_step_up", "state": "FAIL", "detail": exc.message})
    else:
        checks.append({"name": "fresh_step_up", "state": "WARNING", "detail": "A current step-up proof is required before commit."})
    count, _ = _fixture_target(session, namespace)
    checks.append({"name": "target", "state": "PASS" if count else "FAIL", "detail": f"{count} bounded Phase 4 fixture record(s) match the namespace."})
    return checks


def danger_preview(session: Session, actor: ActorContext, namespace: str) -> dict[str, Any]:
    if not FIXTURE_NAMESPACE.fullmatch(namespace):
        raise APIError(422, "FIXTURE_NAMESPACE_INVALID", "The test fixture namespace is not valid.")
    count, fingerprint = _fixture_target(session, namespace)
    checks = _preconditions(session, actor, namespace)
    reference = str(uuid4())
    operation = db.AdminOperation(operation_id=str(uuid4()), operation_type=OP_FIXTURE_RECOVERY, risk_class=RISK_HIGH, status="PREVIEWED", actor_user_id=actor.user_id, target_json={"fixture_namespace": namespace, "target_count": count}, preview_reference=reference, preview_expires_at=_utcnow() + PREVIEW_TTL, target_fingerprint=fingerprint, lock_key="phase4.fixture-recovery", correlation_id=actor.request_id, result_json={"preconditions": checks})
    session.add(operation)
    session.flush()
    AuditEventWriter().write_event(session, actor, entity_type="System", entity_id=operation.id, entity_display_id=operation.operation_id, operation="admin.danger.fixture-recovery.preview", action=AuditAction.DANGER_ATTEMPT, result=AuditResult.SUCCESS, metadata={"operation_id": operation.operation_id, "preview_reference": reference, "target_count": count, "preconditions": checks})
    return {"operation_id": operation.operation_id, "preview_reference": reference, "expires_at": operation.preview_expires_at, "target": operation.target_json, "consequence": "Only non-authoritative Phase 4 test fixture rows in this namespace will be removed.", "recovery": "Restore the configured eoat_atlas_test recovery point through the approved operator procedure if needed.", "typed_confirmation": f"PURGE PHASE4 TEST FIXTURES {namespace}", "preconditions": checks}


def danger_commit(session: Session, request: Request, actor: ActorContext, preview_reference: str, confirmation: str, reason: str) -> dict[str, Any]:
    operation = session.scalar(select(db.AdminOperation).where(db.AdminOperation.preview_reference == preview_reference).with_for_update())
    if operation is None or operation.operation_type != OP_FIXTURE_RECOVERY:
        raise APIError(404, "DANGER_PREVIEW_NOT_FOUND", "The Danger Zone preview is unavailable.")
    namespace = str((operation.target_json or {}).get("fixture_namespace", ""))
    denied: str | None = None
    if operation.actor_user_id != actor.user_id or _utc(operation.preview_expires_at) is None or _utc(operation.preview_expires_at) <= _utcnow():
        denied = "Preview expired or belongs to another session actor."
    expected = f"PURGE PHASE4 TEST FIXTURES {namespace}"
    if confirmation != expected:
        denied = "Typed confirmation does not exactly match the test-only target."
    count, fingerprint = _fixture_target(session, namespace)
    if fingerprint != operation.target_fingerprint:
        denied = "Target state changed; obtain a new preview."
    checks = _preconditions(session, actor, namespace, request=request, require_step_up=True)
    if any(item["state"] != "PASS" for item in checks):
        denied = denied or "A required server-side precondition failed."
    if denied:
        operation.status = "FAILED"
        operation.completed_at = _utcnow()
        operation.error_code = "DANGER_OPERATION_DENIED"
        operation.result_json = {"reason": denied, "preconditions": checks}
        event_id = AuditEventWriter().write_event(session, actor, entity_type="System", entity_id=operation.id, entity_display_id=operation.operation_id, operation="admin.danger.fixture-recovery.commit", action=AuditAction.DANGER_ATTEMPT, result=AuditResult.DENIED, reason=reason, metadata={"reason": denied, "preconditions": checks, "preview_reference": preview_reference})
        return {"operation_id": operation.operation_id, "status": "DENIED", "error_code": "DANGER_OPERATION_DENIED", "message": denied, "audit_event_id": event_id, "preconditions": checks}
    operation.status = "RUNNING"
    operation.started_at = _utcnow()
    writer = AuditEventWriter()
    writer.write_event(session, actor, entity_type="System", entity_id=operation.id, entity_display_id=operation.operation_id, operation="admin.danger.fixture-recovery.confirm", action=AuditAction.DANGER_CONFIRMED, result=AuditResult.SUCCESS, reason=reason, metadata={"preview_reference": preview_reference, "target_count": count})
    writer.write_event(session, actor, entity_type="System", entity_id=operation.id, entity_display_id=operation.operation_id, operation="admin.danger.fixture-recovery.start", action=AuditAction.DANGER_STARTED, result=AuditResult.SUCCESS, reason=reason, metadata={"target_count": count})
    session.query(db.AdminOperationFixture).filter(db.AdminOperationFixture.fixture_namespace == namespace).delete(synchronize_session=False)
    operation.status = "COMPLETED"
    operation.completed_at = _utcnow()
    operation.result_json = {"removed_count": count, "fixture_namespace": namespace, "recovery": "validated test recovery point remains available"}
    event_id = writer.write_event(session, actor, entity_type="System", entity_id=operation.id, entity_display_id=operation.operation_id, operation="admin.danger.fixture-recovery.complete", action=AuditAction.DANGER_SUCCEEDED, result=AuditResult.SUCCESS, reason=reason, metadata=operation.result_json)
    return {"operation_id": operation.operation_id, "status": operation.status, "removed_count": count, "audit_event_id": event_id, "correlation_id": actor.request_id}
