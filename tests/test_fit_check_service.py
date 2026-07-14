from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from core.atlas_models import (
    AtlasDataBundle,
    AtlasIndexes,
    DocumentationStatus,
    EOATRecord,
    MachineRecord,
    PhotoItem,
    PhotoSet,
    ToolRecord,
    WarningItem,
)
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.fit_check_service import FitCheckRequest, run_fit_check


def test_empty_selections_return_no_result(tmp_path: Path) -> None:
    assert run_fit_check(_bundle(tmp_path), FitCheckRequest()) is None


def test_tool_only_returns_partial_result_and_alternatives(tmp_path: Path) -> None:
    result = run_fit_check(_bundle(tmp_path), FitCheckRequest(tool_id="5116950010"))

    assert result is not None
    assert result.status == "insufficient_data"
    assert result.selected_tool is not None
    assert result.selected_eoat is None
    assert result.recommended_eoat is not None
    assert _requirement(result, "machine_compatibility").status == "unknown"
    assert _requirement(result, "eoat_compatibility").status == "unknown"
    assert _requirement(result, "robot_type").status == "unknown"
    assert _requirement(result, "air_architecture").status == "unknown"
    assert _requirement(result, "quick_disconnect").status == "unknown"
    assert _requirement(result, "part_count").status == "unknown"
    assert _requirement(result, "sensor_requirements").status == "unknown"
    assert result.warnings == ()
    assert result.alternatives.machines
    assert result.alternatives.eoats


def test_machine_only_returns_partial_result_and_alternatives(tmp_path: Path) -> None:
    result = run_fit_check(_bundle(tmp_path), FitCheckRequest(machine_id="71"))

    assert result is not None
    assert result.status == "insufficient_data"
    assert result.selected_machine is not None
    assert result.alternatives.eoats


def test_tool_machine_recommends_eoat_without_validating_it(tmp_path: Path) -> None:
    result = run_fit_check(_bundle(tmp_path), FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_mode="auto"))

    assert result is not None
    assert result.status == "insufficient_data"
    assert result.selected_eoat is None
    assert result.recommended_eoat is not None
    assert result.recommended_eoat.eoat_id == "P4-EOAT-0002"
    assert _requirement(result, "machine_compatibility").status == "pass"
    assert _requirement(result, "eoat_compatibility").status == "unknown"
    assert _requirement(result, "quick_disconnect").status == "unknown"
    assert _requirement(result, "part_count").status == "unknown"
    assert _requirement(result, "sensor_requirements").status == "unknown"


def test_tool_eoat_partial_check_requires_machine_not_eoat(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", eoat_id="P4-EOAT-0002", eoat_mode="manual"),
    )

    assert result is not None
    assert result.status == "insufficient_data"
    assert "Machine" in result.message
    assert result.selected_tool is not None
    assert result.selected_machine is None
    assert result.selected_eoat is not None
    assert _requirement(result, "machine_compatibility").value == "Select Machine"
    assert _requirement(result, "eoat_compatibility").status == "pass"
    assert _requirement(result, "robot_type").value == "Select Machine"
    assert _requirement(result, "air_architecture").value == "Select Machine"
    assert _requirement(result, "quick_disconnect").value != "Select EOAT"
    assert _requirement(result, "part_count").status == "pass"
    assert _requirement(result, "sensor_requirements").value != "Select EOAT"
    assert result.alternatives.machines


def test_machine_eoat_partial_check_requires_tool_not_machine_or_eoat(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"),
    )

    assert result is not None
    assert result.status == "insufficient_data"
    assert "Tool" in result.message
    assert result.selected_tool is None
    assert result.selected_machine is not None
    assert result.selected_eoat is not None
    assert _requirement(result, "machine_compatibility").value == "Select Tool"
    assert _requirement(result, "eoat_compatibility").status == "pass"
    assert _requirement(result, "robot_type").status == "pass"
    assert _requirement(result, "air_architecture").status in {"pass", "warning"}
    assert _requirement(result, "quick_disconnect").value != "Select EOAT"


def test_complete_selected_setup_validates_eoat_requirements(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"),
    )

    assert result is not None
    assert result.status in {"compatible", "warning"}
    assert result.selected_eoat is not None
    assert result.selected_eoat.eoat_id == "P4-EOAT-0002"
    assert _requirement(result, "machine_compatibility").status == "pass"
    assert _requirement(result, "eoat_compatibility").status == "pass"


def test_tool_machine_without_eoat_input_is_insufficient_even_without_recommendation(tmp_path: Path) -> None:
    result = run_fit_check(_bundle(tmp_path), FitCheckRequest(tool_id="NOEOAT-1", machine_id="71", eoat_mode="auto"))

    assert result is not None
    assert result.status == "insufficient_data"
    assert result.input_completeness.has_tool is True
    assert result.input_completeness.has_machine is True
    assert result.input_completeness.has_eoat is False
    assert result.recommended_eoat is None
    assert any(warning.id == "no-eoat-found" for warning in result.warnings)


