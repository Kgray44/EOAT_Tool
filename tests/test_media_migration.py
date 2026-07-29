from __future__ import annotations

from pathlib import Path

import pytest

from tools.migration.media_migration import MediaSource, plan_media_migration, write_immutable_receipt


def _source(root: Path, name: str, content: bytes = b"image") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_media_plan_is_uuid_addressed_and_checksum_verified(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    source = _source(root, "photos/alpha.jpg")

    report = plan_media_migration(
        [MediaSource(1, "12345678-1234-1234-1234-123456789abc", "alpha.jpg", str(source), "image/jpeg")],
        source_roots=[root], target_root=tmp_path / "governed",
    )

    assert report.safe_to_execute
    item = report.items[0]
    assert item.status == "COPY"
    assert item.target_relative_path == "12/12345678-1234-1234-1234-123456789abc.jpg"
    assert item.checksum_sha256
    assert report.thumbnail_ready_count == 0  # invalid image bytes are not advertised as thumbnail-ready


def test_media_plan_refuses_source_outside_allowlist_and_target_conflict(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    outside = _source(tmp_path / "outside", "secret.jpg")
    uuid = "12345678-1234-1234-1234-123456789abc"
    target = tmp_path / "governed" / "12" / f"{uuid}.jpg"
    _source(target.parent, target.name, b"different")

    unsafe = plan_media_migration([MediaSource(1, uuid, "secret.jpg", str(outside), "image/jpeg")], source_roots=[approved], target_root=tmp_path / "governed")
    assert not unsafe.safe_to_execute and unsafe.unsafe_count == 1

    allowed = _source(approved, "allowed.jpg", b"source")
    conflict = plan_media_migration([MediaSource(1, uuid, "allowed.jpg", str(allowed), "image/jpeg")], source_roots=[approved], target_root=tmp_path / "governed")
    assert not conflict.safe_to_execute and conflict.conflict_count == 1


def test_media_receipt_is_immutable_and_does_not_leak_source_root(tmp_path: Path) -> None:
    root = tmp_path / "secret-root"
    source = _source(root, "alpha.jpg")
    report = plan_media_migration([MediaSource(1, "12345678-1234-1234-1234-123456789abc", "alpha.jpg", str(source), "image/jpeg")], source_roots=[root], target_root=tmp_path / "governed")

    receipt = write_immutable_receipt(report, tmp_path / "receipts")

    assert str(root) not in receipt.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_immutable_receipt(report, tmp_path / "receipts")
