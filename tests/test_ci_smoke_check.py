from __future__ import annotations

from scripts.ci_smoke_check import run_registry_checks


def test_ci_smoke_registry_checks_pass(fake_project):
    assert run_registry_checks(fake_project) == []
