from __future__ import annotations

from pathlib import Path

from core.atlas_models import AtlasDataBundle, AtlasIndexes, EOATRecord, MachineRecord, ToolRecord
from core.atlas_search import normalize_search_term, resolve_search_query
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key


def test_resolver_opens_exact_tool_profile_before_recommendation_matches(tmp_path: Path) -> None:
    resolution = resolve_search_query(_resolver_bundle(tmp_path), "4611380030")

    assert resolution.found is True
    assert resolution.entity_type == "tool"
    assert resolution.entity_id == "4611380030"
    assert resolution.route_target == {"page": "library", "entity_type": "tool", "entity_id": "4611380030"}
    assert resolution.confidence == "exact"


def test_resolver_normalizes_eoat_and_machine_queries(tmp_path: Path) -> None:
    bundle = _resolver_bundle(tmp_path)

    eoat = resolve_search_query(bundle, " cl eoat 0054 ")
    machine = resolve_search_query(bundle, "Machine #46")
    compact_machine = resolve_search_query(bundle, "machine46")
    short_machine = resolve_search_query(bundle, "M46")

    assert (eoat.entity_type, eoat.entity_id, eoat.confidence) == ("eoat", "CL-EOAT-0054", "normalized")
    assert (machine.entity_type, machine.entity_id) == ("machine", "46")
    assert (compact_machine.entity_type, compact_machine.entity_id) == ("machine", "46")
    assert (short_machine.entity_type, short_machine.entity_id) == ("machine", "46")


def test_resolver_routes_part_and_mold_identifiers_to_tool_profile(tmp_path: Path) -> None:
    bundle = _resolver_bundle(tmp_path)

    part = resolve_search_query(bundle, "part # PART-461")
    mold = resolve_search_query(bundle, "MOLD-461")

    assert (part.entity_type, part.entity_id) == ("tool", "4611380030")
    assert (mold.entity_type, mold.entity_id) == ("tool", "4611380030")


def test_resolver_reports_ambiguous_exact_matches(tmp_path: Path) -> None:
    bundle = _resolver_bundle(tmp_path, duplicate_part=True)

    resolution = resolve_search_query(bundle, "DUP-PART")

    assert resolution.found is True
    assert resolution.entity_type == "ambiguous"
    assert {match.key for match in resolution.matches} == {"4611380030", "DUP-TOOL"}


def test_normalize_search_term_strips_common_labels() -> None:
    assert normalize_search_term("  Machine #46  ") == "46"
    assert normalize_search_term("Tool # 4611380030") == "4611380030"
    assert normalize_search_term("EOAT CL-EOAT-0054") == "cl-eoat-0054"


def _resolver_bundle(tmp_path: Path, *, duplicate_part: bool = False) -> AtlasDataBundle:
    eoat = EOATRecord(
        eoat_id="CL-EOAT-0054",
        display_id="CL-EOAT-0054",
        tools=("4611380030",),
        machines=("46",),
        eoat_type="Vacuum",
    )
    tool = ToolRecord(
        tool="4611380030",
        label="Tool 4611380030",
        molds=("MOLD-461",),
        parts=("PART-461", "DUP-PART"),
        compatible_eoats=(eoat.eoat_id,),
        compatible_machines=("46",),
    )
    tools = [tool]
    if duplicate_part:
        tools.append(
            ToolRecord(
                tool="DUP-TOOL",
                label="Tool DUP-TOOL",
                parts=("DUP-PART",),
                compatible_machines=("46",),
            )
        )
    machine = MachineRecord(
        machine="46",
        label="Machine 46",
        robot_type="Engel Viper",
        compatible_eoats=(eoat.eoat_id,),
        compatible_tools=tuple(tool.tool for tool in tools),
    )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat.eoat_id): eoat.eoat_id},
        eoats_by_tool={normalized_tool_key(tool.tool): (eoat.eoat_id,) for tool in tools},
        eoats_by_machine={normalized_machine_key(machine.machine): (eoat.eoat_id,)},
        machines_by_tool={normalized_tool_key(tool.tool): (machine.machine,) for tool in tools},
        machines_by_eoat={normalized_eoat_key(eoat.eoat_id): (machine.machine,)},
        tools_by_machine={normalized_machine_key(machine.machine): tuple(tool.tool for tool in tools)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-09 09:00",
        eoats=(eoat,),
        machines=(machine,),
        tools=tuple(tools),
        indexes=indexes,
    )
