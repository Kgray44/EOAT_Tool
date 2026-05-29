from __future__ import annotations

import pytest

from app.pages.performance import PerformancePage
from core.performance import log_performance_event
from tests.ui.helpers import table_text, wait_for_background_tasks

pytestmark = pytest.mark.usability


def test_performance_page_shows_slowest_operations_and_cache_counts(qapp, fake_config, fake_project):
    log_performance_event(fake_project, "dashboard.quick_refresh", 0.2, details={"cache_status": "hit"})
    log_performance_event(fake_project, "dashboard.deep_refresh", 2.4, details={"cache_updated": True})

    page = PerformancePage(fake_config)
    page.show()
    wait_for_background_tasks()

    assert int(page.cards["Events Logged"].value_label.text()) >= 2
    assert page.cards["Cache Hits"].value_label.text() == "1"
    assert "dashboard.deep_refresh" in table_text(page.table)
