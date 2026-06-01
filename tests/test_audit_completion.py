from __future__ import annotations

from core.audit.defaults import UNKNOWN_NOT_CHECKED
from core.audit_completion import CompletionPolicy, evaluate_completion, next_completion_actions
from core.audit_constants import (
    IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_FIELD,
    MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD,
    MANUAL_COMPLETION_OVERRIDE_USER_FIELD,
)


def _entry(**overrides):
    data = {
        "Audit ID": "AUD-COMP-001",
        "Audit Date": "2026-05-28",
        "Auditor": "Synthetic Auditor",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "12",
        "Tool #": "T-001",
        "Robot Type": "Wittmann R8",
        "EOAT Type": "Vacuum",
        "EOAT Moves": "Part",
        "# of Cups": "4",
        "Cup Type/Material": "Silicone",
        "Vacuum Generator Type": "Venturi",
        "Sensors Present?": "No",
        "Electrical/Wiring Present?": "No",
        "Quick Disconnects Present?": "No",
        "Tubing Condition": "OK",
        "Cable Management Condition": "OK",
        "Known Issues": "None",
        "Photos Taken?": "Yes",
        "Status": "Complete",
        "Priority": "Medium",
        "Follow-Up Needed": "No",
    }
    data.update(overrides)
    return data


def test_completion_policy_reports_missing_actionable_fields():
    result = evaluate_completion(
        _entry(**{"Press/Machine #": "", "Tool #": "", "Sensors Present?": "Yes", "Sensor Type": UNKNOWN_NOT_CHECKED})
    )

    assert result.can_finish is False
    assert result.percent_complete < 100
    assert "Press/Machine #" in result.missing_required_fields
    assert "Sensor Type" in result.guided_fields


def test_completion_policy_accepts_manual_override_truthfully():
    result = evaluate_completion(
        _entry(
            **{
                "Press/Machine #": "",
                "Tool #": "",
                MANUAL_COMPLETION_OVERRIDE_FIELD: "Yes",
                MANUAL_COMPLETION_OVERRIDE_TIMESTAMP_FIELD: "2026-05-28T20:00:00+00:00",
                MANUAL_COMPLETION_OVERRIDE_USER_FIELD: "Synthetic Auditor",
                IGNORED_EMPTY_FIELDS_AT_OVERRIDE_FIELD: "Press/Machine #; Sensor Type",
            }
        )
    )

    assert result.can_finish is True
    assert result.percent_complete == 100
    assert result.manual_completion_override is True
    assert result.ignored_empty_fields_at_override == ("Press/Machine #", "Sensor Type")


def test_completion_policy_can_disable_manual_override():
    result = evaluate_completion(
        _entry(**{MANUAL_COMPLETION_OVERRIDE_FIELD: "Yes"}), CompletionPolicy(allow_manual_override=False)
    )

    assert result.manual_completion_override is False
    assert result.can_finish is False


def test_next_completion_actions_returns_ranked_fields():
    actions = next_completion_actions(
        _entry(**{"Press/Machine #": "", "Tool #": "", "Tubing Condition": UNKNOWN_NOT_CHECKED}), limit=2
    )

    assert actions[0]["field"] == "Press/Machine #"
    assert len(actions) == 2
    assert all(action["section"] for action in actions)
