from __future__ import annotations

import pytest

from core.safe_files import backup_file, safe_copy_file, safe_write_text, timestamped_filename


def test_timestamped_filename_keeps_extension():
    name = timestamped_filename("report", ".md")

    assert name.startswith("report_")
    assert name.endswith(".md")


def test_safe_write_refuses_overwrite_without_flag(tmp_path):
    target = tmp_path / "note.txt"
    safe_write_text(target, "first")

    with pytest.raises(FileExistsError):
        safe_write_text(target, "second")


def test_backup_and_safe_copy(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    backup = backup_file(source, tmp_path / "backups")
    copied = safe_copy_file(source, tmp_path / "copy.txt")

    assert backup.exists()
    assert copied.read_text(encoding="utf-8") == "hello"

