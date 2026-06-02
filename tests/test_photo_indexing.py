from __future__ import annotations

from openpyxl import load_workbook

from core.paths import resolve_project_paths
from core.photo_evidence import photo_index_path_findings
from core.photo_indexing import destination_folder, intake_photos, list_incoming_photos, preview_photo_intake
from core.workbook_cache import invalidate_workbook_cache
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
    invalidate_workbook_cache(workbook_path)


def _delete_sheet_column(project_root, sheet_name: str, header: str) -> None:
    workbook_path = resolve_project_paths(project_root).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook[sheet_name]
    headers = [cell.value for cell in ws[1]]
    if header in headers:
        ws.delete_cols(headers.index(header) + 1)
    workbook.save(workbook_path)
    workbook.close()
    invalidate_workbook_cache(workbook_path)


def test_photo_preview_and_copy_intake(fake_project):
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    photo = incoming / "IMG_0001.jpg"
    photo.write_bytes(b"fake jpg")

    assert list_incoming_photos(fake_project) == [photo]
    plan = preview_photo_intake(
        fake_project,
        [photo],
        "Plant 4",
        "Press 12",
        "2026-05-18",
        "Overall",
        tool_number="6200171020",
    )

    assert plan[0].target.name == "Plant4_Machine12_Tool6200171020_EOAT_2026-05-18_Overall_001.jpg"

    result = intake_photos(
        fake_project,
        [photo],
        "Plant 4",
        "Press 12",
        "2026-05-18",
        "Overall",
        tool_number="6200171020",
        copy_mode=True,
    )

    assert result.success is True
    assert photo.exists()
    assert (
        destination_folder(fake_project, "Overall")
        / "Plant4_Machine12_Tool6200171020_EOAT_2026-05-18_Overall_001.jpg"
    ).exists()
    wb = load_workbook(resolve_project_paths(fake_project).master_workbook, read_only=True)
    ws = wb["Photo Index"]
    assert ws.max_row == 2
    wb.close()


def test_photo_filename_omits_blank_tool_cleanly(fake_project):
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    photo = incoming / "IMG_0001.jpg"
    photo.write_bytes(b"fake jpg")

    plan = preview_photo_intake(fake_project, [photo], "Plant 4", "12", "2026-05-18", "Overall")

    assert plan[0].target.name == "Plant4_Machine12_EOAT_2026-05-18_Overall_001.jpg"
    assert "ToolUnknown" not in plan[0].target.name
    assert "__" not in plan[0].target.name


def test_photo_collision_safe_filename(fake_project):
    folder = destination_folder(fake_project, "Sensors")
    folder.mkdir(parents=True)
    (folder / "Plant4_Machine12_Tool6200171020_EOAT_2026-05-18_Sensors_001.jpg").write_bytes(b"existing")
    photo = fake_project / "photo.jpg"
    photo.write_bytes(b"new")

    plan = preview_photo_intake(
        fake_project,
        [photo],
        "Plant 4",
        "Machine 12",
        "2026-05-18",
        "Sensors",
        tool_number="6200171020",
    )

    assert plan[0].target.name == "Plant4_Machine12_Tool6200171020_EOAT_2026-05-18_Sensors_002.jpg"


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
        tool_number="TOOL-12",
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


def test_photo_intake_appends_photo_folder_link_once(fake_project):
    _append_inventory_row(
        fake_project,
        {
            "Audit ID": "AUD-PHOTO-APPEND-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "TOOL-12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Mechanical / Gripper",
            "Photos Taken?": "No",
            "Photo Folder/Link": "existing/reference",
        },
    )
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    first = incoming / "IMG_0005.jpg"
    second = incoming / "IMG_0006.jpg"
    first.write_bytes(b"fake jpg")
    second.write_bytes(b"fake jpg")

    for photo in [first, second]:
        result = intake_photos(
            fake_project,
            [photo],
            "Plant 4",
            "Press 12",
            "2026-05-18",
            "Grippers",
            tool_number="TOOL-12",
            related_audit_id="AUD-PHOTO-APPEND-001",
            copy_mode=True,
            log_activity=False,
        )
        assert result.success is True

    row = next(
        row
        for row in row_dicts(resolve_project_paths(fake_project).master_workbook, "EOAT Inventory")
        if row["Audit ID"] == "AUD-PHOTO-APPEND-001"
    )
    folder = str(destination_folder(fake_project, "Grippers"))
    lines = [line.strip() for line in str(row["Photo Folder/Link"]).splitlines() if line.strip()]

    assert lines[0] == "existing/reference"
    assert lines.count(folder) == 1


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
    assert any("Photo Index was updated" in warning and "AUD-DOES-NOT-EXIST" in warning for warning in result.warnings)
    workbook_path = resolve_project_paths(fake_project).master_workbook
    assert any(row["Related Audit ID"] == "AUD-DOES-NOT-EXIST" for row in row_dicts(workbook_path, "Photo Index"))
    assert not any(row.get("Audit ID") == "AUD-DOES-NOT-EXIST" for row in row_dicts(workbook_path, "EOAT Inventory"))


