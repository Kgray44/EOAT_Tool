from __future__ import annotations

from core.audit_constants import MANUAL_COMPLETION_OVERRIDE_FIELD
from core.guided_audit import build_guided_audit_plan


def _entry(**overrides):
    data = {
        "Audit ID": "AUD-GUIDED-001",
        "Audit Date": "2026-05-28",
        "Auditor": "Synthetic Auditor",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "12",
        "Robot Type": "Wittmann R8",
        "EOAT Type": "Vacuum",
        "Status": "In Progress",
        "Priority": "Medium",
        "Follow-Up Needed": "No",
        "Sensors Present?": "No",
        "Quick Disconnects Present?": "No",
        "Electrical/Wiring Present?": "No",
    }
    data.update(overrides)
    return data


def test_guided_audit_plan_prioritizes_required_identity_fields():
    plan = build_guided_audit_plan(_entry(**{"Press/Machine #": "", "Robot Type": ""}), limit=3)

    assert plan.can_finish is False
    assert plan.steps[0].field == "Press/Machine #"
    assert plan.steps[0].section == "Audit Header"
    assert "guided step" in plan.summary


def test_guided_audit_plan_respects_manual_override():
    plan = build_guided_audit_plan(_entry(**{"Press/Machine #": "", MANUAL_COMPLETION_OVERRIDE_FIELD: "Yes"}))

    assert plan.can_finish is True
    assert plan.percent_complete == 100
    assert plan.steps == ()
    assert "Manual completion override" in plan.summary
