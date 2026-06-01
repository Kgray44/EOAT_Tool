from __future__ import annotations

from core.audit.smart_rules import apply_smart_default_rules, default_smart_default_rules


def test_part_present_sets_reed_switch_when_empty():
    result = apply_smart_default_rules(
        {"Part-Present Detection Present?": "Yes", "Sensor Type": ""},
        default_smart_default_rules(),
    )

    assert result.values["Sensor Type"] == "Reed Switch"
    assert "part_present_sensor_type" in result.applied_rules


def test_part_present_sets_smc_when_empty():
    result = apply_smart_default_rules(
        {"Part-Present Detection Present?": "Yes", "Sensor Brand/Model": ""},
        default_smart_default_rules(),
    )

    assert result.values["Sensor Brand/Model"] == "SMC"
    assert "part_present_sensor_model" in result.applied_rules


def test_custom_sensor_not_overwritten():
    result = apply_smart_default_rules(
        {"Part-Present Detection Present?": "Yes", "Sensor Type": "Keyence"},
        default_smart_default_rules(),
    )

    assert result.values["Sensor Type"] == "Keyence"
    assert "part_present_sensor_type" in result.skipped_rules


def test_condition_contains_applies_changeover_default():
    result = apply_smart_default_rules(
        {"Connection Type": "ATI quick changer", "Changeover Difficulty": ""},
        default_smart_default_rules(),
    )

    assert result.values["Changeover Difficulty"] == "Low"


def test_hidden_smart_rule_target_not_defaulted():
    result = apply_smart_default_rules(
        {"Sensors Present?": "No", "Known Issues": "Part drop", "Sensor Type": ""},
        [
            {
                "id": "hidden_sensor",
                "when_field": "Known Issues",
                "operator": "contains",
                "when_value": "drop",
                "set_field": "Sensor Type",
                "set_value": "Reed Switch",
            }
        ],
    )

    assert result.values["Sensor Type"] == ""
    assert "hidden_sensor" in result.skipped_rules


def test_conflicting_smart_rules_warn_even_when_target_has_custom_value():
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

    result = apply_smart_default_rules({"Connection Type": "ATI", "Changeover Difficulty": "Custom"}, rules)

    assert result.values["Changeover Difficulty"] == "Custom"
    assert result.warnings
