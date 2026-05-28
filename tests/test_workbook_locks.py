from __future__ import annotations

from openpyxl import Workbook

from core.workbook_locks import detect_workbook_lock


def test_workbook_lock_detector_allows_writable_workbook(tmp_path):
    path = tmp_path / "EOAT_Master_Tracker.xlsx"
    workbook = Workbook()
    workbook.save(path)
    workbook.close()

    status = detect_workbook_lock(path)

    assert status.exists
    assert status.can_write
    assert not status.locked


def test_workbook_lock_detector_detects_office_lock_file(tmp_path):
    path = tmp_path / "EOAT_Master_Tracker.xlsx"
    workbook = Workbook()
    workbook.save(path)
    workbook.close()
    path.with_name("~$EOAT_Master_Tracker.xlsx").write_text("", encoding="utf-8")

    status = detect_workbook_lock(path)

    assert status.exists
    assert status.locked
    assert not status.can_write
    assert "Office" in status.message
