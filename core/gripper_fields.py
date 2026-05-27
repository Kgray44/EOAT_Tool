from __future__ import annotations

from typing import Any

GRIPPER_COUNT_FIELD = "# of Grippers"
GRIPPER_TYPE_FIELD = "Gripper Type"
GRIPPER_MODEL_FIELD = "Gripper Model"
GRIPPER_SIZE_FIELD = "Gripper Size"

GRIPPER_TYPE_VALUES = ["Single Pressure", "Double Pressure"]

GRIPPER_MODEL_PRESETS = {
    "Large Double Gripper": "MHZL2-16D",
    "Small Double Gripper": "MHZL2-10S",
}
GRIPPER_MODEL_PRESET_LABELS = list(GRIPPER_MODEL_PRESETS)
GRIPPER_MODEL_WORKBOOK_TO_FRIENDLY = {value: label for label, value in GRIPPER_MODEL_PRESETS.items()}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def gripper_model_to_workbook(value: Any) -> str:
    text = _text(value)
    return GRIPPER_MODEL_PRESETS.get(text, text)


def gripper_model_to_ui(value: Any) -> str:
    text = _text(value)
    return GRIPPER_MODEL_WORKBOOK_TO_FRIENDLY.get(text, text)
