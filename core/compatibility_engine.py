from __future__ import annotations

from .atlas_models import AtlasDataBundle, CompatibilityLink
from .atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key


def eoat_to_machines(bundle: AtlasDataBundle, eoat_id: str) -> list[CompatibilityLink]:
    record = _eoat(bundle, eoat_id)
    if record is None:
        return []
    links = []
    for machine in record.machines:
        for tool in record.tools or ("",):
            links.append(
                CompatibilityLink(
                    eoat_id=record.eoat_id,
                    machine=machine,
                    tool=tool,
                    part=record.part_description,
                    status="Compatible",
                    source=_source_for_link(record.eoat_id, machine, tool),
                    reasons=("EOAT profile lists this machine/tool relationship.",),
                    warnings=record.warnings,
                )
            )
    return links


def machine_to_eoats(bundle: AtlasDataBundle, machine: str) -> list[CompatibilityLink]:
    key = normalized_machine_key(machine)
    eoat_ids = bundle.indexes.eoats_by_machine.get(key, ())
    links = []
    for eoat_id in eoat_ids:
        record = _eoat(bundle, eoat_id)
        if record is None:
            continue
        links.append(
            CompatibilityLink(
                eoat_id=record.eoat_id,
                machine=machine,
                tool=", ".join(record.tools),
                part=record.part_description,
                status="Compatible",
                source="EOAT Master Tracker / Press Capacity",
                reasons=(f"{record.eoat_id} is indexed as compatible with Machine {machine}.",),
                warnings=record.warnings,
            )
        )
    return links


def tool_to_eoats(bundle: AtlasDataBundle, tool: str) -> list[CompatibilityLink]:
    key = normalized_tool_key(tool)
    eoat_ids = bundle.indexes.eoats_by_tool.get(key, ())
    machines = bundle.indexes.machines_by_tool.get(key, ())
    links = []
    for eoat_id in eoat_ids:
        record = _eoat(bundle, eoat_id)
        if record is None:
            continue
        for machine in machines or record.machines or ("",):
            links.append(
                CompatibilityLink(
                    eoat_id=record.eoat_id,
                    machine=machine,
                    tool=tool,
                    part=record.part_description,
                    status="Compatible",
                    source="Exact tool match",
                    reasons=(f"Tool {tool} is linked to {record.eoat_id}.",),
                    warnings=record.warnings,
                )
            )
    return links


def compatibility_matrix_rows(bundle: AtlasDataBundle, *, mode: str = "eoat_machine") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if mode == "tool_eoat":
        for tool in bundle.tools:
            for eoat_id in tool.compatible_eoats or ("",):
                rows.append(
                    {
                        "Tool": tool.tool,
                        "EOAT": eoat_id,
                        "Machines": ", ".join(tool.compatible_machines),
                        "Status": "Compatible" if eoat_id else "Missing EOAT",
                        "Source": tool.source,
                    }
                )
        return rows
    if mode == "tool_machine":
        for tool in bundle.tools:
            for machine in tool.compatible_machines or ("",):
                rows.append(
                    {
                        "Tool": tool.tool,
                        "Machine": machine,
                        "EOATs": ", ".join(tool.compatible_eoats),
                        "Status": "Compatible" if machine else "Missing machine",
                        "Source": tool.source,
                    }
                )
        return rows
    for eoat in bundle.eoats:
        for machine in eoat.machines or ("",):
            rows.append(
                {
                    "EOAT": eoat.eoat_id,
                    "Machine": machine,
                    "Tools": ", ".join(eoat.tools),
                    "EOAT Type": eoat.eoat_type,
                    "Status": "Compatible" if machine else "Missing data",
                    "Documentation": f"{eoat.documentation.score}%",
                    "Photos": str(eoat.photo_count),
                    "Warnings": str(eoat.warning_count),
                }
            )
    return rows


def _eoat(bundle: AtlasDataBundle, eoat_id: str):
    key = normalized_eoat_key(eoat_id)
    canonical = bundle.indexes.eoat_by_id.get(key, eoat_id)
    return next((record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) == normalized_eoat_key(canonical)), None)


def _source_for_link(eoat_id: str, machine: str, tool: str) -> str:
    pieces = ["EOAT Master Tracker"]
    if machine and tool:
        pieces.append("Press Capacity inferred where available")
    if eoat_id.startswith("AUD-"):
        pieces.append("audit fallback ID")
    return " + ".join(pieces)


__all__ = ["compatibility_matrix_rows", "eoat_to_machines", "machine_to_eoats", "tool_to_eoats"]
