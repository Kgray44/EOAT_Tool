from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.versioning import get_release_info
from release_tools.versioning import Version

from .database import models as db
from .errors import APIError


def canonical_release_payload() -> dict[str, str]:
    return get_release_info().provenance()


def ensure_application_release(session: Session, payload: dict[str, Any] | None = None) -> db.ApplicationRelease:
    values = canonical_release_payload() if payload is None else {key: str(value or "") for key, value in payload.items()}
    application_version = str(Version.parse(values.get("application_version", "")))
    release_id = values.get("release_id", "")
    if release_id != f"eoat-atlas-{application_version}":
        raise APIError(422, "RELEASE_ID_MISMATCH", "release_id does not match application_version.")
    build_id = values.get("build_id", "").strip()
    if not build_id:
        raise APIError(422, "BUILD_ID_REQUIRED", "build_id is required for application release registration.")
    record = session.scalar(select(db.ApplicationRelease).where(db.ApplicationRelease.build_id == build_id))
    now = datetime.now(timezone.utc)
    if record is None:
        record = db.ApplicationRelease(
            application_version=application_version,
            release_id=release_id,
            build_id=build_id,
            commit_sha=values.get("commit_sha") or None,
            release_channel=values.get("release_channel") or "development",
            database_schema_revision=values.get("database_schema_revision") or None,
            api_contract_version=values.get("api_contract_version") or None,
            launcher_version=values.get("launcher_version") or None,
            installer_version=values.get("installer_version") or None,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(record)
        session.flush()
    else:
        if record.application_version != application_version or record.release_id != release_id:
            raise APIError(409, "BUILD_ID_REUSED", "build_id is already registered to a different release.")
        record.last_seen_at = now
    return record


def release_id_for_instance(session: Session, application_instance_id: int | None) -> int | None:
    if application_instance_id is None:
        return ensure_application_release(session).id
    release_id = session.scalar(
        select(db.ApplicationInstance.application_release_id).where(
            db.ApplicationInstance.id == application_instance_id
        )
    )
    return release_id or ensure_application_release(session).id


__all__ = ["canonical_release_payload", "ensure_application_release", "release_id_for_instance"]
