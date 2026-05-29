from __future__ import annotations

from core.app_health import FAIL, PASS, UNKNOWN, WARNING, run_app_health_checks


def test_app_health_reports_runtime_project_and_workbook_checks(fake_project, fake_config):
    summary = run_app_health_checks(fake_project, config=fake_config, check_repo_safety=False, check_scheduled_tasks=False)
    by_key = {check.key: check for check in summary.checks}

    assert by_key["python_version"].status == PASS
    assert by_key["pyside_import"].status in {PASS, FAIL}
    assert by_key["project_root"].status == PASS
    assert by_key["master_workbook"].status == PASS
    assert by_key["workbook_lock"].status in {PASS, WARNING}
    assert by_key["repo_safety_audit"].status == UNKNOWN
    assert by_key["scheduled_daily"].status == UNKNOWN
    assert summary.counts[PASS] >= 3


def test_app_health_flags_missing_project_root(tmp_path, fake_config):
    missing = tmp_path / "missing_project"
    config = type(fake_config)(**{**fake_config.to_dict(), "project_root": str(missing)})

    summary = run_app_health_checks(missing, config=config)
    by_key = {check.key: check for check in summary.checks}

    assert by_key["project_root"].status == FAIL
    assert by_key["master_workbook"].status == FAIL
    assert summary.status in {FAIL, WARNING}
