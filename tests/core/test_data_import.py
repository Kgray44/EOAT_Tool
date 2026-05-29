from __future__ import annotations

import csv
import json
from pathlib import Path

from openpyxl import Workbook

from core.data_import import (
    confirm_import,
    detect_import_type,
    dry_run_import,
    import_log_path,
    preview_import_file,
    read_import_log,
    supported_import_types,
    validate_import_file,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> Path:
    headers = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Import"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    workbook.save(path)
    workbook.close()
    return path


def test_supported_import_types_include_requested_sources():
    type_ids = {spec.type_id for spec in supported_import_types()}

    assert {
        "press_capacity",
        "downtime_export",
        "scrap_export",
        "maintenance_event_export",
        "cycle_time_baseline",
        "machine_master_list",
        "robot_list",
        "pm_records",
    }.issubset(type_ids)


def test_data_import_detects_previews_maps_and_dry_runs_without_writing(fake_project, tmp_path):
    source = _write_csv(
        tmp_path / "downtime.csv",
        [
            {"Date": "2026-05-18", "Machine": "Press 12", "Minutes Down": "30", "Source": "MES export"},
            {"Date": "2026-05-19", "Machine": "Press 12", "Minutes Down": "15", "Source": "MES export"},
        ],
    )

    assert detect_import_type(source) == "downtime_export"
    preview = preview_import_file(source)
    dry_run = dry_run_import(fake_project, source)

    assert preview.row_count == 2
    assert preview.mapping["Press/Machine #"] == "Machine"
    assert dry_run.row_count == 2
    assert dry_run.mapped_rows[0]["Downtime Minutes"] == 30.0
    assert not Path(dry_run.would_write[0]).exists()
    assert not import_log_path(fake_project).exists()


def test_data_import_validates_missing_required_mapping(fake_project, tmp_path):
    source = _write_csv(tmp_path / "scrap.csv", [{"Date": "2026-05-18", "Press": "Press 12", "Reason": "Drop"}])

    _preview, issues = validate_import_file(source, import_type="scrap_export")

    assert any(issue.severity == "error" and issue.field == "Scrap Quantity" for issue in issues)


def test_confirm_import_requires_confirmation_and_writes_log(fake_project, tmp_path):
    source = _write_csv(
        tmp_path / "cycle_time.csv",
        [{"Date": "2026-05-18", "Press": "Press 12", "Cycle Seconds": "18.5", "Source": "PLC measured export"}],
    )

    unconfirmed = confirm_import(fake_project, source, import_type="cycle_time_baseline", confirmed=False, log_activity=False)
    confirmed = confirm_import(fake_project, source, import_type="cycle_time_baseline", confirmed=True, log_activity=False)

    assert unconfirmed.success is False
    assert confirmed.success is True
    assert confirmed.files_created
    snapshot = next(Path(path) for path in confirmed.files_created if path.endswith(".json"))
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["import_type"] == "cycle_time_baseline"
    assert payload["rows"][0]["Cycle Time"] == 18.5
    assert read_import_log(fake_project)[0]["import_type"] == "cycle_time_baseline"


def test_press_capacity_workbook_detects_from_xlsx_headers(fake_project, tmp_path):
    source = _write_xlsx(tmp_path / "capacity.xlsx", ["Machine No.", "Part Number", "Description"], [["12", "PART-1", "Sample"]])

    dry_run = dry_run_import(fake_project, source, import_type=None)

    assert dry_run.import_type == "press_capacity"
    assert dry_run.mapped_rows[0]["Machine No."] == "12"
    assert dry_run.mapped_rows[0]["NGW Part Number"] == "PART-1"
