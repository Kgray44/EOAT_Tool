from __future__ import annotations

from openpyxl import Workbook

from core.audit_entries import save_audit_entry
from core.audit_progress import calculate_audit_progress, generate_audit_progress_report
from core.eoat_ids import EOAT_ASSEMBLY_ID_FIELD
from core.interview_entries import save_interview_entry
from core.paths import get_press_capacity_file
from core.photo_indexing import intake_photos


def _write_press_capacity(project_root, rows):
    path = get_press_capacity_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Capacity"
    ws.append(["Machine No.", "NGW Part Number", "NGW Part Description"])
    for machine_cell, part_number, description in rows:
        ws.append([machine_cell, part_number, description])
    workbook.save(path)
    workbook.close()
    return path


def test_audit_progress_metrics_and_report(fake_project):
    assert save_audit_entry(
        fake_project,
        {
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "EOAT Moves": "Part",
            "Status": "Audited",
            "Pilot Candidate?": "Yes",
        },
    ).success
    assert save_interview_entry(
        fake_project,
        {
            "Date": "2026-05-18",
            "Role/Department": "Operator",
            "Plant/Area": "Plant 4",
            "Notes": "Drops parts sometimes.",
        },
    ).success
    photo = fake_project / "photo.jpg"
    photo.write_bytes(b"fake")
    assert intake_photos(
        fake_project, [photo], "Plant 4", "Press 12", "2026-05-18", "Front View", tool_number="TOOL-12"
    ).success

    summary, error = calculate_audit_progress(fake_project)
    assert error is None
    assert summary.metrics["total_eoat_inventory_rows"] == 1
    assert summary.metrics["audited_eoat_count"] == 1
    assert summary.metrics["photos_indexed_count"] == 1
    assert summary.metrics["interviews_logged_count"] == 1
    assert summary.missing_field_counts["EOAT Moves"] == 0

    result = generate_audit_progress_report(fake_project)
    assert result.success is True
    assert result.output_reports


def test_audit_progress_tracks_missing_eoat_moves(fake_project):
    assert save_audit_entry(
        fake_project,
        {
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Status": "Audited",
        },
    ).success

    summary, error = calculate_audit_progress(fake_project)

    assert error is None
    assert summary.missing_field_counts["EOAT Moves"] == 1


def test_audit_progress_missing_workbook(tmp_path):
    summary, error = calculate_audit_progress(tmp_path)

    assert summary is None
    assert error is not None
    assert error.success is False


def test_audit_progress_counts_multi_tool_eoats(fake_project):
    _write_press_capacity(
        fake_project,
        [
            ("26, 31", "5116830010", "Tool A"),
            ("26, 44", "5116830020", "Tool B"),
        ],
    )
    for tool in ["5116830010", "5116830020"]:
        assert save_audit_entry(
            fake_project,
            {
                "Audit Date": "2026-06-08",
                "Auditor": "KG",
                "Plant/Area": "Plant 4",
                "Press/Machine #": "26",
                EOAT_ASSEMBLY_ID_FIELD: "P4-EOAT-0007",
                "Tool #": tool,
                "Robot Type": "Wittmann R9",
                "EOAT Type": "Vacuum",
                "Status": "Audited",
            },
        ).success

    summary, error = calculate_audit_progress(fake_project)

    assert error is None
    assert summary.metrics["multi_tool_eoat_count"] == 1
    assert summary.metrics["total_eoat_tool_links"] >= 2
    assert summary.multi_tool_eoats[0]["EOAT Assembly ID"] == "P4-EOAT-0007"
    assert summary.multi_tool_eoats[0]["Audit Machine #s"] == "26"
    assert summary.multi_tool_eoats[0]["Press Capacity Machine #s"] == "26, 31, 44"
    assert summary.multi_tool_eoats[0]["Machine #s"] == "26, 31, 44"
    compatibility_row = next(
        row for row in summary.eoat_machine_compatibility if row["EOAT Assembly ID"] == "P4-EOAT-0007"
    )
    assert compatibility_row["Press Capacity Machine #s"] == "26, 31, 44"
