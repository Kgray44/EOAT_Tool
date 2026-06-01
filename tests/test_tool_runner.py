from __future__ import annotations

from core.tool_runner import run_python_script


def test_tool_runner_handles_missing_script(tmp_path):
    result = run_python_script(tmp_path / "missing.py", tool_id="missing", tool_name="Missing")

    assert result.success is False
    assert "Script does not exist" in result.summary
