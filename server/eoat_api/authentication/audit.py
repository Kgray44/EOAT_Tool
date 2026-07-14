from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from ..database import models as db


def record_auth_event(
    session: Session,
    event_type: str,
    *,
    result: str,
    external_subject: str | None = None,
    user_id: int | None = None,
    application_instance_id: int | None = None,
    provider: str | None = None,
    request_id: str | None = None,
    operation: str | None = None,
    reason_code: str | None = None,
    client_version: str | None = None,
    source_ip: str | None = None,
    details: dict | None = None,
) -> None:
    session.add(
        db.AuthenticationAuditEvent(
            event_uuid=str(uuid4()),
            event_type=event_type,
            external_subject=external_subject,
            user_id=user_id,
            application_instance_id=application_instance_id,
            provider=provider,
            request_id=request_id,
            operation=operation,
            result=result,
            reason_code=reason_code,
            client_version=client_version,
            source_ip=source_ip,
            details_json=details,
        )
    )
