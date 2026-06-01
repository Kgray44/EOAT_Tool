from __future__ import annotations

from typing import Any

from .gripper_presets import (
    default_gripper_display_to_value,
    default_gripper_value_to_display,
    gripper_model_to_ui_value,
    gripper_model_to_workbook_value,
)

CUP_COUNT_FIELD = "# of Cups"
GRIPPER_COUNT_FIELD = "# of Grippers"
GRIPPER_TYPE_FIELD = "Gripper Type"
GRIPPER_MODEL_FIELD = "Gripper Model"

GRIPPER_TYPE_VALUES = ["Single Pressure", "Double Pressure"]

GRIPPER_MODEL_PRESETS = default_gripper_display_to_value()
GRIPPER_MODEL_PRESET_LABELS = list(GRIPPER_MODEL_PRESETS)
GRIPPER_MODEL_WORKBOOK_TO_FRIENDLY = default_gripper_value_to_display()


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def gripper_model_to_workbook(value: Any, project_root=None) -> str:
    return gripper_model_to_workbook_value(value, project_root)


def gripper_model_to_ui(value: Any, project_root=None) -> str:
    return gripper_model_to_ui_value(value, project_root)
