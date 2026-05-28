from __future__ import annotations

from core.compatibility_matrix import STATE_AUDITED, build_compatibility_matrix


def test_compatibility_matrix_builds_tool_machine_rows(usability_fake_project):
    summary = build_compatibility_matrix(usability_fake_project)

    assert summary.metrics["tools"] >= 1
    assert summary.metrics["machines"] >= 1
    assert summary.rows
    assert any(STATE_AUDITED in row.machine_states.values() for row in summary.rows)
    assert summary.standardization_opportunities