def test_manual_eoat_mismatch_returns_not_compatible(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0099", eoat_mode="manual"),
    )

    assert result is not None
    assert result.status == "not_compatible"
    assert result.headline == "Not Compatible"
    assert "Insufficient Data" not in result.headline
    assert "Select EOAT" not in result.message
    assert result.selected_eoat is not None
    assert result.selected_eoat.eoat_id == "P4-EOAT-0099"
    assert result.recommended_eoat is not None
    assert result.recommended_eoat.eoat_id == "P4-EOAT-0002"
    assert result.input_completeness.complete() is True
    assert result.validity.eoat_exists is True
    assert result.compatibility.full_setup == "fail"
    assert result.tool_to_eoat.status == "conflict"
    assert result.eoat_to_machine.status == "conflict"
    assert all(requirement.value != "Select EOAT" for requirement in result.requirements)


def test_invalid_manual_eoat_is_invalid_input_not_missing_data(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-DOES-NOT-EXIST", eoat_mode="manual"),
    )

    assert result is not None
    assert result.status == "invalid_input"
    assert result.headline == "Invalid Input"
    assert result.input_completeness.complete() is True
    assert result.validity.tool_exists is True
    assert result.validity.machine_exists is True
    assert result.validity.eoat_exists is False
    assert result.compatibility.full_setup == "not_evaluated"
    assert "Insufficient Data" not in result.headline
    assert "Select EOAT" not in result.message
    assert _requirement(result, "eoat_compatibility").value == "Invalid EOAT"
    assert all(requirement.value != "Select EOAT" for requirement in result.requirements)


def test_incompatible_selected_eoat_is_not_ranked_best_match(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0099", eoat_mode="manual"),
    )

    assert result is not None
    alternatives = {item.eoat.eoat_id: item for item in result.alternatives.eoats}
    assert alternatives["P4-EOAT-0099"].status == "incompatible"
    assert alternatives["P4-EOAT-0099"].status_label == "Incompatible"
    assert alternatives["P4-EOAT-0002"].status == "best"
    assert alternatives["P4-EOAT-0002"].status_label == "Best Match"


def test_incompatible_selected_machine_is_not_ranked_best_match(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", machine_id="26", eoat_id="P4-EOAT-0002", eoat_mode="manual"),
    )

    assert result is not None
    alternatives = {item.machine.machine: item for item in result.alternatives.machines}
    assert alternatives["26"].status == "incompatible"
    assert alternatives["26"].status_label == "Incompatible"
    assert any(item.status == "best" for key, item in alternatives.items() if key != "26")


def test_missing_current_eoat_mode_produces_warning(tmp_path: Path) -> None:
    bundle = replace(
        _bundle(tmp_path),
        machines=(replace(_machine("71"), current_eoat="", current_eoat_status="unknown"),),
    )

    result = run_fit_check(bundle, FitCheckRequest(machine_id="71", eoat_mode="current"))

    assert result is not None
    assert result.status == "insufficient_data"
    assert any("Current EOAT" in warning.title for warning in result.warnings)


