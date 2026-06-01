from __future__ import annotations

from app.pages.audit_defaults_controller import AuditDefaultsController
from core.audit.smart_rules import apply_smart_default_rules, default_smart_default_rules
from core.config import UserConfig


def test_default_smart_rules_apply_part_present_and_connection_defaults():
    result = apply_smart_default_rules(
        {
            "Part-Present Detection Present?": "Yes",
            "Connection Type": "ATI QC",
            "Sensor Type": "",
            "Sensor Brand/Model": "",
            "Changeover Difficulty": "Unknown / Not Checked",
        },
        default_smart_default_rules(),
    )

    assert result.values["Sensor Type"] == "Reed Switch"
    assert result.values["Sensor Brand/Model"] == "SMC"
    assert result.values["Changeover Difficulty"] == "Low"
    assert "part_present_sensor_type" in result.applied_rules


def test_smart_rules_preserve_user_entered_values_by_default():
    result = apply_smart_default_rules(
        {"Part-Present Detection Present?": "Yes", "Sensor Type": "Custom Sensor"},
        default_smart_default_rules(),
    )

    assert result.values["Sensor Type"] == "Custom Sensor"
    assert "part_present_sensor_type" in result.skipped_rules


def test_smart_rules_report_conflicts_without_overwriting_first_value():
    rules = [
        {
            "id": "first",
            "when_field": "Connection Type",
            "operator": "contains",
            "when_value": "ATI",
            "set_field": "Changeover Difficulty",
            "set_value": "Low",
        },
        {
            "id": "second",
            "when_field": "Connection Type",
            "operator": "contains",
            "when_value": "ATI",
            "set_field": "Changeover Difficulty",
            "set_value": "High",
        },
    ]

    result = apply_smart_default_rules({"Connection Type": "ATI", "Changeover Difficulty": ""}, rules)

    assert result.values["Changeover Difficulty"] == "Low"
    assert result.warnings
    assert "second" in result.skipped_rules


def test_audit_defaults_controller_exposes_configured_smart_rules():
    config = UserConfig(
        smart_default_rules=[
            {
                "id": "custom_priority",
                "when_field": "Known Issues",
                "operator": "contains",
                "when_value": "drop",
                "set_field": "Priority",
                "set_value": "High",
            }
        ]
    )
    controller = AuditDefaultsController(config)

    result = controller.smart_defaults({"Known Issues": "Part drop", "Priority": ""})

    assert result.values["Priority"] == "High"
    assert result.applied_rules == ("custom_priority",)
