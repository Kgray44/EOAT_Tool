from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolResult:
    tool_id: str
    tool_name: str
    success: bool
    summary: str
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    output_reports: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    structured_data: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float | None = None

    @classmethod
    def ok(
        cls,
        tool_id: str,
        tool_name: str,
        summary: str,
        **kwargs: Any,
    ) -> "ToolResult":
        return cls(tool_id=tool_id, tool_name=tool_name, success=True, summary=summary, **kwargs)

    @classmethod
    def fail(
        cls,
        tool_id: str,
        tool_name: str,
        summary: str,
        errors: list[str] | None = None,
        **kwargs: Any,
    ) -> "ToolResult":
        return cls(
            tool_id=tool_id,
            tool_name=tool_name,
            success=False,
            summary=summary,
            errors=errors or [],
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        lines = [f"# {self.tool_name}", "", f"**Status:** {status}", f"**Summary:** {self.summary}"]
        if self.duration_seconds is not None:
            lines.append(f"**Duration:** {self.duration_seconds:.2f} seconds")
        for title, values in [
            ("Details", self.details),
            ("Warnings", self.warnings),
            ("Errors", self.errors),
            ("Files Created", self.files_created),
            ("Files Modified", self.files_modified),
            ("Output Reports", self.output_reports),
        ]:
            if values:
                lines.extend(["", f"## {title}"])
                lines.extend(f"- {value}" for value in values)
        if self.metrics:
            lines.extend(["", "## Metrics"])
            lines.extend(f"- {key}: {value}" for key, value in self.metrics.items())
        return "\n".join(lines) + "\n"
