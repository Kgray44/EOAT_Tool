from __future__ import annotations

from core.project_data_service import build_machine_360_context


def test_machine_360_context_aggregates_fake_project(usability_fake_project):
    context = build_machine_360_context(usability_fake_project, "101")

    assert context.machine_number == "101"
    assert context.metrics["physical_audit_count"] >= 1
    assert context.physical_audits
    assert context.metrics["open_item_count"] >= 0
    assert context.recommended_actions
    assert context.guided_plans


def test_machine_360_context_handles_missing_machine(usability_fake_project):
    context = build_machine_360_context(usability_fake_project, "")

    assert context.warnings
    assert context.metrics["physical_audit_count"] == 0
    assert "Create or load" in " ".join(context.recommended_actions)
