"""Deterministic, synthetic audit evidence for Phase 2 acceptance tests.

This fixture deliberately contains no directory, machine, or production data.
It represents the audit situations the read-only Administrator experience must
be able to investigate, including redaction and tied timestamps.
"""

from __future__ import annotations

from copy import deepcopy


_BASE = {
    "actor": {"type": "user", "id": "user-17", "display_name": "Test Administrator", "directory_name": "test.admin"},
    "entity": {"type": "EOAT", "id": "eoat-54", "display_id": "TEST-EOAT-0054"},
    "changed_fields": ["location"],
    "before": {"location": "Synthetic storage"},
    "after": {"location": "Synthetic cell 27"},
    "reason_or_note": "Synthetic acceptance evidence only",
    "source_client": "web",
    "request_id": "request-phase2-test",
    "correlation_id": "correlation-phase2-test",
    "transaction_id": "transaction-phase2-test",
    "operation": "PATCH /api/v1/eoats/eoat-54",
    "result": "SUCCESS",
    "schema_version": 1,
}


def _event(event_id: str, timestamp: str, action: str, category: str, **overrides):
    value = deepcopy(_BASE)
    value.update({"event_id": event_id, "occurred_at_utc": timestamp, "action": action, "action_category": category})
    value.update(overrides)
    return value


AUDIT_ACCEPTANCE_EVENTS = [
    _event("fixture-001", "2026-08-11T18:00:00Z", "UPDATE", "BUSINESS_DATA"),
    _event("fixture-002", "2026-08-11T17:59:00Z", "LOCATION_CHANGE", "LOCATION_STATE"),
    _event("fixture-003", "2026-08-11T17:58:00Z", "LINK", "RELATIONSHIPS", entity={"type": "Machine", "id": "machine-27", "display_id": "TEST-MACHINE-27"}),
    _event("fixture-004", "2026-08-11T17:57:00Z", "UPLOAD", "DOCUMENTS_MEDIA", entity={"type": "Document", "id": "document-11", "display_id": "TEST-DOC-11"}),
    _event("fixture-005", "2026-08-11T17:56:00Z", "PM_COMPLETE", "MAINTENANCE_INSPECTION"),
    _event("fixture-006", "2026-08-11T17:55:00Z", "LOGIN_SUCCESS", "AUTHENTICATION", entity={"type": "Identity", "id": "user-17", "display_id": "test.admin"}),
    _event("fixture-007", "2026-08-11T17:54:00Z", "LOGIN_FAILURE", "AUTHENTICATION", result="FAILURE"),
    _event("fixture-008", "2026-08-11T17:53:00Z", "ACCESS_DENIED", "AUTHORIZATION", result="DENIED"),
    _event("fixture-009", "2026-08-11T17:52:00Z", "SCHEMA_MIGRATED", "SYSTEM_OPERATIONS", actor={"type": "system", "id": "migration", "display_name": "Schema runner", "directory_name": None}),
    _event("fixture-010", "2026-08-11T17:51:00Z", "UPDATE", "BUSINESS_DATA", after={"serial": None, "password": {"_audit_value": "REDACTED"}}),
    _event("fixture-tied-a", "2026-08-11T17:50:00Z", "STATUS_CHANGE", "LOCATION_STATE"),
    _event("fixture-tied-z", "2026-08-11T17:50:00Z", "STATUS_CHANGE", "LOCATION_STATE"),
]
