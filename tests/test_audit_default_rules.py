from __future__ import annotations

from app.pages.audit_defaults_controller import AuditDefaultsController
from core.audit.default_rules import apply_audit_default_rules, preview_audit_default_rules
from core.config import UserConfig


def test_default_applies_to_empty_new_audit_field():
    result = apply_audit_default_rules(
        {},
        [{"id": "auditor_default", "enabled": True, "field": "Auditor", "value": "KG", "scope": "new_audit", "overwrite_policy": "empty_only"}],
    )

    assert result.values["Auditor"] == "KG"
    assert result.applied_rules == ("auditor_default",)


def test_default_does_not_overwrite_existing_value():
    result = apply_audit_default_rules(
        {"Auditor": "Existing"},
        [{"id": "auditor_default", "enabled": True, "field": "Auditor", "value": "KG", "scope": "new_audit", "overwrite_policy": "empty_only"}],
    )

    assert result.values["Auditor"] == "Existing"
    assert "auditor_default" in result.skipped_rules


def test_disabled_default_does_not_apply():
    result = apply_audit_default_rules(
        {},
        [{"id": "disabled", "enabled": False, "field": "Auditor", "value": "KG"}],
    )

    assert "Auditor" not in result.values
    assert "disabled" in result.skipped_rules


def test_hidden_field_not_defaulted():
    result = apply_audit_default_rules(
        {"Sensors Present?": "No", "Sensor Type": ""},
        [{"id": "sensor_default", "field": "Sensor Type", "value": "Reed Switch"}],
    )

    assert result.values["Sensor Type"] == ""
    assert result.preview_rows[0].reason == "Field is hidden or not applicable."


def test_condition_equals_works():
    result = apply_audit_default_rules(
        {"Follow-Up Needed": "Yes", "Priority": ""},
        [
            {
                "id": "follow_up_priority",
                "field": "Priority",
                "value": "High",
                "conditions": [{"field": "Follow-Up Needed", "operator": "equals", "value": "Yes"}],
            }
        ],
    )

    assert result.values["Priority"] == "High"


def test_condition_contains_works():
    result = apply_audit_default_rules(
        {"Known Issues": "Part drop at handoff", "Priority": ""},
        [
            {
                "id": "drop_priority",
                "field": "Priority",
                "value": "High",
                "conditions": [{"field": "Known Issues", "operator": "contains", "value": "drop"}],
            }
        ],
    )

    assert result.values["Priority"] == "High"


def test_preview_returns_expected_rows_without_changing_values():
    result = preview_audit_default_rules(
        {},
        [{"id": "plant_default", "field": "Plant/Area", "value": "Plant 4"}],
    )

    assert result.values == {}
    assert result.preview_rows[0].field == "Plant/Area"
    assert result.preview_rows[0].status == "would_apply"


def test_existing_matching_default_does_not_report_changed_field():
    result = apply_audit_default_rules(
        {"Plant/Area": "Plant 4"},
        [{"id": "plant_default", "field": "Plant/Area", "value": "Plant 4"}],
    )

    assert result.changed_fields == ()
    assert result.preview_rows[0].status == "already_set"


def test_controller_respects_explicit_disabled_default_rules():
    config = UserConfig(audit_default_rules=[{"id": "disabled_auditor", "enabled": False, "field": "Auditor", "value": "KG"}])
    controller = AuditDefaultsController(config)

    assert "Auditor" not in controller.initial_form_defaults()
