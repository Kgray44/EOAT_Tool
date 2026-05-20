from __future__ import annotations

from core.reports import read_report_preview, report_folders


def test_report_preview_reads_text_file(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# Hello", encoding="utf-8")

    text, warning = read_report_preview(report)

    assert warning is None
    assert "# Hello" in text


def test_report_folders_handles_missing_project(tmp_path):
    folders = report_folders(tmp_path)

    assert {folder.label for folder in folders} >= {"Daily Status Reports", "Validation Reports", "Activity Logs"}

