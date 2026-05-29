from __future__ import annotations

from scripts.ci_smoke_check import run_demo_project_checks, run_registry_checks, run_tool_registry_checks


def test_ci_smoke_registry_checks_pass(fake_project):
    assert run_registry_checks(fake_project) == []


def test_ci_smoke_tool_registry_checks_pass():
    assert run_tool_registry_checks() == []


def test_ci_smoke_demo_project_checks_pass():
    assert run_demo_project_checks() == []
