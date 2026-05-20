from __future__ import annotations

from core.system_audit import run_system_audit


def test_system_audit_runs_without_cli_help(fake_project):
    result = run_system_audit(fake_project, check_cli_help=False, log_activity=False)

    assert result.success is True
    assert result.output_reports
    assert result.metrics["registered_tools"] >= 20
