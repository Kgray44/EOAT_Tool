from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import TOOLKIT_ROOT

DEFAULT_REGISTRY_PATH = TOOLKIT_ROOT / "data_templates" / "tool_registry_seed.json"


@dataclass(frozen=True)
class ToolMetadata:
    id: str
    name: str
    category: str
    phase: str
    description: str
    input: str
    output: str
    safe_to_run_repeatedly: bool
    modifies_project_files: bool
    requires_workbook: bool
    requires_git: bool
    dashboard_page: str
    cli_module: str
    entry_point: str
    implementation_status: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolMetadata:
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ToolRegistry:
    def __init__(self, tools: list[ToolMetadata]):
        self._tools = tools
        self._by_id = {tool.id: tool for tool in tools}

    @classmethod
    def load(cls, path: str | Path = DEFAULT_REGISTRY_PATH) -> ToolRegistry:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([ToolMetadata.from_dict(item) for item in data])

    def list_tools(self) -> list[ToolMetadata]:
        return list(self._tools)

    def get(self, tool_id: str) -> ToolMetadata | None:
        return self._by_id.get(tool_id)

    def implemented_tools(self) -> list[ToolMetadata]:
        return [tool for tool in self._tools if tool.implementation_status in {"implemented", "partial"}]
