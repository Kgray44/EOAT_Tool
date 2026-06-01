from __future__ import annotations

from pathlib import Path

from .markdown_writer import write_markdown_report
from .result import ToolResult


def write_tool_result_report(output_dir: str | Path, result: ToolResult, overwrite: bool = False) -> Path:
    return write_markdown_report(output_dir, result.tool_id, result.to_markdown(), overwrite=overwrite)
