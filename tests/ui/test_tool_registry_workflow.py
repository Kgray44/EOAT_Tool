from __future__ import annotations

import pytest

from app.pages.tool_registry import ToolRegistryPage
from tests.ui.helpers import table_text

pytestmark = pytest.mark.usability


def test_tool_registry_lists_expected_major_tools_and_filters(qapp):
    page = ToolRegistryPage()
    page.show()
    text = table_text(page.table).lower()

    expected = [
        "project setup",
        "daily",
        "weekly",
        "morning",
        "audit",
        "photo",
        "workbook",
        "issue",
        "documentation",
        "fmea",
        "pilot",
        "kpi",
        "pm",
        "bom",
        "presentation",
        "final",
        "handoff",
        "system",
        "backup",
    ]
    missing = [item for item in expected if item not in text]
    assert not missing

    page.search.setText("fmea")
    filtered = table_text(page.table).lower()
    assert "fmea" in filtered
    assert page.table.rowCount() >= 1
