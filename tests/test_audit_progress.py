from __future__ import annotations

from core.audit_entries import save_audit_entry
from core.audit_progress import calculate_audit_progress, generate_audit_progress_report
from core.interview_entries import save_interview_entry
from core.photo_indexing import intake_photos


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
        {"Date": "2026-05-18", "Role/Department": "Operator", "Plant/Area": "Plant 4", "Notes": "Drops parts sometimes."},
    ).success
    photo = fake_project / "photo.jpg"
    photo.write_bytes(b"fake")
    assert intake_photos(fake_project, [photo], "Plant 4", "Press 12", "2026-05-18", "Overall").success

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
