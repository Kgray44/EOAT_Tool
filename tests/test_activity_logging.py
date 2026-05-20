from __future__ import annotations

import json

from core.logging import activity_log_path, log_tool_run, read_recent_activity
from core.result import ToolResult


def test_activity_logging_writes_jsonl(tmp_path):
    result = ToolResult.ok("test_tool", "Test Tool", "Logged.")

    warning = log_tool_run(result, tmp_path)
    path = activity_log_path(tmp_path)

    assert warning is None
    assert path.exists()
    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["tool_id"] == "test_tool"
    assert entry["success"] is True


def test_read_recent_activity_returns_newest_first(tmp_path):
    log_tool_run(ToolResult.ok("one", "One", "First."), tmp_path)
    log_tool_run(ToolResult.ok("two", "Two", "Second."), tmp_path)

    entries, warning = read_recent_activity(tmp_path, limit=2)

    assert warning is None
    assert [entry["tool_id"] for entry in entries] == ["two", "one"]
