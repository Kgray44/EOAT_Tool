from __future__ import annotations

import pytest

from core.safe_files import safe_copy_file, safe_write_text


def test_safe_write_refuses_overwrite(tmp_path):
    path = tmp_path / "report.md"
    safe_write_text(path, "one")

    with pytest.raises(FileExistsError):
        safe_write_text(path, "two")


def test_safe_copy_refuses_overwrite(tmp_path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")

    with pytest.raises(FileExistsError):
        safe_copy_file(source, target)
