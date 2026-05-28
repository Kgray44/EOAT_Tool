from __future__ import annotations

import json

from core.gripper_fields import gripper_model_to_ui, gripper_model_to_workbook
from core.gripper_presets import (
    gripper_model_display_values,
    is_known_gripper_preset,
    load_gripper_presets,
    project_gripper_presets_path,
)


def test_default_gripper_presets_preserve_existing_mappings():
    presets = {preset.friendly_name: preset.part_number for preset in load_gripper_presets()}

    assert presets["Large Double Gripper"] == "MHZL2-16D"
    assert presets["Small Double Gripper"] == "MHZL2-10S"
    assert gripper_model_to_workbook("Large Double Gripper") == "MHZL2-16D"
    assert gripper_model_to_workbook("Small Double Gripper") == "MHZL2-10S"
    assert gripper_model_to_ui("MHZL2-16D") == "Large Double Gripper"
    assert gripper_model_to_ui("MHZL2-10S") == "Small Double Gripper"


def test_project_gripper_presets_extend_dropdown_and_mapping(fake_project):
    path = project_gripper_presets_path(fake_project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "presets": [
                    {
                        "friendly_name": "Demo Test Gripper",
                        "part_number": "DEMO-GRIP-001",
                        "manufacturer": "Synthetic",
                        "default_type": "Double Pressure",
                        "notes": "Synthetic test preset.",
                        "active": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    labels = gripper_model_display_values(fake_project)

    assert "Demo Test Gripper" in labels
    assert gripper_model_to_workbook("Demo Test Gripper", fake_project) == "DEMO-GRIP-001"
    assert gripper_model_to_ui("DEMO-GRIP-001", fake_project) == "Demo Test Gripper"
    assert is_known_gripper_preset("DEMO-GRIP-001", fake_project) is True
