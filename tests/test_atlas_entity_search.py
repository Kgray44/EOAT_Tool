from __future__ import annotations

from pathlib import Path

from core.atlas_entity_search import EntitySearchIndex, result_from_recent_dict
from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, ToolRecord


def test_entity_search_exact_tool_and_machine_number_priority(tmp_path: Path) -> None:
    index = EntitySearchIndex.build(_bundle(tmp_path))

    tool = index.search("6201510010").top_exact_match
    machine = index.search("52").top_exact_match

    assert tool is not None
    assert (tool.entity_type, tool.entity_id) == ("tool", "6201510010")
    assert tool.route_target == {"page": "library", "entity_type": "tool", "entity_id": "6201510010"}
    assert machine is not None
    assert (machine.entity_type, machine.entity_id) == ("machine", "52")


def test_recent_entity_dict_validates_against_current_index(tmp_path: Path) -> None:
    index = EntitySearchIndex.build(_bundle(tmp_path))
    recent = {
        "type": "eoat",
        "id": "P4-EOAT-0052",
        "displayLabel": "Old label",
        "route": {"page": "library", "entity_type": "eoat", "entity_id": "P4-EOAT-0052"},
    }

    result = result_from_recent_dict(recent, index)
    stale = result_from_recent_dict({**recent, "id": "P4-EOAT-9999"}, index)

    assert result is not None
    assert result.display_label == "P4-EOAT-0052"
    assert index.has(result.entity_type, result.entity_id)
    assert stale is not None
    assert not index.has(stale.entity_type, stale.entity_id)


def _bundle(tmp_path: Path) -> AtlasDataBundle:
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0052",
        display_id="P4-EOAT-0052",
        tools=("6201510010",),
        machines=("52",),
        eoat_type="Vacuum",
        status="Installed",
    )
    tool = ToolRecord(
        tool="6201510010",
        label="Tool 6201510010",
        compatible_eoats=(eoat.eoat_id,),
        compatible_machines=("52",),
        part_description="Demo part",
    )
    machine = MachineRecord(
        machine="52",
        label="Machine 52",
        robot_type="Engel Viper",
        compatible_eoats=(eoat.eoat_id,),
        compatible_tools=(tool.tool,),
        current_eoat=eoat.eoat_id,
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-09 09:00",
        eoats=(eoat,),
        machines=(machine,),
        tools=(tool,),
    )