def test_missing_photo_and_documentation_are_data_quality_notes_not_setup_warnings(tmp_path: Path) -> None:
    poor_eoat = replace(
        _eoat("P4-EOAT-0002"),
        documentation=DocumentationStatus(score=42, status_label="Needs Review"),
        photos=PhotoSet(eoat_id="P4-EOAT-0002"),
    )
    bundle = replace(_bundle(tmp_path), eoats=(poor_eoat, _eoat("P4-EOAT-0099", machines=("99",), tools=("MISMATCH",))))

    result = run_fit_check(bundle, FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"))

    assert result is not None
    assert result.status == "compatible"
    warning_blob = " ".join(f"{warning.title} {warning.message}" for warning in result.warnings).casefold()
    assert "photo" not in warning_blob
    assert "documentation" not in warning_blob
    notes = tuple(result.details.documentation_details["data_quality_notes"])
    assert any("photo" in note.casefold() for note in notes)
    assert any("documentation score" in note.casefold() for note in notes)


def test_unknown_known_issue_placeholder_is_not_setup_warning(tmp_path: Path) -> None:
    eoat = replace(
        _eoat("P4-EOAT-0002"),
        known_issues="Unknown / Not Checked",
        warnings=(WarningItem("info", "Known issue noted", "Unknown / Not Checked"),),
    )
    bundle = replace(_bundle(tmp_path), eoats=(eoat, _eoat("P4-EOAT-0099", machines=("99",), tools=("MISMATCH",))))

    result = run_fit_check(bundle, FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"))

    assert result is not None
    assert not any("Known issue" in warning.title for warning in result.warnings)


def test_real_known_issue_remains_setup_warning(tmp_path: Path) -> None:
    eoat = replace(_eoat("P4-EOAT-0002"), known_issues="Vacuum issue at pickup")
    bundle = replace(_bundle(tmp_path), eoats=(eoat, _eoat("P4-EOAT-0099", machines=("99",), tools=("MISMATCH",))))

    result = run_fit_check(bundle, FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"))

    assert result is not None
    assert any("Known issue" in warning.title for warning in result.warnings)


def test_alternatives_are_generated_and_ranked(tmp_path: Path) -> None:
    result = run_fit_check(_bundle(tmp_path), FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"))

    assert result is not None
    assert result.alternatives.machines[0].status in {"current", "best"}
    assert result.alternatives.eoats[0].eoat.eoat_id == "P4-EOAT-0002"
    assert result.alternatives.eoats[0].status in {"current", "best"}


def test_requirement_statuses_are_derived_from_source_data(tmp_path: Path) -> None:
    result = run_fit_check(
        _bundle(tmp_path),
        FitCheckRequest(tool_id="5116950010", machine_id="71", eoat_id="P4-EOAT-0002", eoat_mode="manual"),
    )

    assert result is not None
    requirements = {item.id: item for item in result.requirements}
    assert requirements["robot_type"].status == "pass"
    assert requirements["air_architecture"].status in {"pass", "warning"}
    assert requirements["quick_disconnect"].status == "pass"
    assert requirements["part_count"].value == "Match (4 parts)"
    assert requirements["sensor_requirements"].status == "pass"


def _requirement(result, requirement_id: str):
    return next(item for item in result.requirements if item.id == requirement_id)


def _bundle(tmp_path: Path) -> AtlasDataBundle:
    eoat = _eoat("P4-EOAT-0002")
    other_eoat = _eoat("P4-EOAT-0099", tools=("OTHER-TOOL",), machines=("99",), robot_types=("Sytrama",))
    tool = ToolRecord(
        tool="5116950010",
        label="Tool 5116950010",
        parts=("WASHER, 29MM",),
        part_family="Washer",
        part_description="WASHER, 29MM",
        compatible_eoats=("P4-EOAT-0002", "P4-EOAT-0003"),
        compatible_machines=("71", "2", "26"),
        source_rows=({"Number of Parts Picked": "4", "Last Audit Date": "2026-06-20"},),
    )
    no_eoat_tool = ToolRecord(
        tool="NOEOAT-1",
        label="Tool NOEOAT-1",
        compatible_machines=("71",),
        source_rows=({"Number of Parts Picked": "1", "Last Audit Date": "2026-06-20"},),
    )
    machine = _machine("71")
    alt_machine = _machine("2")
    verify_machine = replace(_machine("26"), compatible_eoats=("P4-EOAT-0003",), current_eoat="")
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(record.eoat_id): record.eoat_id for record in (eoat, other_eoat)},
        eoats_by_tool={normalized_tool_key(tool.tool): ("P4-EOAT-0002", "P4-EOAT-0003")},
        eoats_by_machine={normalized_machine_key("71"): ("P4-EOAT-0002",)},
        machines_by_tool={normalized_tool_key(tool.tool): ("71", "2", "26")},
        machines_by_eoat={normalized_eoat_key("P4-EOAT-0002"): ("71", "2")},
        tools_by_machine={normalized_machine_key("71"): (tool.tool, no_eoat_tool.tool)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-06 08:00",
        eoats=(eoat, other_eoat),
        tools=(tool, no_eoat_tool),
        machines=(machine, alt_machine, verify_machine),
        indexes=indexes,
    )


def _eoat(
    eoat_id: str,
    *,
    tools: tuple[str, ...] = ("5116950010",),
    machines: tuple[str, ...] = ("71", "2"),
    robot_types: tuple[str, ...] = ("Wittmann",),
) -> EOATRecord:
    photo = PhotoItem(path=f"C:/tmp/{eoat_id}.png", filename=f"{eoat_id}.png")
    return EOATRecord(
        eoat_id=eoat_id,
        display_id=eoat_id,
        tools=tools,
        machines=machines,
        eoat_type="Mechanical / Gripper",
        robot_types=robot_types,
        connection_type="Pneumatic Quick Disconnect: Staubli",
        pressure_info="Air Circuit Architecture: Robot pressure; # of Grippers: 4",
        sensor_info="Sensors Present? Yes; Part-Present Detection Present? Yes",
        documentation=DocumentationStatus(score=91, status_label="Good"),
        photos=PhotoSet(eoat_id=eoat_id, photos=(photo,)),
        source_rows=(
            {
                "Number of Parts Picked": "4",
                "Air Circuit Architecture": "Robot pressure",
                "Pneumatic Quick Disconnect Type": "Staubli",
                "Last Audit Date": "2026-06-18",
            },
        ),
    )


def _machine(machine: str) -> MachineRecord:
    return MachineRecord(
        machine=machine,
        label=f"Machine {machine}",
        robot_type="Wittmann",
        robot_model="Wittmann W701",
        compatible_eoats=("P4-EOAT-0002",),
        compatible_tools=("5116950010", "NOEOAT-1"),
        current_eoat="P4-EOAT-0002",
        documentation_score=94,
        source_rows=(
            {
                "Air Circuit Architecture": "Robot pressure",
                "External Pressure Circuits": "0 external",
                "Last Audit Date": "2026-06-21",
            },
        ),
    )
