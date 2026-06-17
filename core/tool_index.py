from __future__ import annotations

from .atlas_models import AtlasDataBundle, ToolRecord
from .atlas_utils import normalized_tool_key


def tool_by_id(bundle: AtlasDataBundle, tool: str) -> ToolRecord | None:
    key = normalized_tool_key(tool)
    return next((record for record in bundle.tools if normalized_tool_key(record.tool) == key), None)


def eoats_for_tool(bundle: AtlasDataBundle, tool: str) -> tuple[str, ...]:
    return bundle.indexes.eoats_by_tool.get(normalized_tool_key(tool), ())


def machines_for_tool(bundle: AtlasDataBundle, tool: str) -> tuple[str, ...]:
    return bundle.indexes.machines_by_tool.get(normalized_tool_key(tool), ())


__all__ = ["eoats_for_tool", "machines_for_tool", "tool_by_id"]
