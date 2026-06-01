from __future__ import annotations

from core.result import ToolResult


def test_tool_result_to_dict_and_markdown():
    result = ToolResult.ok(
        "sample",
        "Sample Tool",
        "Finished cleanly.",
        details=["Checked folders"],
        metrics={"count": 2},
    )

    data = result.to_dict()
    markdown = result.to_markdown()

    assert data["tool_id"] == "sample"
    assert data["success"] is True
    assert "# Sample Tool" in markdown
    assert "Checked folders" in markdown
    assert "count: 2" in markdown
