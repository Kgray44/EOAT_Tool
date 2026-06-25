from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.atlas import pages as atlas_pages
from app.atlas.atlas_window import PAGE_LABELS, AtlasWindow
from app.atlas.pages import SetupPacketPage, ToolListTile
from app.atlas.settings import AtlasSettings, load_atlas_settings, save_atlas_settings
from app.atlas.setup_packet_dialog import SetupPacketDialog
from core.atlas_data_loader import invalidate_atlas_data_cache, load_atlas_data
from core.atlas_models import PhotoItem, PhotoSet, ToolRecord, WarningItem
from core.atlas_setup_packets import (
    COMPATIBILITY_CONFIRMED,
    COMPATIBILITY_MANUAL_OVERRIDE,
    COMPATIBILITY_MISSING_DATA,
    COMPATIBILITY_NOT_CONFIRMED,
    COMPATIBILITY_PARTIAL,
    PACKET_TYPE_CHOICES,
    PACKET_TYPE_DOCUMENTATION_REVIEW,
    PACKET_TYPE_MAINTENANCE_PM,
    PACKET_TYPE_SETUP_VERIFICATION,
    PACKET_TYPE_STANDARD,
    PHOTO_ALL,
    PHOTO_KEY,
    PHOTO_NONE,
    SetupPacketOptions,
    build_setup_packet_context,
    packet_section_names,
    select_photos_for_packet,
    selectable_eoats,
    selectable_machines,
    selectable_tools,
    validate_setup_context,
)
from core.config import UserConfig
from core.paths import resolve_project_paths
from core.setup_packet_pdf import export_setup_packet_pdf, setup_packet_filename
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_machine_first_filtering_only_shows_compatible_tools_and_eoats(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    tools = [record.tool for record in selectable_tools(bundle, machine_id="101")]
    eoats = [record.eoat_id for record in selectable_eoats(bundle, machine_id="101", tool_id="TOOL-A")]

    assert tools == ["TOOL-A"]
    assert "TOOL-B" not in tools
    assert eoats == ["AUD-20260518-001"]


def test_tool_first_filtering_only_shows_compatible_machines_and_eoats(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    machines = [record.machine for record in selectable_machines(bundle, tool_id="TOOL-A")]
    eoats = [record.eoat_id for record in selectable_eoats(bundle, tool_id="TOOL-A", machine_id="101")]

    assert machines == ["101"]
    assert eoats == ["AUD-20260518-001"]


def test_eoat_first_filtering_only_shows_compatible_tools_and_machines(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    tools = [record.tool for record in selectable_tools(bundle, eoat_id="AUD-20260518-001")]
    machines = [record.machine for record in selectable_machines(bundle, eoat_id="AUD-20260518-001", tool_id="TOOL-A")]

    assert tools == ["TOOL-A"]
    assert machines == ["101"]


def test_incompatible_selection_is_blocked_until_override(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    blocked = selectable_eoats(bundle, machine_id="101", tool_id="TOOL-B")
    allowed = selectable_eoats(bundle, machine_id="101", tool_id="TOOL-B", allow_unconfirmed=True)

    assert blocked == ()
    assert {record.eoat_id for record in allowed} >= {"AUD-20260518-001", "AUD-20260518-002"}


def test_validation_statuses_are_correct(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    confirmed = validate_setup_context(bundle, "101", "TOOL-A", "AUD-20260518-001")
    partial = validate_setup_context(bundle, "101", "TOOL-A", "AUD-20260518-002")
    not_confirmed = validate_setup_context(bundle, "101", "TOOL-B", "AUD-20260518-003")
    missing = validate_setup_context(bundle, "999", "NO-TOOL", "NO-EOAT")
    override = validate_setup_context(bundle, "101", "TOOL-B", "AUD-20260518-003", manual_override_used=True)

    assert confirmed.status == COMPATIBILITY_CONFIRMED
    assert partial.status == COMPATIBILITY_PARTIAL
    assert not_confirmed.status == COMPATIBILITY_NOT_CONFIRMED
    assert missing.status == COMPATIBILITY_MISSING_DATA
    assert override.status == COMPATIBILITY_MANUAL_OVERRIDE
    assert any("Manual override" in warning.title for warning in override.warnings)


def test_output_filename_is_timestamped_and_safe(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    context = build_setup_packet_context(bundle, "101", "TOOL-A", "AUD-20260518-001", SetupPacketOptions())

    name = setup_packet_filename(context, timestamp="20260618_143022")

    assert name == "Setup_Packet_Machine_101_Tool_TOOL-A_EOAT_AUD-20260518-001_20260618_143022.pdf"


def test_pdf_export_creates_file(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    bundle = _bundle(tmp_path)
    context = build_setup_packet_context(
        bundle,
        "101",
        "TOOL-A",
        "AUD-20260518-001",
        SetupPacketOptions(photo_inclusion=PHOTO_NONE),
    )

    result = export_setup_packet_pdf(context)

    assert result.path.exists()
    assert result.path.suffix == ".pdf"
    assert "Setup_Packets" in str(result.path)


def test_pdf_export_packet_types_and_all_photos_get_pages(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    pytest.importorskip("PIL")
    from pypdf import PdfReader

    bundle = _bundle_with_real_photos(tmp_path)
    packet_types = [
        PACKET_TYPE_STANDARD,
        PACKET_TYPE_SETUP_VERIFICATION,
        PACKET_TYPE_MAINTENANCE_PM,
        PACKET_TYPE_DOCUMENTATION_REVIEW,
    ]
    for packet_type in packet_types:
        context = build_setup_packet_context(
            bundle,
            "101",
            "TOOL-A",
            "AUD-20260518-001",
            SetupPacketOptions(packet_type=packet_type, photo_inclusion=PHOTO_NONE),
        )
        assert export_setup_packet_pdf(context, tmp_path / "exports").path.exists()

    all_photo_context = build_setup_packet_context(
        bundle,
        "101",
        "TOOL-A",
        "AUD-20260518-001",
        SetupPacketOptions(packet_type=PACKET_TYPE_STANDARD, photo_inclusion=PHOTO_ALL),
    )
    result = export_setup_packet_pdf(all_photo_context, tmp_path / "exports")
    reader = PdfReader(str(result.path))

    assert len(all_photo_context.selected_photos) == 3
    assert len(reader.pages) >= len(all_photo_context.selected_photos) + 8


def test_photo_inclusion_modes_select_expected_photos(tmp_path: Path) -> None:
    bundle = _bundle_with_photos(tmp_path)
    eoat = bundle.eoats[0]

    assert select_photos_for_packet(eoat, SetupPacketOptions(photo_inclusion=PHOTO_NONE)) == ()
    assert len(select_photos_for_packet(eoat, SetupPacketOptions(photo_inclusion=PHOTO_KEY))) == 3
    assert len(select_photos_for_packet(eoat, SetupPacketOptions(photo_inclusion=PHOTO_ALL))) == 3


def test_packet_type_options_are_available() -> None:
    assert PACKET_TYPE_CHOICES == (
        PACKET_TYPE_STANDARD,
        PACKET_TYPE_SETUP_VERIFICATION,
        PACKET_TYPE_MAINTENANCE_PM,
        PACKET_TYPE_DOCUMENTATION_REVIEW,
    )
    assert "Compatibility Summary" in packet_section_names(SetupPacketOptions(packet_type=PACKET_TYPE_STANDARD))
    assert "Maintenance / PM Checklist" in packet_section_names(SetupPacketOptions(packet_type=PACKET_TYPE_MAINTENANCE_PM))
    assert "Documentation Score And Missing Fields" in packet_section_names(
        SetupPacketOptions(packet_type=PACKET_TYPE_DOCUMENTATION_REVIEW)
    )


def test_setup_packet_settings_persist(tmp_path: Path) -> None:
    settings_path = tmp_path / "atlas_settings.json"
    save_atlas_settings(
        AtlasSettings(
            setup_packet_default_type="maintenance_pm",
            setup_packet_photo_inclusion="all",
            setup_packet_open_after_generation="open_folder",
            setup_packet_include_qr_label=True,
            setup_packet_detail_level="detailed",
            setup_packet_allow_manual_override_combinations=True,
        ),
        settings_path,
    )

    loaded = load_atlas_settings(settings_path)

    assert loaded.setup_packet_default_type == "maintenance_pm"
    assert loaded.setup_packet_photo_inclusion == "all"
    assert loaded.setup_packet_open_after_generation == "open_folder"
    assert loaded.setup_packet_include_qr_label is True
    assert loaded.setup_packet_detail_level == "detailed"
    assert loaded.setup_packet_allow_manual_override_combinations is True


def test_manual_override_requires_explicit_confirmation(qapp, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    bundle = _bundle(tmp_path)
    dialog = SetupPacketDialog(bundle, settings=AtlasSettings(), machine_id="101", tool_id="TOOL-A", eoat_id="AUD-20260518-001")

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    dialog.confirm_override()
    assert dialog.override_confirmed is False

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    dialog.confirm_override()
    assert dialog.override_confirmed is True
    dialog.close()


def test_result_screen_actions_are_wired(qapp, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    dialog = SetupPacketDialog(bundle, settings=AtlasSettings(), machine_id="101", tool_id="TOOL-A", eoat_id="AUD-20260518-001")

    assert dialog.open_pdf_button.text() == "Open PDF"
    assert dialog.open_folder_button.text() == "Open Folder"
    assert dialog.copy_path_button.text() == "Copy File Path"
    assert dialog.regenerate_button.text() == "Regenerate"
    dialog.close()


def test_setup_packet_page_exists_in_sidebar_registry(qapp, tmp_path: Path) -> None:
    assert ("setup_packet", "Changeover Packet Builder") in PAGE_LABELS

    window = AtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False, settings=AtlasSettings())

    assert "setup_packet" in window.nav_items
    assert isinstance(window.pages["setup_packet"], SetupPacketPage)
    window.close()


def test_setup_packet_page_removes_order_dependency_and_renumbers_steps(qapp, tmp_path: Path) -> None:
    page = SetupPacketPage(_PacketControllerStub())
    text = _widget_text(page)

    assert "Select starting context" not in text
    assert "Opened from" not in text
    assert "1. Start anywhere" in text
    assert "Start anywhere. Choose a Machine, Tool/Mold/Part, or EOAT." in text
    assert "2. Compatibility Review" in text
    assert "3. Packet Options" in text
    assert "4. Generate / View PDF" in text
    assert "Reset Selection" in text


def test_open_setup_packet_switches_page_and_prefills_context(qapp, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    window = AtlasWindow(UserConfig(project_root=str(bundle.project_root)), auto_refresh=False, settings=AtlasSettings())
    window.bundle = bundle
    for page in window.pages.values():
        if hasattr(page, "set_bundle"):
            page.set_bundle(bundle)

    window.open_setup_packet(
        machine="101",
        tool="TOOL-A",
        eoat="AUD-20260518-001",
        context_label="Unit Test",
    )

    page = window.pages["setup_packet"]
    assert window.current_page_key == "setup_packet"
    assert page.machine_id == "101"
    assert page.tool_id == "TOOL-A"
    assert page.eoat_id == "AUD-20260518-001"
    assert page.context_label == "Unit Test"
    assert "Prefilled from Unit Test" in page.prefill_note.text()
    window.close()


def test_setup_packet_settings_live_on_setup_packet_page(qapp, tmp_path: Path) -> None:
    window = AtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False, settings=AtlasSettings())
    setup_page = window.pages["setup_packet"]
    diagnostics_page = window.pages["diagnostics"]

    assert hasattr(setup_page, "setup_packet_type_combo")
    assert hasattr(setup_page, "setup_packet_photo_combo")
    assert not hasattr(diagnostics_page, "setup_packet_type_combo")
    assert not hasattr(diagnostics_page, "setup_packet_photo_combo")

    setup_page.setup_packet_type_combo.setCurrentText("Maintenance / PM Packet")
    assert window.settings.setup_packet_default_type == "maintenance_pm"
    window.close()


def test_setup_packet_option_changes_use_lightweight_save_path(qapp) -> None:
    controller = _PacketControllerStub(AtlasSettings())
    page = SetupPacketPage(controller)

    page.setup_packet_type_combo.setCurrentText("Maintenance / PM Packet")
    page._packet_settings_timer.stop()
    page._flush_packet_settings()

    assert controller.settings.setup_packet_default_type == "maintenance_pm"
    assert controller.update_settings_calls == 0
    assert controller.setup_packet_update_calls == 1


def test_setup_packet_option_changes_do_not_rebuild_library_or_move_scroll(qapp) -> None:
    controller = _PacketControllerStub(AtlasSettings())
    page = SetupPacketPage(controller)
    page.resize(900, 360)
    page.show()
    qapp.processEvents()
    page.workflow_scroll.verticalScrollBar().setValue(40)
    before = page.workflow_scroll.verticalScrollBar().value()

    def fail_refresh_packet_list() -> None:
        raise AssertionError("packet list should not refresh for local option changes")

    page.refresh_packet_list = fail_refresh_packet_list
    page.setup_packet_photo_combo.setCurrentText("All photos")
    qapp.processEvents()

    assert page.workflow_scroll.verticalScrollBar().value() == before
    page.close()


def test_setup_packet_qr_checkbox_toggles_when_global_qr_enabled(qapp) -> None:
    controller = _PacketControllerStub(AtlasSettings(enable_qr_codes=True))
    page = SetupPacketPage(controller)

    assert page.setup_packet_qr_check.isEnabled()
    page.setup_packet_qr_check.setChecked(True)

    assert controller.settings.setup_packet_include_qr_label is True
    assert page.setup_packet_qr_helper.isVisible() is False


def test_setup_packet_qr_checkbox_disabled_with_helper_when_global_qr_disabled(qapp) -> None:
    page = SetupPacketPage(_PacketControllerStub(AtlasSettings(enable_qr_codes=False)))

    assert page.setup_packet_qr_check.isEnabled() is False
    assert "Enable QR Codes in Settings" in page.setup_packet_qr_helper.text()


def test_reset_selection_clears_context_but_preserves_packet_options(qapp, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    controller = _PacketControllerStub(AtlasSettings())
    page = SetupPacketPage(controller)
    page.set_bundle(bundle)
    page.setup_packet_type_combo.setCurrentText("Maintenance / PM Packet")
    page.prefill_context(machine_id="101", tool_id="TOOL-A", eoat_id="AUD-20260518-001", context_label="Tool Search")
    page.override_confirmed = True

    page.reset_selection()

    assert page.machine_id == ""
    assert page.tool_id == ""
    assert page.eoat_id == ""
    assert page.override_confirmed is False
    assert page.setup_packet_type_combo.currentText() == "Maintenance / PM Packet"
    assert "Selection incomplete" in _widget_text(page.review_card)


def test_generated_packet_becomes_latest_and_writes_sidecar(qapp, tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("reportlab")
    bundle = _bundle(tmp_path)
    controller = _PacketControllerStub(AtlasSettings(setup_packet_open_after_generation="ask_each_time"))
    page = SetupPacketPage(controller)
    page.set_bundle(bundle)
    page.prefill_context(machine_id="101", tool_id="TOOL-A", eoat_id="AUD-20260518-001")
    monkeypatch.setattr(page, "_run_open_preference", lambda: None)

    page.generate_pdf()

    assert page.last_packet_path is not None
    assert page.last_packet_path.exists()
    assert page.last_packet_path.with_suffix(".json").exists()
    assert "Machine 101" in page.latest_pdf_info.text()
    assert "Machine 101 | Tool TOOL-A | EOAT AUD-20260518-001" in page.latest_setup_label.text()
    assert "TOOL-A" in page.latest_pdf_info.text()
    assert "AUD-20260518-001" in page.latest_pdf_info.text()
    assert page.latest_open_pdf_button.text() == "Open"
    assert page.latest_open_folder_button.text() == "Folder"
    assert "No previous changeover packet exports found." in _list_text(page.packet_list)


def test_packet_library_parses_sidecar_and_filename_metadata(tmp_path: Path) -> None:
    pdf = tmp_path / "Setup_Packet_Machine_101_Tool_TOOL-A_EOAT_AUD-20260518-001_20260618_143022.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    pdf.with_suffix(".json").write_text(
        '{"machine":"999","tool":"SIDE","eoat":"EOAT-SIDE","packet_type":"Documentation Review Packet",'
        '"photo_inclusion":"All photos","compatibility_status":"Manual Override Used","manual_override_used":true}',
        encoding="utf-8",
    )

    metadata = atlas_pages._setup_packet_metadata(pdf)
    rows = dict(atlas_pages._setup_packet_pdf_metadata_rows(pdf))

    assert metadata["machine"] == "999"
    assert rows["Packet type"] == "Documentation Review Packet"
    assert rows["Manual override"] == "Yes"
    assert "2026-06-18" in atlas_pages._setup_packet_pdf_row_summary(pdf)


def test_previous_packets_list_uses_cards_and_skips_latest(qapp, tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    page = SetupPacketPage(_PacketControllerStub())
    page.set_bundle(bundle)
    folder = Path(bundle.project_root) / "06_Final_Handoff" / "Atlas_Exports" / "Setup_Packets"
    folder.mkdir(parents=True, exist_ok=True)
    latest = folder / "Setup_Packet_Machine_101_Tool_TOOL-A_EOAT_AUD-20260518-001_20260618_143022.pdf"
    previous = folder / "Setup_Packet_Machine_102_Tool_TOOL-B_EOAT_AUD-20260518-002_20260618_133022.pdf"
    latest.write_bytes(b"%PDF-1.4\n%%EOF\n")
    previous.write_bytes(b"%PDF-1.4\n%%EOF\n")
    page._set_latest_packet(latest)

    page.refresh_packet_list()

    assert page.packet_list.count() == 1
    row = page.packet_list.itemWidget(page.packet_list.item(0))
    assert row is not None
    assert "Machine 102 | Tool TOOL-B | EOAT AUD-20260518-002" in _widget_text(row)
    assert "TOOL-B" in _widget_text(row)
    assert "TOOL-A" not in _list_text(page.packet_list)


def test_view_in_app_action_uses_modal_for_previous_packets(qapp, tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "Setup_Packet_Machine_101_Tool_TOOL-A_EOAT_AUD-20260518-001_20260618_143022.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    page = SetupPacketPage(_PacketControllerStub())
    opened = []

    class FakeDialog:
        def __init__(self, path, parent=None):
            opened.append(Path(path))

        def exec(self):
            return 0

    monkeypatch.setattr(atlas_pages, "_SetupPacketPdfViewerDialog", FakeDialog)

    page.view_packet_in_app(pdf)

    assert opened == [pdf]
    assert page.last_packet_path == pdf
    assert page.view_in_app_button.text() == "View"
    assert page.latest_open_pdf_button.text() == "Open"
    assert page.latest_open_folder_button.text() == "Folder"
    assert page.latest_copy_path_button.text() == "Copy Path"


def test_pdf_viewer_dialog_prioritizes_pdf_with_metadata_sidebar(qapp, tmp_path: Path) -> None:
    pdf = tmp_path / "Setup_Packet_Machine_101_Tool_TOOL-A_EOAT_AUD-20260518-001_20260618_143022.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    dialog = atlas_pages._SetupPacketPdfViewerDialog(pdf)

    assert dialog.viewer_splitter.count() == 2
    assert dialog.viewer_splitter.widget(0) is dialog.metadata_sidebar
    assert dialog.viewer_splitter.widget(1) is dialog.viewer
    assert dialog.metadata_sidebar.minimumWidth() >= 280
    dialog.close()


def test_pdf_viewer_loads_pdf_when_qtpdf_is_available(qapp, tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    if atlas_pages.QPdfDocument is None:
        pytest.skip("QtPdf is unavailable")
    bundle = _bundle(tmp_path)
    context = build_setup_packet_context(
        bundle,
        "101",
        "TOOL-A",
        "AUD-20260518-001",
        SetupPacketOptions(photo_inclusion=PHOTO_NONE),
    )
    result = export_setup_packet_pdf(context, tmp_path)
    viewer = atlas_pages._SetupPacketPdfViewer()

    viewer.load_pdf(result.path)

    assert viewer.document is not None
    assert viewer.document.pageCount() > 0


def test_pdf_viewer_fallback_only_when_qtpdf_unavailable(qapp, monkeypatch) -> None:
    monkeypatch.setattr(atlas_pages, "QPdfDocument", None)
    monkeypatch.setattr(atlas_pages, "QPdfView", None)

    viewer = atlas_pages._SetupPacketPdfViewer()

    assert "Embedded PDF viewer is unavailable in this build." in viewer.message.text()


def test_tool_card_size_hint_prevents_bottom_chip_clipping(qapp) -> None:
    tool = ToolRecord(
        tool="TOOL-LONG",
        label="Tool TOOL-LONG",
        compatible_machines=("101", "102", "103"),
        compatible_eoats=("EOAT-A", "EOAT-B", "EOAT-C", "EOAT-D"),
        warnings=(WarningItem("warn", "Tool warning", "Review this tool."),),
        part_description="Long molded part with linked EOAT chips",
    )

    regular = ToolListTile(tool, compact=False, compare_callback=lambda _checked: None, recent=True)
    compact = ToolListTile(tool, compact=True, compare_callback=lambda _checked: None, recent=True)

    assert regular.sizeHint().height() >= 166
    assert regular.minimumHeight() >= 166
    assert compact.sizeHint().height() >= 130
    assert compact.minimumHeight() >= 130


def _widget_text(widget) -> str:
    texts = []
    for child in [*widget.findChildren(atlas_pages.QLabel), *widget.findChildren(atlas_pages.QPushButton)]:
        value = child.text()
        if value:
            texts.append(value)
    return "\n".join(texts)


def _list_text(list_widget) -> str:
    parts = []
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        parts.append(item.text())
        row = list_widget.itemWidget(item)
        if row is not None:
            parts.append(_widget_text(row))
    return "\n".join(parts)


class _PacketControllerStub:
    def __init__(self, settings: AtlasSettings | None = None):
        self.settings = settings or AtlasSettings()
        self.status_messages: list[str] = []
        self.update_settings_calls = 0
        self.setup_packet_update_calls = 0

    def update_settings(self, settings: AtlasSettings) -> None:
        self.update_settings_calls += 1
        self.settings = settings.normalized()

    def update_setup_packet_settings(self, settings: AtlasSettings) -> None:
        self.setup_packet_update_calls += 1
        self.settings = settings.normalized()

    def show_status(self, message: str) -> None:
        self.status_messages.append(message)


def _bundle(tmp_path: Path):
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(resolve_project_paths(root).reference_data)
    invalidate_atlas_data_cache(root)
    return load_atlas_data(root, force_refresh=True)


def _bundle_with_photos(tmp_path: Path):
    bundle = _bundle(tmp_path)
    photo_dir = Path(bundle.project_root) / "01_EOAT_Audit" / "Cell_Photos" / "P4-EOAT-TEST"
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo_paths = [
        photo_dir / "overall_eoat.png",
        photo_dir / "tubing_routing.png",
        photo_dir / "sensor_detail.png",
    ]
    for path in photo_paths:
        path.write_bytes(b"fake image bytes")
    photos = tuple(
        PhotoItem(path=str(path), filename=path.name, category=path.stem.replace("_", " "))
        for path in photo_paths
    )
    eoat = replace(
        bundle.eoats[0],
        photos=PhotoSet(eoat_id=bundle.eoats[0].eoat_id, folder_path=str(photo_dir), folder_exists=True, photos=photos),
    )
    return replace(bundle, eoats=tuple([eoat, *bundle.eoats[1:]]))


def _bundle_with_real_photos(tmp_path: Path):
    from PIL import Image

    bundle = _bundle(tmp_path)
    photo_dir = Path(bundle.project_root) / "01_EOAT_Audit" / "Cell_Photos" / "P4-EOAT-TEST"
    photo_dir.mkdir(parents=True, exist_ok=True)
    photo_specs = [
        ("overall_eoat.png", "#2f80ed"),
        ("tubing_routing.png", "#087f5b"),
        ("sensor_detail.png", "#d80621"),
    ]
    photos = []
    for filename, color in photo_specs:
        path = photo_dir / filename
        Image.new("RGB", (640, 420), color).save(path)
        photos.append(PhotoItem(path=str(path), filename=path.name, category=path.stem.replace("_", " ")))
    eoat = replace(
        bundle.eoats[0],
        photos=PhotoSet(eoat_id=bundle.eoats[0].eoat_id, folder_path=str(photo_dir), folder_exists=True, photos=tuple(photos)),
    )
    return replace(bundle, eoats=tuple([eoat, *bundle.eoats[1:]]))
