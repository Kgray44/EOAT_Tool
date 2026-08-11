from tests.fixtures.admin_phase2 import AUDIT_ACCEPTANCE_EVENTS


def test_phase_two_audit_fixture_is_safe_deterministic_and_semantically_broad():
    actions = {event["action"] for event in AUDIT_ACCEPTANCE_EVENTS}
    categories = {event["action_category"] for event in AUDIT_ACCEPTANCE_EVENTS}
    results = {event["result"] for event in AUDIT_ACCEPTANCE_EVENTS}

    assert len({event["event_id"] for event in AUDIT_ACCEPTANCE_EVENTS}) == len(AUDIT_ACCEPTANCE_EVENTS)
    assert {"UPDATE", "LOCATION_CHANGE", "LINK", "UPLOAD", "PM_COMPLETE", "LOGIN_SUCCESS", "LOGIN_FAILURE", "ACCESS_DENIED"} <= actions
    assert {"BUSINESS_DATA", "RELATIONSHIPS", "DOCUMENTS_MEDIA", "AUTHENTICATION", "AUTHORIZATION", "SYSTEM_OPERATIONS"} <= categories
    assert {"SUCCESS", "FAILURE", "DENIED"} <= results
    assert any(event["actor"]["type"] == "system" for event in AUDIT_ACCEPTANCE_EVENTS)
    assert {"EOAT", "Machine", "Tool"} <= {event["entity"]["type"] for event in AUDIT_ACCEPTANCE_EVENTS}
    assert any(len(event["changed_fields"]) > 1 for event in AUDIT_ACCEPTANCE_EVENTS)
    assert any(event["after"].get("password") == {"_audit_value": "REDACTED"} for event in AUDIT_ACCEPTANCE_EVENTS)
    assert [event["event_id"] for event in AUDIT_ACCEPTANCE_EVENTS if event["occurred_at_utc"] == "2026-08-11T17:50:00Z"] == ["fixture-tied-a", "fixture-tied-z"]
