from __future__ import annotations

import json

import pytest
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from server.eoat_api.admin.diffing import material_diff
from server.eoat_api.admin.legacy import legacy_history_evidence
from server.eoat_api.admin.redaction import REDACTED_VALUE, redact
from server.eoat_api.admin.repository import AuditEventRepository
from server.eoat_api.admin.service import AuditEventWriter, execute_with_required_audit
from server.eoat_api.admin.taxonomy import (
    AuditAction,
    AuditActionCategory,
    action_for_legacy_operation,
    category_for_action,
)
from server.eoat_api.security import ActorContext


def actor(role: str = "ADMINISTRATOR") -> ActorContext:
    return ActorContext(
        user_id=42,
        identity="dev.admin",
        display_name="Development Administrator",
        role=role,
        request_id="req-admin-foundation",
        application_instance_id=None,
        client_version="test",
    )


def test_taxonomy_is_closed_and_legacy_operations_map_to_controlled_actions():
    assert action_for_legacy_operation("archive") is AuditAction.ARCHIVE
    assert action_for_legacy_operation("link_target") is AuditAction.LINK
    assert category_for_action(AuditAction.LINK) is AuditActionCategory.RELATIONSHIPS
    with pytest.raises(ValueError):
        AuditAction("invented endpoint action")


def test_material_diff_preserves_missing_null_empty_and_redacted_states():
    diff = material_diff(
        {"empty": "", "nullable": None, "password": "old-value", "removed": "present"},
        {"empty": "", "nullable": "set", "password": "new-value", "added": None},
    )
    assert diff.changed_fields == ["added", "nullable", "password", "removed"]
    assert "removed" not in diff.after
    assert "added" not in diff.before
    assert diff.after["added"] is None
    assert diff.before["password"] == REDACTED_VALUE
    assert diff.after["password"] == REDACTED_VALUE


def test_redaction_never_serializes_deliberately_submitted_secret_values():
    payload = {
        "password": "correct-horse-battery-staple",
        "nested": {"bearer_token": "eyJ.definitely-not-safe"},
        "records": [{"ldap_bind_password": "not-for-audit"}, {"api_token": "also-not-safe"}],
        "safe": "dev.admin",
    }
    serialized = json.dumps(redact(payload), sort_keys=True)
    for secret in ("correct-horse-battery-staple", "eyJ.definitely-not-safe", "not-for-audit", "also-not-safe"):
        assert secret not in serialized
    assert '"safe": "dev.admin"' in serialized


def test_writer_emits_a_structured_event_and_normalized_change_rows_without_secrets():
    class RecordingSession:
        def __init__(self):
            self.added = []
            self.flush_snapshots = []

        def add(self, value):
            self.added.append(value)

        def flush(self):
            self.flush_snapshots.append(len(self.added))

    session = RecordingSession()
    result = AuditEventWriter().write_change(
        session,
        actor(),
        entity_type="eoat",
        entity_id=54,
        entity_display_id="CL-EOAT-0054",
        operation="update",
        previous={"display_name": "Old", "api_token": "old-token"},
        current={"display_name": "New", "api_token": "new-token"},
    )
    event = session.added[0]
    assert result.event_id == event.event_id
    assert event.action == "UPDATE"
    assert event.action_category == "BUSINESS_DATA"
    assert event.changed_fields_json == ["api_token", "display_name"]
    assert "old-token" not in json.dumps(event.before_state_json)
    assert "new-token" not in json.dumps(event.after_state_json)
    assert len(session.added) == 3  # one event plus one normalized row per changed field
    # The parent must be flushed before child rows: MySQL enforces the
    # public-event-ID foreign key and cannot infer this dependency itself.
    assert session.flush_snapshots == [1, 3]


def test_administrator_permission_is_distinct_from_authenticated_viewer():
    assert actor("ADMINISTRATOR").permits("admin.audit.view")
    assert not actor("VIEWER").permits("admin.audit.view")


def test_global_audit_repository_exposes_no_ordinary_update_or_delete_path():
    assert not hasattr(AuditEventRepository, "update")
    assert not hasattr(AuditEventRepository, "delete")


def test_legacy_projection_preserves_unknown_evidence_as_unknown():
    legacy = type(
        "Legacy",
        (),
        {
            "id": 7,
            "event_uuid": "legacy-event-7",
            "occurred_at": None,
            "entity_type": "eoat",
            "entity_id": 54,
            "actor_user_id": None,
            "event_category": "ENGINEERING_CHANGES",
            "previous_values_json": None,
            "new_values_json": {"display_name": "Known resulting value"},
        },
    )()
    projected = legacy_history_evidence(legacy)
    assert projected.evidence_level == "legacy / limited-evidence"
    assert projected.occurred_at_utc is None
    assert projected.actor_id is None
    assert projected.before is None
    assert projected.after == {"display_name": "Known resulting value"}


class Base(DeclarativeBase):
    pass


class MutableBusinessRecord(Base):
    __tablename__ = "mutable_business_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[str] = mapped_column(String(64), nullable=False)


class MandatoryAuditRecord(Base):
    __tablename__ = "mandatory_audit_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    required_evidence: Mapped[str] = mapped_column(String(64), nullable=False)


def test_audit_persistence_failure_rolls_back_the_governed_business_mutation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            business = MutableBusinessRecord(value="before")
            session.add(business)
            session.flush()
            business_id = business.id

        with Session(engine) as session, session.begin():
            business = session.get(MutableBusinessRecord, business_id)
            assert business is not None
            with pytest.raises(IntegrityError):
                execute_with_required_audit(
                    session,
                    lambda: setattr(business, "value", "after"),
                    lambda: session.add(MandatoryAuditRecord(required_evidence=None)),
                )
            session.refresh(business)
            assert business.value == "before"
    finally:
        engine.dispose()
