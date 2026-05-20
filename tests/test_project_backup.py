from __future__ import annotations

import zipfile

from core.project_backup import backup_project


def test_workbook_backup_creates_copy(fake_project):
    result = backup_project(fake_project, mode="workbook")

    assert result.success is True
    assert result.files_created[0].endswith(".xlsx")


def test_light_backup_creates_zip(fake_project):
    (fake_project / "notes.md").write_text("hello", encoding="utf-8")
    result = backup_project(fake_project, mode="light")

    assert result.success is True
    zip_path = result.files_created[0]
    assert zip_path.endswith(".zip")
    with zipfile.ZipFile(zip_path) as archive:
        assert "notes.md" in archive.namelist()
