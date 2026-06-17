from __future__ import annotations

from .atlas_models import AtlasDataBundle, MachineRecord
from .atlas_utils import normalized_machine_key, normalized_tool_key


def machine_by_id(bundle: AtlasDataBundle, machine: str) -> MachineRecord | None:
    key = normalized_machine_key(machine)
    return next((record for record in bundle.machines if normalized_machine_key(record.machine) == key), None)


def machines_for_tool(bundle: AtlasDataBundle, tool: str) -> tuple[str, ...]:
    return bundle.indexes.machines_by_tool.get(normalized_tool_key(tool), ())


def eoats_for_machine(bundle: AtlasDataBundle, machine: str) -> tuple[str, ...]:
    return bundle.indexes.eoats_by_machine.get(normalized_machine_key(machine), ())


def tools_for_machine(bundle: AtlasDataBundle, machine: str) -> tuple[str, ...]:
    return bundle.indexes.tools_by_machine.get(normalized_machine_key(machine), ())


__all__ = ["eoats_for_machine", "machine_by_id", "machines_for_tool", "tools_for_machine"]
