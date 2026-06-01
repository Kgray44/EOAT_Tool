from __future__ import annotations

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.photo_indexing import destination_folder, intake_photos, list_incoming_photos, preview_photo_intake
from core.workbook_io import row_dicts
from core.workbook_schema import get_expected_headers


def _append_inventory_row(project_root, values: dict[str, object]) -> None:
    workbook_path = resolve_project_paths(project_root).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    row = {header: "" for header in get_expected_headers("EOAT Inventory")}
    row.update(values)
    ws.append([row.get(header, "") for header in headers])
    workbook.save(workbook_path)
    workbook.close()


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


def test_photo_move_mode_heic_and_unsupported_extension_handling(fake_project):
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    heic = incoming / "IMG_0002.HEIC"
    heic.write_bytes(b"fake heic")
    unsupported = incoming / "notes.txt"
    unsupported.write_text("not an image", encoding="utf-8")

    assert list_incoming_photos(fake_project) == [heic]
    plan = preview_photo_intake(
        fake_project, [heic, unsupported], "Plant 4", "Press 12", "2026-05-18", "Tool Connection"
    )

    assert len(plan) == 1
    assert plan[0].target.suffix == ".heic"

    result = intake_photos(
        fake_project, [heic], "Plant 4", "Press 12", "2026-05-18", "Tool Connection", copy_mode=False
    )

    assert result.success is True
    assert not heic.exists()
    assert plan[0].target.exists()


def test_photo_intake_updates_related_audit_row_and_structured_photo_fields(fake_project):
    _append_inventory_row(
        fake_project,
        {
            "Audit ID": "AUD-PHOTO-UPDATE-001",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "TOOL-12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Mechanical / Gripper",
            "Status": "Complete",
            "Photos Taken?": "No",
            "Photo Folder/Link": "",
        },
    )
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    photo = incoming / "IMG_0003.jpg"
    photo.write_bytes(b"fake jpg")

    result = intake_photos(
        fake_project,
        [photo],
        "Plant 4",
        "Press 12",
        "2026-05-18",
        "Grippers",
        related_audit_id="AUD-PHOTO-UPDATE-001",
        linked_audit_field="Gripper Model",
        copy_mode=True,
        log_activity=False,
    )

    workbook_path = resolve_project_paths(fake_project).master_workbook
    inventory = row_dicts(workbook_path, "EOAT Inventory")
    row = next(row for row in inventory if row["Audit ID"] == "AUD-PHOTO-UPDATE-001")
    photos = row_dicts(workbook_path, "Photo Index")
    photo_row = next(row for row in photos if row["Related Audit ID"] == "AUD-PHOTO-UPDATE-001")

    assert result.success is True
    assert result.metrics["audit_rows_updated"] == 1
    assert any(path.endswith(".xlsx") for path in result.files_created)
    assert row["Photos Taken?"] == "Yes"
    assert "Grippers" in str(row["Photo Folder/Link"])
    assert photo_row["Tool #"] == "TOOL-12"
    assert photo_row["Linked Audit Field"] == "Gripper Model"


def test_photo_intake_warns_when_related_audit_id_is_missing(fake_project):
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    photo = incoming / "IMG_0004.jpg"
    photo.write_bytes(b"fake jpg")

    result = intake_photos(
        fake_project,
        [photo],
        "Plant 4",
        "Press 12",
        "2026-05-18",
        "Overall EOAT",
        related_audit_id="AUD-DOES-NOT-EXIST",
        copy_mode=True,
        log_activity=False,
    )

    assert result.success is True
    assert any("Related Audit ID was not found" in warning for warning in result.warnings)
