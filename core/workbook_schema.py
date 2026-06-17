from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .constants import TOOLKIT_ROOT

DEFAULT_SCHEMA_PATH = TOOLKIT_ROOT / "data_templates" / "workbook_schema.json"


@lru_cache(maxsize=4)
def load_workbook_schema(schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    path = Path(schema_path)
    return json.loads(path.read_text(encoding="utf-8"))


def get_expected_sheets(schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> list[str]:
    schema = load_workbook_schema(Path(schema_path))
    return list(schema.get("sheets", {}).keys())


def get_expected_headers(sheet_name: str, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> list[str]:
    schema = load_workbook_schema(Path(schema_path))
    sheet = schema.get("sheets", {}).get(sheet_name, {})
    return list(sheet.get("required_headers", []))


def get_key_inventory_headers() -> list[str]:
    return [
        "Audit ID",
        "Audit Date",
        "Auditor",
        "Plant/Area",
        "Press/Machine #",
        "Tool #",
        "EOAT Assembly ID",
        "Robot Type",
        "EOAT Type",
        "# of Cylinders",
        "Cylinder Type",
        "Sensors Present?",
        "Tubing Condition",
        "Cable Management Condition",
        "Known Issues",
        "Maintenance Frequency",
        "Photos Taken?",
        "Status",
        "Priority",
        "Pilot Candidate?",
        "Audit Context",
        "Manual Completion Override",
        "Notes",
    ]
