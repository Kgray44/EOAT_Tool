from __future__ import annotations

import pytest


@pytest.fixture
def fake_project(usability_fake_project):
    return usability_fake_project


@pytest.fixture
def fake_config(usability_fake_config):
    return usability_fake_config
