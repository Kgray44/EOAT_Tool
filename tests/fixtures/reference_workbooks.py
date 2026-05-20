from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from core.press_lookup import CAPACITY_FILE_NAME, MASTER_FILE_NAME


def create_press_reference_workbooks(
    folder: str | Path,
    *,
    duplicate_master: bool = False,
    multiple_capacity_rows: bool = False,
) -> Path:
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    _create_master(root / MASTER_FILE_NAME, duplicate_master=duplicate_master)
    _create_capacity(root / CAPACITY_FILE_NAME, multiple_capacity_rows=multiple_capacity_rows)
    return root


def _create_master(path: Path, *, duplicate_master: bool) -> None:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Machine Specifications"
    headers = [
        "Machine Number",
        "U.S. Tons",
        "Press Brand",
        "Model #",
        "Year Mfg.",
        "Controller Type",
        "Screw Diameter",
        "Injection Capacity",
        "Robot/Picker Brand",
        "Robot/Picker Model #",
        "Robot/Picker Serial #",
        "Robot/Picker Mfg. Date",
        "Full Servo",
        "# of TCU's",
        "EDART UNIT PRESS SIDE",
    ]
    ws.append(headers)
    row = [12, 80, "Nissei", "FNX80", 2018, "TACT", "25mm", "3.1 oz", "Wittmann", "W833", "ROB-12", 2019, "Yes", 2, "Left"]
    ws.append(row)
    if duplicate_master:
        duplicate = row[:]
        duplicate[2] = "Nissei Alternate"
        ws.append(duplicate)
    workbook.save(path)
    workbook.close()


def _create_capacity(path: Path, *, multiple_capacity_rows: bool) -> None:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Capacity"
    ws.append(["Press 12 - 80T - 25mm Screw"])
    ws.append(
        [
            "Machine No.",
            "NGW Part Number",
            "NGW Part Description",
            "Bill-to / Customer",
            "Cycle Time (S)",
            "Cavitation",
            "Forecasted Capacity",
            "Available Capacity",
            "Hours Allocated per month",
            "Hours per week",
            "Committed Hours per Year",
        ]
    )
    ws.append(["12", "DEMO-PN-1200", "Demo housing cap", "Demo Customer A", 18.5, 4, 100000, 25000, 120, 30, 1440])
    if multiple_capacity_rows:
        ws.append(["12", "DEMO-PN-1201", "Demo housing base", "Demo Customer A", 22.0, 2, 80000, 18000, 90, 22.5, 1080])
    ws.append(["1, 70", "DEMO-PN-0170", "Shared row for other machines", "Other demo customer", 30, 1, 1000, 500, 10, 2.5, 120])
    ws.append(["Summary for Press 12 committed hours"])
    workbook.save(path)
    workbook.close()

