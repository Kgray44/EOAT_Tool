from __future__ import annotations

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.photo_indexing import destination_folder, intake_photos, list_incoming_photos, preview_photo_intake


def test_photo_preview_and_copy_intake(fake_project):
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    photo = incoming / "IMG_0001.jpg"
    photo.write_bytes(b"fake jpg")

    assert list_incoming_photos(fake_project) == [photo]
    plan = preview_photo_intake(fake_project, [photo], "Plant 4", "Press 12", "2026-05-18", "Overall")

    assert plan[0].target.name == "Plant4_Press12_EOAT_2026-05-18_Overall_001.jpg"

    result = intake_photos(fake_project, [photo], "Plant 4", "Press 12", "2026-05-18", "Overall", copy_mode=True)

    assert result.success is True
    assert photo.exists()
    assert (destination_folder(fake_project, "Overall") / "Plant4_Press12_EOAT_2026-05-18_Overall_001.jpg").exists()
    wb = load_workbook(resolve_project_paths(fake_project).master_workbook, read_only=True)
    ws = wb["Photo Index"]
    assert ws.max_row == 2
    wb.close()


def test_photo_collision_safe_filename(fake_project):
    folder = destination_folder(fake_project, "Sensors")
    folder.mkdir(parents=True)
    (folder / "Plant4_Press12_EOAT_2026-05-18_Sensors_001.jpg").write_bytes(b"existing")
    photo = fake_project / "photo.jpg"
    photo.write_bytes(b"new")

    plan = preview_photo_intake(fake_project, [photo], "Plant 4", "Press 12", "2026-05-18", "Sensors")

    assert plan[0].target.name.endswith("_002.jpg")