def test_per_photo_classification_routes_to_each_shot_folder(fake_project):
    incoming = resolve_project_paths(fake_project).incoming_photos
    incoming.mkdir(parents=True)
    first = incoming / "IMG_1001.jpg"
    second = incoming / "IMG_1002.jpg"
    first.write_bytes(b"fake jpg")
    second.write_bytes(b"fake jpg")

    result = intake_photos(
        fake_project,
        [first, second],
        "Plant 4",
        "Press 12",
        "2026-05-18",
        "Overall EOAT",
        tool_number="TOOL-12",
        per_photo_metadata=[
            {"source": str(first), "view_type": "Overall EOAT", "description": "Overall evidence."},
            {"source": str(second), "view_type": "Sensors", "description": "Sensor evidence."},
        ],
        copy_mode=True,
        log_activity=False,
    )
    rows = row_dicts(resolve_project_paths(fake_project).master_workbook, "Photo Index")
    filenames = {row["EOAT Area Shown"]: row["Photo Filename"] for row in rows}

    assert result.success is True
    assert (destination_folder(fake_project, "Overall EOAT") / filenames["Overall EOAT"]).exists()
    assert (destination_folder(fake_project, "Sensors") / filenames["Sensors"]).exists()
    assert "OverallEOAT" in filenames["Overall EOAT"]
    assert "Sensors" in filenames["Sensors"]
    assert all("ToolTOOL12" in filename for filename in filenames.values())


def test_photo_index_without_tool_column_remains_valid_for_legacy_rows(fake_project):
    _delete_sheet_column(fake_project, "Photo Index", "Tool #")
    _append_inventory_row(
        fake_project,
        {
            "Audit ID": "AUD-LEGACY-PHOTO-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "TOOL-12",
            "EOAT Type": "Vacuum",
            "Photos Taken?": "Yes",
        },
    )
    folder = destination_folder(fake_project, "Overall")
    folder.mkdir(parents=True, exist_ok=True)
    photo = folder / "Plant4_Press12_EOAT_2026-05-18_Overall_001.jpg"
    photo.write_bytes(b"legacy")
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook["Photo Index"]
    headers = [cell.value for cell in ws[1]]
    values = {
        "Photo ID": "PHO-LEGACY-001",
        "Date Taken": "2026-05-18",
        "Plant/Area": "Plant 4",
        "Press/Machine #": "Press 12",
        "EOAT Area Shown": "Overall",
        "Photo Filename": photo.name,
        "Folder Path": str(folder),
        "Related Audit ID": "AUD-LEGACY-PHOTO-001",
    }
    ws.append([values.get(header, "") for header in headers])
    workbook.save(workbook_path)
    workbook.close()
    invalidate_workbook_cache(workbook_path)

    findings = photo_index_path_findings(fake_project)

    assert not any("Tool #" in finding.message and "missing" in finding.message.casefold() for finding in findings)


def test_photo_index_validation_flags_relationship_and_tool_mismatch(fake_project):
    _append_inventory_row(
        fake_project,
        {
            "Audit ID": "AUD-TOOL-MISMATCH-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "TOOL-A",
            "EOAT Type": "Vacuum",
        },
    )
    _append_inventory_row(
        fake_project,
        {
            "Audit ID": "AUD-PATH-CHECK-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 13",
            "Tool #": "TOOL-C",
            "EOAT Type": "Vacuum",
        },
    )
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook["Photo Index"]
    headers = [cell.value for cell in ws[1]]
    for values in [
        {
            "Photo ID": "PHO-MISMATCH-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 12",
            "Tool #": "TOOL-B",
            "EOAT Area Shown": "Overall",
            "Photo Filename": "missing.jpg",
            "Folder Path": str(destination_folder(fake_project, "Overall")),
            "Related Audit ID": "AUD-TOOL-MISMATCH-001",
        },
        {
            "Photo ID": "PHO-NO-AUDIT-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 14",
            "Tool #": "TOOL-D",
            "EOAT Area Shown": "Overall",
            "Photo Filename": "missing.jpg",
            "Folder Path": str(destination_folder(fake_project, "Overall")),
            "Related Audit ID": "AUD-MISSING-RELATIONSHIP",
        },
        {
            "Photo ID": "PHO-MISSING-FOLDER-001",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "Press 13",
            "Tool #": "TOOL-C",
            "EOAT Area Shown": "Overall",
            "Photo Filename": "",
            "Folder Path": "",
            "Related Audit ID": "AUD-PATH-CHECK-001",
        },
    ]:
        ws.append([values.get(header, "") for header in headers])
    workbook.save(workbook_path)
    workbook.close()
    invalidate_workbook_cache(workbook_path)

    findings = photo_index_path_findings(fake_project)

    assert any("Tool # does not match" in finding.message for finding in findings)
    assert any("Related Audit ID does not match" in finding.message for finding in findings)
    assert any("missing Photo Filename" in finding.message for finding in findings)
    assert any("missing Folder Path" in finding.message for finding in findings)
