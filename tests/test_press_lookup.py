from __future__ import annotations

import pytest

from core.press_lookup import lookup_press, normalize_machine_number
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


@pytest.mark.parametrize("value", ["12", "Press 12", "P12", "Machine 12", "M12", "press-12", "Press #12"])
def test_machine_number_normalization_accepts_common_forms(value):
    assert normalize_machine_number(value) == 12


def test_lookup_fills_master_press_fields(fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")

    result = lookup_press(fake_project, "Press 12")

    assert result.master_matched is True
    assert result.master_fields["U.S. Tons"] == 80
    assert result.master_fields["Press Brand"] == "Nissei"
    assert result.master_fields["Robot/Picker Model #"] == "W833"
    assert result.robot_type_suggestion == "Wittmann W833"
    assert result.robot_model_controller_suggestion == "W833"


def test_lookup_fills_capacity_fields(fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")

    result = lookup_press(fake_project, "12")

    assert result.capacity_matched is True
    assert result.capacity_summary["Press Capacity Label"] == "Press 12 - 80T - 25mm Screw"
    assert result.capacity_summary["Capacity Tonnage"] == "80T"
    assert result.capacity_summary["Screw Size"] == "25mm Screw"
    assert result.capacity_part_rows[0].fields["NGW Part Number"] == "DEMO-PN-1200"
    assert result.capacity_part_rows[0].fields["Cycle Time (S)"] == 18.5
    assert result.part_family_suggestion == "DEMO-PN-1200 - Demo housing cap"


def test_multiple_capacity_rows_are_preserved_for_selection(fake_project):
    create_press_reference_workbooks(fake_project / "reference-data", multiple_capacity_rows=True)

    result = lookup_press(fake_project, "Machine 12")

    assert len(result.capacity_part_rows) == 2
    assert [row.fields["NGW Part Number"] for row in result.capacity_part_rows] == ["DEMO-PN-1200", "DEMO-PN-1201"]


def test_capacity_lookup_finds_machine_in_comma_separated_machine_no(fake_project):
    create_press_reference_workbooks(fake_project / "reference-data")

    result = lookup_press(fake_project, "70")

    assert result.capacity_matched is True
    assert result.capacity_part_rows[0].fields["NGW Part Number"] == "DEMO-PN-0170"


def test_missing_machine_number_is_clear_error():
    with pytest.raises(ValueError, match="Machine number is required"):
        normalize_machine_number("")


@pytest.mark.parametrize("value", ["banana", "Press banana", "12 and 13"])
def test_machine_number_normalization_rejects_invalid_forms(value):
    with pytest.raises(ValueError):
        normalize_machine_number(value)


def test_duplicate_master_rows_produce_warning(fake_project):
    create_press_reference_workbooks(fake_project / "reference-data", duplicate_master=True)

    result = lookup_press(fake_project, "12")

    assert any("Multiple master press rows" in warning for warning in result.warnings)
    assert any("Conflicting master values for Press Brand" in warning for warning in result.warnings)


def test_missing_reference_file_does_not_crash(fake_project):
    result = lookup_press(fake_project, "12")

    assert result.master_matched is False
    assert result.capacity_matched is False
    assert any("reference file not found" in warning for warning in result.warnings)
