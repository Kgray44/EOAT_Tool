from __future__ import annotations

import time
import threading
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from core.atlas_models import AtlasDataBundle, AtlasIndexes, DocumentationStatus, EOATRecord, MachineRecord, PhotoItem, PhotoSet, ToolRecord
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.atlas_data_loader import _current_eoat_for_rows, _current_eoat_resolution_for_rows
from core.atlas_record_details import RecordDetailData, RecordField, RecordPhoto, RecordPhotoGroup
from core.library_data_service import LibraryDataService
from core.photos.photo_service import PhotoService

from app.atlas.minimalist.library import (
    AtlasMinimalistLibraryPage,
    ENTITY_EOAT,
    ENTITY_MACHINE,
    ENTITY_TOOL,
    SEARCH_DEBOUNCE_MS,
    AtlasRecordCard,
    CopyIdButton,
    LibraryCatalog,
    LibraryBrowseStateView,
    LibraryRecordStateView,
    MinimalistLibraryContent,
    EntityPortrait,
    PhotoGalleryCard,
    PhotoGroupSection,
    PhotoLightboxOverlay,
    PDFOptionsOverlay,
    PDFPreviewOverlay,
    PhotoTile,
    RecordHeroPanel,
    RecordOverviewTab,
    RecordTabBar,
    RelationshipOverviewPanel,
    SummaryMetricsPanel,
    MetricBlock,
    atlas_card_metrics,
    machine_current_eoat_display,
    parse_eoat_id,
    record_status_display,
)
from app.atlas.minimalist.home import AtlasMinimalistHomePage
from app.atlas.minimalist.widgets import TopChromeFade
from core.reporting.pdf_preview_session import PdfPreviewSession


def test_library_catalog_searches_records_by_relationship_ids(tmp_path: Path) -> None:
    bundle = _library_bundle(tmp_path)
    catalog = LibraryCatalog(bundle, controller=_Controller())

    results = catalog.filtered(query="52")
    keys = {(entity.entity_type, entity.key) for entity in results}

    assert ("eoat", "P4-EOAT-0052") in keys
    assert ("machine", "52") in keys
    assert ("tool", "6201510010") in keys


def test_library_data_service_rebuilds_cache_and_serves_maps(tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))

    assert service.is_index_ready()
    assert (tmp_path / "00_Project_Admin" / "cache" / "library_index.json").exists()
    assert service.get_record("eoat", "P4-EOAT-0052")["eoat_id"] == "P4-EOAT-0052"
    assert service.get_relationships("eoat", "P4-EOAT-0052")["machines"] == ["36", "52"]
    assert len(service.get_photos("eoat", "P4-EOAT-0052")) == 1

    reloaded = LibraryDataService(tmp_path)
    reloaded.load_cached_index()
    assert reloaded.is_index_ready()
    assert reloaded.get_relationships("machine", "52")["current_eoat"] == "P4-EOAT-0052"


def test_eoat_card_preview_selects_front_view_from_cached_photo_metadata(tmp_path: Path) -> None:
    side = PhotoItem(path=str(tmp_path / "side.png"), filename="side.png", photo_type="02_Side_View")
    front = PhotoItem(path=str(tmp_path / "front.png"), filename="front.png", photo_type="01_Front_View")
    bundle = _library_bundle_with_photos(tmp_path, (side, front))
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(bundle)

    record = service.get_record(ENTITY_EOAT, "P4-EOAT-0052")
    assert record is not None
    assert record["preview_photo_type"] == "01_Front_View"
    assert any(path.endswith("front.png") for path in record["preview_photo_path_candidates"])

    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service)
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None
    candidates = catalog.photo_candidates(entity, limit=1)
    assert len(candidates) == 1
    assert any(path.endswith("front.png") for path in candidates[0][1])


def test_eoat_card_preview_falls_back_to_overview_then_icon(tmp_path: Path) -> None:
    overview = PhotoItem(path=str(tmp_path / "overview.png"), filename="overview.png", photo_type="Overall")
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle_with_photos(tmp_path, (overview,)))

    record = service.get_record(ENTITY_EOAT, "P4-EOAT-0052")
    assert record is not None
    assert record["preview_photo_type"] == "Overall"
    assert any(path.endswith("overview.png") for path in record["preview_photo_path_candidates"])

    empty_service = LibraryDataService(tmp_path / "empty")
    empty_service.rebuild_index_from_bundle(_library_bundle_with_photos(tmp_path / "empty", ()))
    empty_record = empty_service.get_record(ENTITY_EOAT, "P4-EOAT-0052")
    assert empty_record is not None
    assert empty_record["preview_photo_path_candidates"] == []

    catalog = LibraryCatalog(None, controller=_Controller(), data_service=empty_service)
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None
    assert catalog.photo_candidates(entity, limit=1) == []


def test_eoat_profile_hero_requests_front_view_photo_async(qapp, tmp_path: Path) -> None:
    side = PhotoItem(path=str(tmp_path / "side.png"), filename="side.png", photo_type="Side View")
    front = PhotoItem(path=str(tmp_path / "front.png"), filename="front.png", photo_type="01_Front_View")
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle_with_photos(tmp_path, (side, front)))
    photo_service = _RecordingPhotoService()
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service, photo_service=photo_service)
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None
    detail = service.get_record_detail_data(ENTITY_EOAT, entity.key)

    hero = RecordHeroPanel(entity, catalog, detail, lambda: None)
    portrait = hero.findChild(EntityPortrait)
    assert portrait is not None
    qapp.processEvents()

    assert photo_service.thumbnail_requests
    photo_id, paths, size, _priority, context_id = photo_service.thumbnail_requests[0]
    assert size == (512, 512)
    assert any(path.endswith("front.png") for path in paths)
    image = QImage(96, 72, QImage.Format.Format_RGB32)
    image.fill(QColor("#235f9e"))
    photo_service.thumbnail_ready.emit(photo_id, image, paths[0], context_id)

    assert _wait_for_qt(qapp, lambda: portrait.pixmap is not None and not portrait.pixmap.isNull(), timeout_ms=500)
    _cleanup_widget(qapp, hero)


def test_eoat_profile_hero_uses_cached_prefetch_immediately(qapp, tmp_path: Path) -> None:
    front = PhotoItem(path=str(tmp_path / "front.png"), filename="front.png", photo_type="01_Front_View")
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle_with_photos(tmp_path, (front,)))
    photo_service = _RecordingPhotoService()
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service, photo_service=photo_service)
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None
    photo_id = catalog.photo_candidates(entity, limit=1)[0][0]
    image = QImage(512, 512, QImage.Format.Format_RGB32)
    image.fill(QColor("#235f9e"))
    photo_service.cached_thumbnails[(photo_id, (512, 512))] = image

    hero = RecordHeroPanel(entity, catalog, service.get_record_detail_data(ENTITY_EOAT, entity.key), lambda: None)
    portrait = hero.findChild(EntityPortrait)
    assert portrait is not None

    assert portrait.pixmap is not None
    assert not portrait.pixmap.isNull()
    assert photo_service.thumbnail_requests == []
    _cleanup_widget(qapp, hero)


def test_visible_eoat_cards_prefetch_hero_thumbnail(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    photo_service = _RecordingPhotoService()
    page.photo_service = photo_service
    page.catalog.photo_service = photo_service
    page.set_bundle(_library_bundle(tmp_path))
    qapp.processEvents()

    view = page.current_view
    assert isinstance(view, LibraryBrowseStateView)
    assert any(request[2] == (512, 512) and request[3] == 70 and request[4].endswith(":hero") for request in photo_service.thumbnail_requests)
    assert not any(request[2] == (512, 512) and request[0].startswith("machine") for request in photo_service.thumbnail_requests)
    _cleanup_widget(qapp, page)


def test_hover_or_focus_eoat_card_prefetches_hero_thumbnail(qapp, tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    photo_service = _RecordingPhotoService()
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service, photo_service=photo_service)
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None
    card = AtlasRecordCard(entity, catalog)
    card.show()
    qapp.processEvents()
    photo_service.thumbnail_requests.clear()

    card._prefetch_hover_hero_photo()
    qapp.processEvents()

    assert any(request[2] == (512, 512) and request[3] == 85 and request[4] == "library:eoat_card_hover:P4-EOAT-0052" for request in photo_service.thumbnail_requests)
    _cleanup_widget(qapp, card)


def test_tool_and_machine_hero_icons_do_not_request_eoat_photo(qapp, tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    photo_service = _RecordingPhotoService()
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service, photo_service=photo_service)
    for entity_type, key in ((ENTITY_TOOL, "6201510010"), (ENTITY_MACHINE, "52")):
        entity = catalog.entity_for(entity_type, key)
        assert entity is not None
        detail = service.get_record_detail_data(entity_type, key)
        hero = RecordHeroPanel(entity, catalog, detail, lambda: None)
        qapp.processEvents()
        _cleanup_widget(qapp, hero)

    assert photo_service.thumbnail_requests == []


def test_profile_copy_button_copies_each_primary_identifier_and_updates_toast(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.show()
    qapp.processEvents()

    cases = (
        (ENTITY_EOAT, "P4-EOAT-0052", "P4-EOAT-0052", "Copy EOAT ID"),
        (ENTITY_TOOL, "6201510010", "6201510010", "Copy Tool #"),
        (ENTITY_MACHINE, "52", "Machine 52", "Copy Machine #"),
    )
    for entity_type, key, copied_value, accessible_name in cases:
        assert page.select_entity(entity_type, key) is True
        qapp.processEvents()
        button = page.findChild(CopyIdButton)
        assert button is not None
        assert button.accessibleName() == accessible_name
        assert button.toolTip() == accessible_name
        assert button.width() == 28
        assert button.height() == 28
        assert button.icon().isNull()
        hero = page.findChild(RecordHeroPanel)
        title = hero.findChild(QLabel, "RecordHeroTitle") if hero is not None else None
        assert hero is not None
        assert title is not None
        title_top = title.mapTo(hero, QPoint(0, 0)).y()
        button_top = button.mapTo(hero, QPoint(0, 0)).y()
        assert 3 <= button_top - title_top <= 8

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        assert QApplication.clipboard().text() == copied_value
        assert page.toast.label.text() == f"Copied {copied_value} to clipboard"

    _cleanup_widget(qapp, page)


def test_profile_copy_button_supports_keyboard_activation(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.show()
    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    qapp.processEvents()
    button = page.findChild(CopyIdButton)
    assert button is not None

    QApplication.clipboard().clear()
    button.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(button, Qt.Key.Key_Return)
    qapp.processEvents()

    assert QApplication.clipboard().text() == "P4-EOAT-0052"
    assert page.toast.label.text() == "Copied P4-EOAT-0052 to clipboard"
    _cleanup_widget(qapp, page)


def test_machine_card_uses_icon_and_does_not_request_thumbnail(qapp, tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    photo_service = _RecordingPhotoService()
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service, photo_service=photo_service)
    entity = catalog.entity_for(ENTITY_MACHINE, "52")
    assert entity is not None
    assert catalog.photo_count(entity) > 0
    assert catalog.photo_candidates(entity, limit=1) == []

    card = AtlasRecordCard(entity, catalog)
    qapp.processEvents()

    assert card._thumbnail is None
    assert photo_service.thumbnail_requests == []
    _cleanup_widget(qapp, card)


def test_only_eoat_card_requests_large_async_thumbnail(qapp, tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    photo_service = _RecordingPhotoService()
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service, photo_service=photo_service)
    eoat = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    tool = catalog.entity_for(ENTITY_TOOL, "6201510010")
    assert eoat is not None
    assert tool is not None
    assert catalog.photo_candidates(eoat, limit=1)
    assert catalog.photo_candidates(tool, limit=1)

    eoat_card = AtlasRecordCard(eoat, catalog, variant="compact")
    tool_card = AtlasRecordCard(tool, catalog, variant="compact")
    qapp.processEvents()

    assert eoat_card._thumbnail_photo_id
    assert tool_card._thumbnail_photo_id == ""
    assert photo_service.thumbnail_requests[0][2] == (384, 256)
    assert len(photo_service.thumbnail_requests) == 1
    assert eoat_card._card_location_line() == "Plant 4 / Production"
    assert tool_card._card_location_line() == "Plant 4 / Production"
    _cleanup_widget(qapp, eoat_card)
    _cleanup_widget(qapp, tool_card)


def test_record_cards_use_shared_metadata_slots(qapp, tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service)
    machine = catalog.entity_for(ENTITY_MACHINE, "52")
    tool = catalog.entity_for(ENTITY_TOOL, "6201510010")
    assert machine is not None
    assert tool is not None

    machine_card = AtlasRecordCard(machine, catalog, variant="compact")
    tool_card = AtlasRecordCard(tool, catalog, variant="compact")

    assert machine_card.entity.subtitle == "Engel Viper"
    assert machine_card._bottom_left_icon() == "eoat"
    assert machine_card._card_location_line() == "Production"
    assert machine_card._thumbnail_photo_id == ""
    assert tool_card._bottom_left_icon() == "machine"
    assert tool_card._card_location_line() == "Plant 4 / Production"
    assert tool_card._thumbnail_photo_id == ""
    _cleanup_widget(qapp, machine_card)
    _cleanup_widget(qapp, tool_card)


def test_record_card_click_and_keyboard_activation_use_whole_card(qapp, tmp_path: Path) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service)
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None

    card = AtlasRecordCard(entity, catalog)
    card.resize(card.sizeHint())
    card.show()
    qapp.processEvents()
    clicked: list[str] = []
    card.clicked.connect(lambda: clicked.append("open"))

    QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(card.width() - 12, card.height() - 12))
    card.setFocus(Qt.FocusReason.TabFocusReason)
    qapp.processEvents()
    QTest.keyClick(card, Qt.Key.Key_Return)
    QTest.keyClick(card, Qt.Key.Key_Space)

    assert card.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert card.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert not hasattr(card, "_draw_arrow_button")
    assert clicked == ["open", "open", "open"]
    _cleanup_widget(qapp, card)


def test_library_data_service_handles_corrupt_cache_without_crashing(tmp_path: Path, monkeypatch) -> None:
    service = LibraryDataService(tmp_path)
    assert service.cache_path is not None
    assert service.meta_path is not None
    service.cache_path.parent.mkdir(parents=True, exist_ok=True)
    service.cache_path.write_text("{not-json", encoding="utf-8")
    service.meta_path.write_text("{}", encoding="utf-8")
    scheduled: list[bool] = []
    monkeypatch.setattr(service, "rebuild_index_in_background", lambda: scheduled.append(True))

    service.load_cached_index()

    assert scheduled == [True]
    assert not service.is_index_ready()


def test_minimalist_library_local_search_and_selection(qapp, tmp_path: Path) -> None:
    controller = _Controller()
    page = MinimalistLibraryContent(controller)
    page.set_bundle(_library_bundle(tmp_path))

    page.focus_search_text("52")
    qapp.processEvents()

    assert page.controls.search_bar.input.text() == "52"
    assert page.select_entity("eoat", "P4-EOAT-0052") is True
    assert page.selected_entity is not None
    assert page.selected_entity.key == "P4-EOAT-0052"
    assert ("eoat", "P4-EOAT-0052") in controller.recent
    _cleanup_widget(qapp, page)


def test_record_open_uses_cached_detail_data(qapp, tmp_path: Path, monkeypatch) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_library_bundle(tmp_path))

    def fail_detail_builder(*_args, **_kwargs):
        raise AssertionError("record open should use LibraryDataService cache")

    monkeypatch.setattr("app.atlas.minimalist.library.build_record_detail_data", fail_detail_builder)

    assert page.select_entity("eoat", "P4-EOAT-0052") is True
    qapp.processEvents()
    assert page.current_view is not None
    assert page.current_view.objectName() == "LibraryRecordStateView"
    _cleanup_widget(qapp, page)


def test_record_cards_skip_synchronous_photo_path_lookup(qapp, tmp_path: Path, monkeypatch) -> None:
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle(tmp_path))
    catalog = LibraryCatalog(None, controller=_Controller(), data_service=service)
    entity = catalog.entity_for("eoat", "P4-EOAT-0052")
    assert entity is not None

    def fail_photo_paths(*_args, **_kwargs):
        raise AssertionError("card construction should not resolve photo paths")

    monkeypatch.setattr(catalog, "photo_paths", fail_photo_paths)
    card = AtlasRecordCard(entity, catalog)
    assert card._thumbnail is None


def test_minimalist_library_browse_categories_render_record_cards(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_library_bundle(tmp_path))

    for scope in (ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE):
        page.active_lenses = {"Cleanroom"}
        page._show_browse(scope)
        qapp.processEvents()

        assert page.state == "browse"
        assert page.scope_type == scope
        assert page.active_lenses == set()
        assert page.current_view is not None
        cards = page.current_view.findChildren(AtlasRecordCard)
        assert cards, f"{scope} browse should render at least one record card"
        assert all(card.sizeHint().height() >= 220 for card in cards)
    _cleanup_widget(qapp, page)


def test_browse_refresh_does_not_leave_stacked_stale_cards(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_multi_tool_bundle(tmp_path, count=12))
    page._show_browse(ENTITY_MACHINE)
    view = page.current_view
    assert view is not None
    page.show()
    qapp.processEvents()
    view.resize(1320, 720)
    view.refresh()
    view.refresh()
    view.layout().activate()
    view.grid_layout.activate()
    qapp.processEvents()

    cards = view.findChildren(AtlasRecordCard)
    geometries = [(card.geometry().x(), card.geometry().y()) for card in cards]
    assert len(cards) >= 2
    assert len(set(geometries)) == len(geometries)
    _cleanup_widget(qapp, page)


def test_tool_browse_grid_uses_full_card_rows_without_overlap(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_multi_tool_bundle(tmp_path, count=12))
    page._show_browse(ENTITY_TOOL)
    view = page.current_view
    assert view is not None

    page.show()
    qapp.processEvents()
    view.resize(1320, 720)
    view.refresh()
    view.layout().activate()
    view.grid_layout.activate()
    qapp.processEvents()

    cards = view.findChildren(AtlasRecordCard)
    assert len(cards) == 12
    assert view._rendered_columns == 3
    assert all(card.geometry().height() >= 220 for card in cards)
    for index, card in enumerate(cards):
        for other in cards[index + 1 :]:
            assert not card.geometry().intersects(other.geometry())
    _cleanup_widget(qapp, page)


def test_browse_renders_only_current_page_and_cancels_thumbnail_context(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_multi_tool_bundle(tmp_path, count=18))
    page._show_browse(ENTITY_TOOL)
    page.show()
    qapp.processEvents()
    view = page.current_view
    assert view is not None
    view.resize(1320, 720)
    view.refresh()
    qapp.processEvents()

    cards = view.findChildren(AtlasRecordCard)
    assert view._last_filtered_count == 18
    assert view._last_page_size == 8
    assert len(cards) == 8
    assert len(cards) < view._last_filtered_count

    cancelled: list[str] = []
    original_cancel = page.photo_service.cancel_context

    def record_cancel(context_id: str) -> None:
        cancelled.append(context_id)
        original_cancel(context_id)

    page.photo_service.cancel_context = record_cancel
    old_keys = view._last_rendered_keys
    view._change_page(1)
    qapp.processEvents()

    assert view.page_index == 1
    assert view._last_rendered_keys != old_keys
    assert len(view.findChildren(AtlasRecordCard)) == 8
    assert any(context.startswith("library:tool") for context in cancelled)
    _cleanup_widget(qapp, page)


def test_eoat_browse_uses_numeric_id_sort_for_first_page(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_eoat_sequence_bundle(tmp_path))
    page._show_browse(ENTITY_EOAT)
    page.show()
    qapp.processEvents()

    view = page.current_view
    assert isinstance(view, LibraryBrowseStateView)
    view.resize(1600, 900)
    view.refresh(reset_page=True)
    qapp.processEvents()

    visible_keys = [key for entity_type, key in view._last_rendered_keys]
    assert visible_keys[:8] == [f"P4-EOAT-{number:04d}" for number in range(1, 9)]
    assert "CL-EOAT-0043" not in visible_keys[:8]
    assert view.page_label.text().startswith("Showing 1-8 of")
    _cleanup_widget(qapp, page)


def test_eoat_sort_is_consistent_between_grid_list_and_search_reset(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_eoat_sequence_bundle(tmp_path))
    page._show_browse(ENTITY_EOAT)
    qapp.processEvents()
    view = page.current_view
    assert isinstance(view, LibraryBrowseStateView)
    view.resize(1600, 900)
    view.refresh(reset_page=True)
    qapp.processEvents()

    grid_keys = view._last_rendered_keys[:6]
    view._set_view_mode("list")
    qapp.processEvents()
    list_keys = view._last_rendered_keys[:6]
    assert list_keys[: len(grid_keys)] == grid_keys

    view.page_index = 2
    view.search_bar.input.setText("CL-EOAT")
    QTest.qWait(SEARCH_DEBOUNCE_MS + 60)
    qapp.processEvents()
    assert view.page_index == 0
    assert view._last_rendered_keys[0][1] == "CL-EOAT-0043"

    view.search_bar.input.clear()
    QTest.qWait(SEARCH_DEBOUNCE_MS + 60)
    qapp.processEvents()
    assert view.page_index == 0
    assert view._last_rendered_keys[0][1] == "P4-EOAT-0001"
    _cleanup_widget(qapp, page)


def test_pagination_shows_adjacent_page_after_page_three(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_eoat_sequence_bundle(tmp_path))
    page._show_browse(ENTITY_EOAT)
    qapp.processEvents()
    view = page.current_view
    assert isinstance(view, LibraryBrowseStateView)
    expected_pages = {
        0: [0, 1, 2, 3, -1, 7],
        1: [0, 1, 2, 3, -1, 7],
        2: [0, 1, 2, 3, -1, 7],
        3: [0, -1, 2, 3, 4, -1, 7],
        4: [0, -1, 3, 4, 5, -1, 7],
        5: [0, -1, 4, 5, 6, 7],
        6: [0, -1, 4, 5, 6, 7],
        7: [0, -1, 4, 5, 6, 7],
    }
    for current_page, expected in expected_pages.items():
        view.page_index = current_page
        assert view._visible_page_numbers(8) == expected

    view.page_index = 2
    view._last_page_count = 8
    view._render_pagination(total=64, page_size=8, page_count=8, start=16, visible_count=8)

    labels = [button.text() for button in view.page_buttons if not button.isHidden()]
    assert labels == ["1", "2", "3", "4", "...", "8"]
    page_three = next(button for button in view.page_buttons if button.text() == "3")
    page_four = next(button for button in view.page_buttons if button.text() == "4")
    assert not page_three.isEnabled()
    assert page_three.property("active") is True
    assert page_four.isEnabled()

    view.page_index = 4
    view._render_pagination(total=64, page_size=8, page_count=8, start=32, visible_count=8)
    labels = [button.text() for button in view.page_buttons if not button.isHidden()]
    assert labels == ["1", "...", "4", "5", "6", "...", "8"]
    ellipses = [button for button in view.page_buttons if not button.isHidden() and button.text() == "..."]
    assert ellipses
    assert all(not button.isEnabled() for button in ellipses)
    _cleanup_widget(qapp, page)


def test_parse_eoat_id_and_malformed_sort_warning(caplog) -> None:
    assert parse_eoat_id("P4-EOAT-0003") == {"prefix": "P4", "number": 3, "normalizedId": "P4-EOAT-0003"}
    assert parse_eoat_id("CL-EOAT-0043") == {"prefix": "CL", "number": 43, "normalizedId": "CL-EOAT-0043"}

    with caplog.at_level("WARNING", logger="app.atlas.minimalist.library"):
        assert parse_eoat_id("BAD-EOAT-ID-777") is None

    assert "Malformed EOAT ID placed at end of Library sort" in caplog.text


def test_search_input_debounces_browse_refresh(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_multi_tool_bundle(tmp_path, count=18))
    page._show_browse(ENTITY_TOOL)
    qapp.processEvents()
    view = page.current_view
    assert view is not None
    view.refresh()
    qapp.processEvents()

    calls: list[str] = []
    original_refresh = view.refresh

    def counted_refresh(*, reset_page: bool = False, interaction: str = "refresh") -> None:
        calls.append(interaction)
        original_refresh(reset_page=reset_page, interaction=interaction)

    view.refresh = counted_refresh
    view.search_bar.input.setText("8")
    view.search_bar.input.setText("82")
    view.search_bar.input.setText("8280030001")
    qapp.processEvents()

    assert calls == []
    QTest.qWait(SEARCH_DEBOUNCE_MS + 60)
    qapp.processEvents()

    assert calls == ["search"]
    _cleanup_widget(qapp, page)


def test_library_loading_state_keeps_shell_and_skeleton_cards(qapp) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.show()
    qapp.processEvents()

    view = page.current_view
    assert view is not None
    assert view.objectName() == "LibraryBrowseStateView"
    assert getattr(view, "loading_message", "")
    assert view.search_bar is not None
    assert view.filter_bar is not None
    skeletons = view.findChildren(QWidget, "LibrarySkeletonCard")
    assert skeletons
    assert len(skeletons) <= 8
    _cleanup_widget(qapp, page)


def test_record_pdf_export_opens_options_before_generation(qapp, tmp_path: Path, monkeypatch) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    for _ in range(4):
        qapp.processEvents()

    view = page.current_view
    assert view is not None
    assert view.hero is not None
    generated = threading.Event()

    def fake_export(detail_data, output_path=None, *, project_root="", options=None):
        generated.set()
        return tmp_path / "should_not_generate.pdf"

    monkeypatch.setattr("core.reporting.pdf_record_report.export_record_pdf", fake_export)
    view._export_pdf()
    qapp.processEvents()

    assert view._pdf_options_overlay is not None
    assert not view._pdf_options_overlay.isHidden()
    assert not view._pdf_export_running
    assert not generated.is_set()

    view._pdf_options_overlay.cancel_button.click()
    assert _wait_for_qt(qapp, lambda: view._pdf_options_overlay is None, timeout_ms=700)
    assert not view._pdf_export_running
    assert not generated.is_set()
    _cleanup_widget(qapp, page)


def test_pdf_options_disable_photo_controls_and_use_exclusive_format_mode(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    qapp.processEvents()

    view = page.current_view
    assert view is not None
    view._export_pdf()
    qapp.processEvents()
    overlay = view._pdf_options_overlay
    assert isinstance(overlay, PDFOptionsOverlay)

    overlay.photos_check.setChecked(False)
    qapp.processEvents()
    assert not overlay.photo_thumbnail_check.isEnabled()
    assert not overlay.photo_appendix_check.isEnabled()
    assert not overlay.missing_photo_check.isEnabled()
    options = overlay.options()
    assert not options.include_photos
    assert not options.include_photo_thumbnails
    assert not options.include_photo_appendix
    assert not options.include_missing_photo_status

    overlay.photos_check.setChecked(True)
    overlay.detailed_radio.setChecked(True)
    qapp.processEvents()
    options = overlay.options()
    assert overlay.photo_thumbnail_check.isEnabled()
    assert overlay.detailed_radio.isChecked()
    assert not overlay.compact_radio.isChecked()
    assert options.format_mode == "detailed"
    assert options.include_workbook_appendix
    _cleanup_widget(qapp, page)


def test_pdf_options_require_at_least_one_report_section(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    qapp.processEvents()

    view = page.current_view
    assert view is not None
    view._export_pdf()
    qapp.processEvents()
    overlay = view._pdf_options_overlay
    assert isinstance(overlay, PDFOptionsOverlay)
    emitted: list[ReportOptions] = []
    overlay.generate_requested.connect(emitted.append)
    for widget in (
        overlay.summary_check,
        overlay.details_check,
        overlay.relationships_check,
        overlay.documentation_check,
        overlay.photos_check,
        overlay.notes_check,
    ):
        widget.setChecked(False)

    overlay.generate_button.click()
    qapp.processEvents()

    assert emitted == []
    assert not overlay.validation_label.isHidden()
    assert "Select at least one" in overlay.validation_label.text()
    _cleanup_widget(qapp, page)


def test_record_pdf_generate_runs_in_background_shows_status_and_preview(qapp, tmp_path: Path, monkeypatch) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    for _ in range(4):
        qapp.processEvents()

    view = page.current_view
    assert view is not None
    assert view.hero is not None
    assert view.hero.export_button is not None
    finished = threading.Event()

    def fake_export(detail_data, output_path=None, *, project_root="", options=None):
        time.sleep(0.05)
        finished.set()
        path = Path(output_path)
        assert "pdf_previews" in str(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
        assert options is not None
        assert options.include_summary
        return path

    monkeypatch.setattr("core.reporting.pdf_record_report.export_record_pdf", fake_export)
    monkeypatch.setattr("core.reporting.pdf_record_report.pdf_image_warnings_for", lambda _path: (object(),))
    view._export_pdf()
    qapp.processEvents()
    assert view._pdf_options_overlay is not None
    view._pdf_options_overlay.generate_button.click()
    qapp.processEvents()

    assert view._pdf_export_running
    assert view._pdf_status_overlay is not None
    assert view.hero.export_button.text() == "Generating..."
    assert not view.hero.export_button.isEnabled()
    assert _wait_for_qt(qapp, lambda: finished.is_set() and not view._pdf_export_running, timeout_ms=1200)
    assert view.hero.export_button.isEnabled()
    assert view.hero.export_button.text() == "Export PDF"
    assert view._pdf_status_overlay is None
    assert view._pdf_preview_overlay is not None
    assert "pdf_previews" in str(view._pdf_preview_overlay.session.temp_pdf_path)
    assert not view._pdf_preview_overlay.session.default_save_path.exists()
    assert view._pdf_preview_overlay.skipped_photo_count == 1
    assert view._pdf_preview_overlay.warning_chip.text() == "1 photo skipped"
    assert view._pdf_preview_overlay.save_button is not None
    assert view._pdf_preview_overlay.print_button is not None
    assert view._pdf_preview_overlay.close_button is not None
    _cleanup_widget(qapp, page)


def test_pdf_preview_save_creates_final_report_without_duplicate_auto_save(qapp, tmp_path: Path, monkeypatch) -> None:
    host = QWidget()
    host.resize(1000, 720)
    host.show()
    temp_pdf = _write_minimal_pdf(tmp_path / "00_Project_Admin" / "cache" / "pdf_previews" / "preview.pdf")
    final_pdf = tmp_path / "output" / "pdf" / "EOAT_Report_P4-EOAT-0052_2026-07-06.pdf"
    session = PdfPreviewSession(ENTITY_EOAT, "P4-EOAT-0052", temp_pdf, final_pdf)
    detail = _gallery_detail_data(tmp_path, group_count=0, photos_per_group=0)
    overlay = PDFPreviewOverlay.open_for(host, session, detail, project_root=str(tmp_path))
    qapp.processEvents()
    monkeypatch.setattr("app.atlas.minimalist.library.QFileDialog.getSaveFileName", lambda *_args, **_kwargs: (str(final_pdf), "PDF files (*.pdf)"))

    overlay.save_button.click()
    qapp.processEvents()
    overlay.close_preview()
    qapp.processEvents()

    assert final_pdf.exists()
    assert session.saved
    assert not session.auto_saved
    assert len(list(final_pdf.parent.glob("EOAT_Report_P4-EOAT-0052_2026-07-06*.pdf"))) == 1
    _cleanup_widget(qapp, host)


def test_pdf_preview_close_within_ten_seconds_auto_saves(qapp, tmp_path: Path) -> None:
    host = QWidget()
    host.resize(1000, 720)
    host.show()
    temp_pdf = _write_minimal_pdf(tmp_path / "00_Project_Admin" / "cache" / "pdf_previews" / "preview_quick.pdf")
    final_pdf = tmp_path / "output" / "pdf" / "EOAT_Report_Quick.pdf"
    session = PdfPreviewSession(ENTITY_EOAT, "P4-EOAT-0052", temp_pdf, final_pdf)
    detail = _gallery_detail_data(tmp_path, group_count=0, photos_per_group=0)
    overlay = PDFPreviewOverlay.open_for(host, session, detail, project_root=str(tmp_path))
    qapp.processEvents()

    overlay.close_preview()
    qapp.processEvents()

    assert session.auto_saved
    assert session.final_saved_path is not None
    assert session.final_saved_path.exists()
    assert session.final_saved_path.parent == final_pdf.parent
    _cleanup_widget(qapp, host)


def test_pdf_preview_close_after_ten_seconds_does_not_auto_save(qapp, tmp_path: Path) -> None:
    host = QWidget()
    host.resize(1000, 720)
    host.show()
    temp_pdf = _write_minimal_pdf(tmp_path / "00_Project_Admin" / "cache" / "pdf_previews" / "preview_late.pdf")
    final_pdf = tmp_path / "output" / "pdf" / "EOAT_Report_Late.pdf"
    session = PdfPreviewSession(ENTITY_EOAT, "P4-EOAT-0052", temp_pdf, final_pdf, opened_at=time.monotonic() - 11)
    detail = _gallery_detail_data(tmp_path, group_count=0, photos_per_group=0)
    overlay = PDFPreviewOverlay.open_for(host, session, detail, project_root=str(tmp_path))
    qapp.processEvents()

    overlay.close_preview()
    qapp.processEvents()

    assert session.closed
    assert not session.saved
    assert not session.auto_saved
    assert not final_pdf.exists()
    _cleanup_widget(qapp, host)


def test_record_pdf_generation_failure_hides_status_and_restores_button(qapp, tmp_path: Path, monkeypatch) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    for _ in range(4):
        qapp.processEvents()

    view = page.current_view
    assert view is not None
    assert view.hero is not None
    assert view.hero.export_button is not None

    def fake_export(detail_data, output_path=None, *, project_root="", options=None):
        raise RuntimeError("write blocked")

    monkeypatch.setattr("core.reporting.pdf_record_report.export_record_pdf", fake_export)
    view._export_pdf()
    qapp.processEvents()
    assert view._pdf_options_overlay is not None
    view._pdf_options_overlay.generate_button.click()
    qapp.processEvents()

    assert _wait_for_qt(qapp, lambda: not view._pdf_export_running, timeout_ms=1200)
    assert view._pdf_status_overlay is None
    assert view.hero.export_button.isEnabled()
    assert view.hero.export_button.text() == "Export PDF"
    assert view._pdf_preview_overlay is None
    _cleanup_widget(qapp, page)


def test_machine_current_eoat_display_is_not_false_warning() -> None:
    unknown = MachineRecord(machine="77", label="Machine 77", source_rows=())
    explicit_none = MachineRecord(
        machine="78",
        label="Machine 78",
        source_rows=({"Status": "EOAT Not Installed", "Notes": "Bench audit"},),
    )

    assert machine_current_eoat_display(unknown).value == "Not Assigned"
    assert machine_current_eoat_display(unknown).state == "unknown"
    assert machine_current_eoat_display(explicit_none).value == "Not Installed"
    assert machine_current_eoat_display(explicit_none).state == "explicit_none"


def test_machine_summary_current_eoat_card_keeps_full_id_visible(qapp) -> None:
    detail = RecordDetailData(
        record_type=ENTITY_MACHINE,
        record_id="40",
        title="Machine 40",
        subtitle="Viper 12",
        condition="CL-EOAT-0054",
        plant_area="Plant 4",
        hero_fields=(),
        detail_sections=(),
        documentation_fields=(),
        photo_groups=(),
        history_fields=(),
        summary_fields=(
            RecordField("EOATs", "8"),
            RecordField("Tools", "12"),
            RecordField("Current EOAT", "CL-EOAT-0054"),
        ),
        report_sections=(),
    )
    panel = SummaryMetricsPanel(detail)
    panel.resize(760, 118)
    panel.show()
    qapp.processEvents()

    blocks = panel.findChildren(MetricBlock)
    current = next(block for block in blocks if block.is_current_eoat_metric())
    compact = [block for block in blocks if not block.is_current_eoat_metric()]

    assert current.display_value() == "CL-EOAT-0054"
    assert current.minimumWidth() >= 320
    assert current.width() >= current.minimumWidth()
    assert all(block.maximumWidth() <= 210 for block in compact)
    _cleanup_widget(qapp, panel)


def test_machine_summary_current_eoat_fallback_labels(qapp) -> None:
    detail = RecordDetailData(
        record_type=ENTITY_MACHINE,
        record_id="77",
        title="Machine 77",
        subtitle="Machine",
        condition="Not Assigned",
        plant_area="Plant 4",
        hero_fields=(),
        detail_sections=(),
        documentation_fields=(),
        photo_groups=(),
        history_fields=(),
        summary_fields=(
            RecordField("EOATs", "0"),
            RecordField("Tools", "0"),
            RecordField("Current EOAT", "No Current EOAT"),
        ),
        report_sections=(),
    )
    panel = SummaryMetricsPanel(detail)
    panel.show()
    qapp.processEvents()
    current = next(block for block in panel.findChildren(MetricBlock) if block.is_current_eoat_metric())

    assert current.display_value() == "Not Installed"
    _cleanup_widget(qapp, panel)


def test_loader_does_not_treat_not_installed_as_current_eoat() -> None:
    rows = [
        {"Status": "EOAT Not Installed", "EOAT Assembly ID": "P4-EOAT-0099", "Audit ID": "AUD-99"},
        {"Status": "Installed", "EOAT Assembly ID": "P4-EOAT-0100", "Audit ID": "AUD-100"},
    ]

    assert _current_eoat_for_rows(rows) == "P4-EOAT-0100"


def test_loader_resolves_current_eoat_from_machine_audit_row() -> None:
    rows = [
        {"Audit Date": "2026-06-01", "Press/Machine #": "36", "Entry Type": "Compatible", "EOAT Assembly ID": "P4-EOAT-0009"},
        {"Audit Date": "2026-06-08", "Press/Machine #": "36", "Status": "Complete", "EOAT Assembly ID": "P4-EOAT-0014"},
    ]
    resolution = _current_eoat_resolution_for_rows(rows)

    assert resolution.eoat_id == "P4-EOAT-0014"
    assert resolution.status == "indexed"
    assert resolution.reason == "latest audit"


def test_eoat_cards_use_active_status_and_condition_metric(tmp_path: Path) -> None:
    catalog = LibraryCatalog(_machine36_bundle(tmp_path), controller=_Controller())
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0014")

    assert entity is not None
    assert record_status_display(entity) == ("Active", "good")
    metrics = atlas_card_metrics(entity, catalog, variant="compact")
    assert [metric.label for metric in metrics] == ["MACHINES", "TOOLS", "CONDITION"]
    assert metrics[-1].value == "On Machine 36"
    assert all(metric.label != "CONNECTION" for metric in metrics)


def test_machine_card_metric_uses_current_eoat(tmp_path: Path) -> None:
    catalog = LibraryCatalog(_machine36_bundle(tmp_path), controller=_Controller())
    entity = catalog.entity_for(ENTITY_MACHINE, "36")

    assert entity is not None
    metrics = atlas_card_metrics(entity, catalog, variant="hero")
    assert metrics[2].label == "CURRENT EOAT"
    assert metrics[2].value == "P4-EOAT-0014"


def test_machine_record_view_combines_current_and_compatible_eoats(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_machine36_bundle(tmp_path))
    entity = page.catalog.entity_for(ENTITY_MACHINE, "36")
    assert entity is not None

    page._show_record(entity)
    for _ in range(4):
        qapp.processEvents()

    panel = page.current_view.overview.relationship_panel
    current_zones = [
        zone
        for zone in panel.left_visible_zones
        if zone.entity.entity_type == ENTITY_EOAT and zone.entity.key == "P4-EOAT-0014"
    ]
    assert current_zones
    assert current_zones[0].badge == "CURRENT"
    assert panel.left_title.startswith("EOATs")
    _cleanup_widget(qapp, page)


def test_record_back_restores_previous_context(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_library_bundle(tmp_path))
    entity = page.catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None

    page._show_record(entity)
    qapp.processEvents()
    assert page.state == "record"
    page._go_back()
    qapp.processEvents()
    assert page.state == "browse"
    assert page.scope_type == ENTITY_EOAT

    page._show_browse(ENTITY_EOAT)
    page._show_record(entity)
    qapp.processEvents()
    assert page.state == "record"
    page._go_back()
    qapp.processEvents()
    assert page.state == "browse"
    assert page.scope_type == ENTITY_EOAT
    _cleanup_widget(qapp, page)


def test_back_to_library_uses_current_record_type_for_direct_profiles(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_library_bundle(tmp_path))

    for entity_type, key in (
        (ENTITY_EOAT, "P4-EOAT-0052"),
        (ENTITY_TOOL, "6201510010"),
        (ENTITY_MACHINE, "52"),
    ):
        assert page.select_entity(entity_type, key) is True
        qapp.processEvents()
        assert page.state == "record"

        page._go_back()
        qapp.processEvents()

        assert page.state == "browse"
        assert page.scope_type == entity_type

    _cleanup_widget(qapp, page)


def test_back_to_library_ignores_mismatched_previous_category(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_library_bundle(tmp_path))
    page._show_browse(ENTITY_TOOL)
    qapp.processEvents()
    view = page.current_view
    assert isinstance(view, LibraryBrowseStateView)
    view.search_bar.input.setText("6201510010")
    entity = page.catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None

    page._show_record(entity)
    qapp.processEvents()
    page._go_back()
    qapp.processEvents()

    assert page.state == "browse"
    assert page.scope_type == ENTITY_EOAT
    assert page.browse_query == ""
    _cleanup_widget(qapp, page)


def test_back_to_library_restores_compatible_browse_state(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1600, 900)
    page.set_bundle(_multi_navigation_bundle(tmp_path, count=12))

    cases = (
        (ENTITY_EOAT, "P4-EOAT-0009", "EOAT ID"),
        (ENTITY_TOOL, "NAV-TOOL-0009", "Tool Number"),
        (ENTITY_MACHINE, "109", "Machine Number"),
    )
    for entity_type, key, sort_name in cases:
        page._show_browse(entity_type)
        qapp.processEvents()
        view = page.current_view
        assert isinstance(view, LibraryBrowseStateView)
        view.view_mode = "list"
        view.grid_button.setChecked(False)
        view.list_button.setChecked(True)
        view.sort_dropdown.combo.setCurrentText(sort_name)
        view.page_index = 1
        entity = page.catalog.entity_for(entity_type, key)
        assert entity is not None

        page._show_record(entity)
        qapp.processEvents()
        page._go_back()
        qapp.processEvents()

        restored = page.current_view
        assert page.state == "browse"
        assert page.scope_type == entity_type
        assert isinstance(restored, LibraryBrowseStateView)
        assert restored.view_mode == "list"
        assert restored.page_index == 1
        assert restored.sort_dropdown.combo.currentText() == sort_name

    _cleanup_widget(qapp, page)


def test_back_to_library_from_related_record_uses_current_record_type(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.set_bundle(_library_bundle(tmp_path))
    eoat = page.catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    tool = page.catalog.entity_for(ENTITY_TOOL, "6201510010")
    assert eoat is not None
    assert tool is not None

    page._show_browse(ENTITY_EOAT)
    page._show_record(eoat)
    qapp.processEvents()
    page._show_record(tool)
    qapp.processEvents()
    assert page.state == "record"
    assert page.selected_entity is not None
    assert page.selected_entity.entity_type == ENTITY_TOOL

    page._go_back()
    qapp.processEvents()

    assert page.state == "browse"
    assert page.scope_type == ENTITY_TOOL
    _cleanup_widget(qapp, page)


def test_back_to_library_hidden_on_home_and_library_browse_pages(qapp, tmp_path: Path) -> None:
    home = AtlasMinimalistHomePage(_Controller())
    home.resize(1400, 900)
    home.show()
    home.page_shown()
    qapp.processEvents()
    home_back = home.shell.top_bar.back_button

    assert not home_back.isVisibleTo(home)
    assert not home_back.isEnabled()

    page = AtlasMinimalistLibraryPage(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.show()
    page.page_shown()
    qapp.processEvents()
    back = page.shell.top_bar.back_button

    assert not back.isVisibleTo(page)
    assert not back.isEnabled()
    for scope in (ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE):
        page.library_content._show_browse(scope)
        qapp.processEvents()
        assert page.library_content.state == "browse"
        assert page.library_content.scope_type == scope
        assert not back.isVisibleTo(page)
        assert not back.isEnabled()

    _cleanup_widget(qapp, home)
    _cleanup_widget(qapp, page)


def test_record_back_button_fades_in_and_out_from_top_chrome(qapp, tmp_path: Path) -> None:
    page = AtlasMinimalistLibraryPage(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.show()
    qapp.processEvents()

    for entity_type, key in ((ENTITY_EOAT, "P4-EOAT-0052"), (ENTITY_TOOL, "6201510010"), (ENTITY_MACHINE, "52")):
        assert page.select_entity(entity_type, key) is True
        qapp.processEvents()

        back = page.shell.top_bar.back_button
        menu = page.shell.top_bar.menu_button
        search = page.shell.top_bar.search_button
        opacity = back.graphicsEffect()
        assert opacity is not None
        assert back.isVisibleTo(page)
        assert back.isEnabled()
        assert page.shell.top_bar._back_animation.duration() == 500
        assert _wait_for_qt(qapp, lambda: float(opacity.opacity()) >= 0.98)
        assert back.geometry().left() > menu.geometry().right()
        assert abs(back.geometry().center().y() - menu.geometry().center().y()) <= 2
        assert abs(back.geometry().center().y() - search.geometry().center().y()) <= 2

        back.click()
        qapp.processEvents()

        assert page.library_content.state == "browse"
        assert page.library_content.scope_type == entity_type
        assert back.isVisibleTo(page)
        assert not back.isEnabled()
        assert page.library_content.current_view is not None
        assert page.library_content.current_view.objectName() == "LibraryBrowseStateView"
        assert _wait_for_qt(qapp, lambda: not back.isVisibleTo(page) and not back.isEnabled() and float(opacity.opacity()) <= 0.02)

    _cleanup_widget(qapp, page)


def test_record_back_button_handles_rapid_navigation_without_stuck_opacity(qapp, tmp_path: Path) -> None:
    page = AtlasMinimalistLibraryPage(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.show()
    qapp.processEvents()
    back = page.shell.top_bar.back_button
    opacity = back.graphicsEffect()
    assert opacity is not None

    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    qapp.processEvents()
    back.click()
    qapp.processEvents()
    assert not back.isEnabled()
    assert page.select_entity(ENTITY_MACHINE, "52") is True
    qapp.processEvents()

    assert page.library_content.state == "record"
    assert back.isVisibleTo(page)
    assert back.isEnabled()
    assert _wait_for_qt(qapp, lambda: back.isVisibleTo(page) and back.isEnabled() and float(opacity.opacity()) >= 0.98)

    back.click()
    qapp.processEvents()
    assert page.library_content.state == "browse"
    assert _wait_for_qt(qapp, lambda: not back.isVisibleTo(page) and not back.isEnabled() and float(opacity.opacity()) <= 0.02)
    _cleanup_widget(qapp, page)


def test_record_shell_reuse_keeps_record_content_visible(qapp, tmp_path: Path) -> None:
    page = AtlasMinimalistLibraryPage(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.show()
    qapp.processEvents()

    for entity_type, key in ((ENTITY_EOAT, "P4-EOAT-0052"), (ENTITY_TOOL, "6201510010"), (ENTITY_MACHINE, "52")):
        assert page.select_entity(entity_type, key) is True
        for _ in range(4):
            qapp.processEvents()
        _assert_record_content_visible(page.library_content.current_view)
        page.library_content._go_back()
        qapp.processEvents()

    _cleanup_widget(qapp, page)


def test_record_page_opens_with_photo_service_disabled(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_library_bundle(tmp_path))
    page.photo_service = None
    page.catalog.photo_service = None
    page.show()
    qapp.processEvents()

    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    for _ in range(4):
        qapp.processEvents()

    _assert_record_content_visible(page.current_view)
    _cleanup_widget(qapp, page)


def test_record_page_survives_photo_service_thumbnail_failure(qapp, tmp_path: Path) -> None:
    page = MinimalistLibraryContent(_Controller())
    page.resize(1400, 900)
    page.set_bundle(_photo_preview_bundle(tmp_path, tmp_path / "missing_preview.png"))
    failing_service = _FailingPhotoService()
    page.photo_service = failing_service
    page.catalog.photo_service = failing_service
    page.show()
    qapp.processEvents()

    assert page.select_entity(ENTITY_EOAT, "P4-EOAT-0052") is True
    for _ in range(4):
        qapp.processEvents()
    _assert_record_content_visible(page.current_view)

    page.current_view._set_tab(2)
    for _ in range(4):
        qapp.processEvents()
    tile = page.current_view.findChild(PhotoTile)
    assert tile is not None
    assert tile.load_error
    assert page.current_view.isVisible()
    assert page.current_view.findChild(RecordHeroPanel).isVisible()
    assert page.current_view.findChild(RecordTabBar).isVisible()
    assert tile.isVisible()
    _cleanup_widget(qapp, page)


def test_top_chrome_fade_stays_under_controls_and_strengthens_on_scroll(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_REDUCED_MOTION", "1")
    host = QWidget()
    fade = TopChromeFade(host)
    try:
        host.resize(1200, 760)
        fade.setGeometry(0, 0, host.width(), fade.HEIGHT)
        host.show()
        qapp.processEvents()

        assert fade.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fade.set_scroll_progress(0.0)
        fade.set_scrolled(True)
        assert _wait_for_qt(qapp, lambda: fade.get_scroll_progress() >= 0.99, timeout_ms=450)

        fade.set_scrolled(False)
        assert _wait_for_qt(qapp, lambda: fade.get_scroll_progress() <= 0.01, timeout_ms=450)
    finally:
        _cleanup_widget(qapp, host)


def test_relationship_overview_shows_seven_related_items_without_more(qapp, tmp_path: Path) -> None:
    panel = _relationship_panel(tmp_path, machine_count=7, tool_count=1)
    try:
        center_y = panel.center_rect.center().y()
        left_cards = panel.left_visible_zones
        right_cards = panel.right_visible_zones

        assert len(left_cards) == 7
        assert not [zone for zone in panel.left_zones if zone.more_count]
        assert len(right_cards) == 1
        assert abs(right_cards[0].geometry().center().y() - center_y) <= 1

        left_columns = _widgets_by_x(left_cards)
        assert sorted((len(column) for column in left_columns.values()), reverse=True) == [3, 2, 2]
        assert all(len(column) <= 3 for column in left_columns.values())
        inner_left_column = left_columns[max(left_columns)]
        inner_centers = sorted(card.geometry().center().y() for card in inner_left_column)
        assert abs(inner_centers[1] - center_y) <= 1
        _assert_widgets_do_not_overlap(left_cards + right_cards)
    finally:
        _cleanup_widget(qapp, panel)


def test_relationship_overview_uses_more_card_only_after_nine_items(qapp, tmp_path: Path) -> None:
    panel = _relationship_panel(tmp_path, machine_count=10, tool_count=1)
    try:
        left_cards = panel.left_visible_zones
        more_zones = [zone for zone in panel.left_zones if zone.more_count]
        left_items = [*left_cards, *more_zones]

        assert len(left_cards) == 8
        assert len(more_zones) == 1
        assert more_zones[0].more_count == 2
        left_columns = _widgets_by_x(left_items)
        assert sorted((len(column) for column in left_columns.values()), reverse=True) == [3, 3, 3]
        assert all(len(column) <= 3 for column in left_columns.values())
        _assert_widgets_do_not_overlap(left_items)
    finally:
        _cleanup_widget(qapp, panel)


def test_relationship_overview_uses_uniform_blue_structure(qapp, tmp_path: Path) -> None:
    panel = _relationship_panel(tmp_path, machine_count=2, tool_count=2)
    try:
        captured_badge_colors: list[str] = []

        def capture_badge(_painter, _center, _text, color, *, compact=False) -> None:
            captured_badge_colors.append(color.name())

        panel._draw_count_badge = capture_badge
        image = QImage(1400, 430, QImage.Format.Format_ARGB32)
        image.fill(QColor("#000000"))
        painter = QPainter(image)
        panel._draw_connectors(painter)
        painter.end()

        assert panel.RELATIONSHIP_CONNECTOR_COLOR.name() == "#168dff"
        assert set(captured_badge_colors) == {"#00c9ff"}
        assert "#20df72" not in captured_badge_colors
    finally:
        _cleanup_widget(qapp, panel)


def test_photo_deduplication_preserves_best_metadata_label(tmp_path: Path) -> None:
    path = tmp_path / "front.png"
    generic = PhotoItem(path=str(path), filename=path.name, category="Other", date_taken="2026-07-01")
    specific = PhotoItem(path=str(path), filename=path.name, photo_type="01_Front_View", imported_at="2026-07-02T08:00:00")
    service = LibraryDataService(tmp_path)
    service.rebuild_index_from_bundle(_library_bundle_with_photos(tmp_path, (generic, specific)))

    detail = service.get_record_detail_data(ENTITY_EOAT, "P4-EOAT-0052")

    assert detail.photo_count == 1
    assert len(detail.photo_groups) == 1
    assert detail.photo_groups[0].title == "Overall / Front View"
    assert detail.photo_groups[0].photos[0].category == "01_Front_View"


def test_photo_gallery_grouped_layout_has_unique_tile_positions(qapp, tmp_path: Path) -> None:
    detail = _gallery_detail_data(tmp_path, group_count=3, photos_per_group=5)
    card = PhotoGalleryCard(detail, project_root=str(tmp_path), photo_service=_RecordingPhotoService())
    card.resize(760, 460)
    card.show()
    qapp.processEvents()
    for section in card.findChildren(PhotoGroupSection):
        section.resize(520, section.height())
        section._apply_columns(3)
    qapp.processEvents()

    tiles = card.findChildren(PhotoTile)
    rects = [QRect(tile.mapTo(card, QPoint(0, 0)), tile.size()) for tile in tiles]

    assert len(tiles) == 15
    assert len({(rect.x(), rect.y()) for rect in rects}) == len(rects)
    for index, rect in enumerate(rects):
        for other in rects[index + 1 :]:
            assert not rect.intersects(other)
    _cleanup_widget(qapp, card)


def test_docs_photos_requests_thumbnails_async_without_sync_decode(qapp, tmp_path: Path) -> None:
    photo_service = _RecordingPhotoService()
    detail = _gallery_detail_data(tmp_path, group_count=1, photos_per_group=2)
    card = PhotoGalleryCard(detail, project_root=str(tmp_path), photo_service=photo_service)
    card.show()
    qapp.processEvents()

    tiles = card.findChildren(PhotoTile)
    assert len(tiles) == 2
    assert len(photo_service.thumbnail_requests) == 2
    assert all(tile.pixmap.isNull() for tile in tiles)
    _cleanup_widget(qapp, card)


def test_record_tabs_are_lazy_rendered(qapp, tmp_path: Path) -> None:
    catalog = LibraryCatalog(_library_bundle(tmp_path), controller=_Controller())
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    assert entity is not None
    view = LibraryRecordStateView(catalog, entity, lambda: None, lambda _entity: None)
    assert view.details is None
    assert view.docs is None
    assert view.history is None

    view._set_tab(1)
    qapp.processEvents()
    assert view.details is not None
    assert view.docs is None
    assert view.history is None

    view._set_tab(2)
    qapp.processEvents()
    assert view.docs is not None
    assert view.history is None

    view._set_tab(3)
    qapp.processEvents()
    assert view.history is not None
    _cleanup_widget(qapp, view)


def test_record_view_shell_is_reused_between_records(qapp, tmp_path: Path) -> None:
    catalog = LibraryCatalog(_library_bundle(tmp_path), controller=_Controller())
    eoat = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0052")
    machine = catalog.entity_for(ENTITY_MACHINE, "52")
    assert eoat is not None
    assert machine is not None
    view = LibraryRecordStateView(catalog, eoat, lambda: None, lambda _entity: None)
    first_view = view

    view.bind_record(catalog, machine)
    qapp.processEvents()
    assert view is first_view
    assert view.entity.key == "52"
    _cleanup_widget(qapp, view)


def test_photo_tile_loads_real_preview_and_opens_lightbox(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_REDUCED_MOTION", "1")
    image_path = tmp_path / "indexed_photos" / "preview.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(96, 64, QImage.Format.Format_RGB32)
    image.fill(QColor("#168dff"))
    assert image.save(str(image_path))

    host = QWidget()
    host.resize(420, 260)
    host.show()
    service = PhotoService(tmp_path, host)
    host.photo_service = service
    tile = PhotoTile(
        _preview_record_photo(image_path, tmp_path),
        record_type=ENTITY_EOAT,
        record_id="P4-EOAT-0052",
        project_root=str(tmp_path),
        photo_service=service,
        context_id="photos:test:preview",
        parent=host,
    )
    tile.move(20, 20)
    tile.show()
    qapp.processEvents()
    assert tile.pixmap.isNull()

    overlay = tile.open_lightbox()
    qapp.processEvents()
    assert overlay is not None
    assert overlay.isVisible()
    assert _wait_for_qt(qapp, lambda: not overlay.preview.pixmap.isNull())
    assert overlay.preview.geometry().width() > tile.geometry().width()

    wheel = _FakeWheelEvent(QPointF(overlay.preview.width() / 2, overlay.preview.height() / 2), 120)
    overlay.preview.wheelEvent(wheel)
    assert wheel.accepted
    assert overlay.preview._zoom > 1.0
    wheel_out = _FakeWheelEvent(QPointF(overlay.preview.width() / 2, overlay.preview.height() / 2), -12000)
    overlay.preview.wheelEvent(wheel_out)
    assert overlay.preview._zoom >= 1.0

    overlay.close_lightbox()
    qapp.processEvents()
    _cleanup_widget(qapp, host)


def test_photo_tile_loads_heic_preview_when_qt_cannot_read(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_REDUCED_MOTION", "1")
    import pillow_heif
    from PIL import Image

    pillow_heif.register_heif_opener()
    image_path = tmp_path / "indexed_photos" / "preview.HEIC"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 60), (24, 141, 255)).save(image_path)
    assert QImageReader(str(image_path)).read().isNull()

    host = QWidget()
    host.resize(420, 260)
    host.show()
    service = PhotoService(tmp_path, host)
    host.photo_service = service
    tile = PhotoTile(
        _preview_record_photo(image_path, tmp_path),
        record_type=ENTITY_EOAT,
        record_id="P4-EOAT-0052",
        project_root=str(tmp_path),
        photo_service=service,
        context_id="photos:test:heic",
        parent=host,
    )
    tile.move(20, 20)
    tile.show()
    qapp.processEvents()
    assert tile.photo.path.casefold().endswith(".heic")
    assert tile.pixmap.isNull()

    overlay = tile.open_lightbox()
    qapp.processEvents()
    assert overlay is not None
    assert overlay.isVisible()
    assert _wait_for_qt(qapp, lambda: not overlay.preview.pixmap.isNull())
    assert overlay.preview.geometry().width() > tile.geometry().width()
    overlay.close_lightbox()
    QTest.qWait(10)
    qapp.processEvents()
    _cleanup_widget(qapp, host)


def _library_bundle(tmp_path: Path) -> AtlasDataBundle:
    photo = PhotoItem(path=str(tmp_path / "P4-EOAT-0052.png"), filename="P4-EOAT-0052.png")
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0052",
        display_id="P4-EOAT-0052",
        tools=("6201510010",),
        machines=("36", "52"),
        eoat_type="Vacuum",
        status="Installed",
        vacuum_info="Mixed robot + external peripheral air; 4 cups",
        documentation=DocumentationStatus(score=88, status_label="Good"),
        photos=PhotoSet(eoat_id="P4-EOAT-0052", photos=(photo,)),
    )
    tool = ToolRecord(
        tool="6201510010",
        label="Tool 6201510010",
        compatible_eoats=("P4-EOAT-0052",),
        compatible_machines=("36", "52"),
        part_description="Demo part",
    )
    machine = MachineRecord(
        machine="52",
        label="Machine 52",
        robot_type="Engel Viper",
        compatible_eoats=("P4-EOAT-0052",),
        compatible_tools=("6201510010",),
        current_eoat="P4-EOAT-0052",
        documentation_score=91,
    )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat.eoat_id): eoat.eoat_id},
        eoats_by_tool={normalized_tool_key(tool.tool): (eoat.eoat_id,)},
        eoats_by_machine={normalized_machine_key("36"): (eoat.eoat_id,), normalized_machine_key("52"): (eoat.eoat_id,)},
        machines_by_tool={normalized_tool_key(tool.tool): ("36", "52")},
        machines_by_eoat={normalized_eoat_key(eoat.eoat_id): ("36", "52")},
        tools_by_machine={normalized_machine_key("36"): (tool.tool,), normalized_machine_key("52"): (tool.tool,)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-01 12:00",
        eoats=(eoat,),
        tools=(tool,),
        machines=(machine,),
        indexes=indexes,
    )


def _library_bundle_with_photos(tmp_path: Path, photos: tuple[PhotoItem, ...]) -> AtlasDataBundle:
    tmp_path.mkdir(parents=True, exist_ok=True)
    base = _library_bundle(tmp_path)
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0052",
        display_id="P4-EOAT-0052",
        tools=("6201510010",),
        machines=("36", "52"),
        eoat_type="Vacuum",
        status="Installed",
        vacuum_info="Mixed robot + external peripheral air; 4 cups",
        documentation=DocumentationStatus(score=88, status_label="Good"),
        photos=PhotoSet(eoat_id="P4-EOAT-0052", indexed_photos=photos),
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at=base.loaded_at,
        eoats=(eoat,),
        tools=base.tools,
        machines=base.machines,
        indexes=base.indexes,
    )


def _eoat_sequence_bundle(tmp_path: Path) -> AtlasDataBundle:
    ids = [
        *(f"CL-EOAT-{number:04d}" for number in range(43, 65)),
        "BROKEN-EOAT-ID",
        *(f"P4-EOAT-{number:04d}" for number in range(42, 0, -1)),
    ]
    eoats = tuple(
        EOATRecord(
            eoat_id=eoat_id,
            display_id=eoat_id,
            eoat_type="Vacuum",
            status="Installed",
            documentation=DocumentationStatus(score=88, status_label="Good"),
            photos=PhotoSet(eoat_id=eoat_id),
        )
        for eoat_id in ids
    )
    indexes = AtlasIndexes(eoat_by_id={normalized_eoat_key(record.eoat_id): record.eoat_id for record in eoats})
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-01 12:00",
        eoats=eoats,
        tools=(),
        machines=(),
        indexes=indexes,
    )


def _preview_record_photo(image_path: Path, project_root: Path) -> RecordPhoto:
    try:
        folder_path = str(image_path.parent.relative_to(project_root))
    except ValueError:
        folder_path = str(image_path.parent)
    return RecordPhoto(
        path=str(image_path),
        filename=image_path.name,
        category="Overall / Front View",
        date_taken="2026-07-02",
        association="P4-EOAT-0052",
        folder_path=folder_path,
        stored_filename=image_path.name,
        photo_filename=image_path.name,
        eoat_id="P4-EOAT-0052",
        path_candidates=(str(image_path),),
    )


def _gallery_detail_data(tmp_path: Path, *, group_count: int, photos_per_group: int) -> RecordDetailData:
    group_titles = ("Overall / Front View", "Side View", "Tool Number", "Mounting Hardware", "Sensors")
    groups: list[RecordPhotoGroup] = []
    for group_index in range(group_count):
        title = group_titles[group_index % len(group_titles)]
        photos = []
        for photo_index in range(photos_per_group):
            path = tmp_path / f"group_{group_index}_photo_{photo_index}.png"
            photos.append(
                RecordPhoto(
                    path=str(path),
                    filename=path.name,
                    category=title,
                    photo_id=f"photo-{group_index}-{photo_index}",
                    date_taken=f"2026-07-{photo_index + 1:02d}",
                    association="P4-EOAT-0052",
                    eoat_id="P4-EOAT-0052",
                    path_candidates=(str(path),),
                )
            )
        groups.append(RecordPhotoGroup(title, tuple(photos)))
    return RecordDetailData(
        record_type=ENTITY_EOAT,
        record_id="P4-EOAT-0052",
        title="P4-EOAT-0052",
        subtitle="Vacuum",
        condition="In Service",
        plant_area="Plant 4",
        hero_fields=(),
        detail_sections=(),
        documentation_fields=(),
        photo_groups=tuple(groups),
        history_fields=(),
        summary_fields=(),
        report_sections=(),
    )


def _photo_preview_bundle(tmp_path: Path, image_path: Path) -> AtlasDataBundle:
    base = _library_bundle(tmp_path)
    photo = PhotoItem(
        path="",
        filename=image_path.name,
        category="Overall / Front View",
        eoat_id="P4-EOAT-0052",
        date_taken="2026-07-02",
        folder_path=str(image_path.parent.relative_to(tmp_path)),
        stored_filename=image_path.name,
        source="photo index",
    )
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0052",
        display_id="P4-EOAT-0052",
        tools=("6201510010",),
        machines=("36", "52"),
        eoat_type="Vacuum",
        status="Installed",
        documentation=DocumentationStatus(score=88, status_label="Good"),
        photos=PhotoSet(eoat_id="P4-EOAT-0052", indexed_photos=(photo,)),
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at=base.loaded_at,
        eoats=(eoat,),
        tools=base.tools,
        machines=base.machines,
        indexes=base.indexes,
    )


def _relationship_capacity_bundle(tmp_path: Path, *, machine_count: int, tool_count: int) -> AtlasDataBundle:
    eoat_id = "P4-EOAT-0777"
    machine_ids = tuple(str(170 + index) for index in range(machine_count))
    tool_ids = tuple(f"CAP-TOOL-{index + 1:02d}" for index in range(tool_count))
    eoat = EOATRecord(
        eoat_id=eoat_id,
        display_id=eoat_id,
        tools=tool_ids,
        machines=machine_ids,
        eoat_type="Vacuum",
        status="Complete",
        documentation=DocumentationStatus(score=86, status_label="Good"),
    )
    tools = tuple(
        ToolRecord(
            tool=tool_id,
            label=tool_id,
            compatible_eoats=(eoat_id,),
            compatible_machines=machine_ids,
            part_description=f"Capacity tool {index + 1}",
        )
        for index, tool_id in enumerate(tool_ids)
    )
    machines = tuple(
        MachineRecord(
            machine=machine_id,
            label=f"Machine {machine_id}",
            robot_type="Sytrama",
            compatible_eoats=(eoat_id,),
            compatible_tools=tool_ids,
            current_eoat=eoat_id if index == 0 else "",
            documentation_score=82,
        )
        for index, machine_id in enumerate(machine_ids)
    )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat_id): eoat_id},
        eoats_by_tool={normalized_tool_key(tool_id): (eoat_id,) for tool_id in tool_ids},
        eoats_by_machine={normalized_machine_key(machine_id): (eoat_id,) for machine_id in machine_ids},
        machines_by_tool={normalized_tool_key(tool_id): machine_ids for tool_id in tool_ids},
        machines_by_eoat={normalized_eoat_key(eoat_id): machine_ids},
        tools_by_machine={normalized_machine_key(machine_id): tool_ids for machine_id in machine_ids},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-01 12:00",
        eoats=(eoat,),
        tools=tools,
        machines=machines,
        indexes=indexes,
    )


def _relationship_panel(tmp_path: Path, *, machine_count: int, tool_count: int) -> RelationshipOverviewPanel:
    catalog = LibraryCatalog(_relationship_capacity_bundle(tmp_path, machine_count=machine_count, tool_count=tool_count), controller=_Controller())
    entity = catalog.entity_for(ENTITY_EOAT, "P4-EOAT-0777")
    assert entity is not None
    panel = RelationshipOverviewPanel(entity, catalog, lambda _entity: None)
    panel.resize(1400, 430)
    panel._populate()
    return panel


def _widgets_by_x(widgets) -> dict[int, list]:
    columns: dict[int, list] = {}
    for widget in widgets:
        columns.setdefault(widget.geometry().x(), []).append(widget)
    return columns


def _assert_widgets_do_not_overlap(widgets) -> None:
    for index, widget in enumerate(widgets):
        for other in widgets[index + 1 :]:
            assert not widget.geometry().intersects(other.geometry())


def _cleanup_widget(qapp, widget) -> None:
    content = getattr(widget, "library_content", None)
    shell = getattr(widget, "shell", None)
    remove_filter = getattr(shell, "remove_app_event_filter", None)
    if callable(remove_filter):
        remove_filter()
    for owner in (widget, content):
        if owner is None:
            continue
        service = getattr(owner, "photo_service", None)
        shutdown = getattr(service, "shutdown", None)
        if callable(shutdown):
            shutdown(1000)
        else:
            shutdown_owner = getattr(owner, "shutdown_photo_service", None)
            if callable(shutdown_owner):
                shutdown_owner()
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def _wait_for_qt(qapp, predicate, *, timeout_ms: int = 2000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    qapp.processEvents()
    return bool(predicate())


def _write_minimal_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    return path


def _assert_record_content_visible(view) -> None:
    assert view is not None
    assert view.objectName() == "LibraryRecordStateView"
    assert view.isVisible()
    assert view.width() > 0
    assert view.height() > 0
    for widget_type in (RecordHeroPanel, RecordTabBar, RecordOverviewTab, RelationshipOverviewPanel, SummaryMetricsPanel):
        widget = view.findChild(widget_type)
        assert widget is not None, widget_type.__name__
        assert widget.isVisible(), widget_type.__name__
        assert widget.width() > 0, widget_type.__name__
        assert widget.height() > 0, widget_type.__name__


class _NoopSignal:
    def connect(self, *_args, **_kwargs) -> None:
        return None


class _TestSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot, *_args, **_kwargs) -> None:
        self._slots.append(slot)

    def emit(self, *args, **kwargs) -> None:
        for slot in list(self._slots):
            slot(*args, **kwargs)


class _RecordingPhotoService:
    def __init__(self) -> None:
        self.thumbnail_ready = _TestSignal()
        self.photo_load_failed = _TestSignal()
        self.project_root = ""
        self.thumbnail_requests: list[tuple[str, tuple[str, ...], tuple[int, int], int, str]] = []
        self.cancelled_contexts: list[str] = []
        self.cached_thumbnails: dict[tuple[str, tuple[int, int]], QImage] = {}

    def set_project_root(self, project_root: str) -> None:
        self.project_root = project_root

    def get_cached_thumbnail(self, *_args, **_kwargs):
        if len(_args) >= 2:
            key = (str(_args[0]), tuple(_args[1]))
            image = self.cached_thumbnails.get(key)
            if image is not None:
                return image.copy()
        return None

    def request_thumbnail(self, photo_id, paths, size, priority, context_id) -> None:
        self.thumbnail_requests.append((str(photo_id), tuple(paths), tuple(size), int(priority), str(context_id)))

    def cancel_context(self, context_id: str) -> None:
        self.cancelled_contexts.append(context_id)

    def pause_prefetch(self) -> None:
        return None

    def resume_prefetch(self) -> None:
        return None

    def shutdown(self, *_args, **_kwargs) -> None:
        return None


class _FailingPhotoService:
    thumbnail_ready = _NoopSignal()
    photo_load_failed = _NoopSignal()

    def get_cached_thumbnail(self, *_args, **_kwargs):
        raise RuntimeError("thumbnail cache unavailable")

    def request_thumbnail(self, *_args, **_kwargs) -> None:
        raise RuntimeError("thumbnail worker unavailable")


class _FakeWheelEvent:
    def __init__(self, position: QPointF, delta: int) -> None:
        self._position = position
        self._delta = delta
        self.accepted = False
        self.ignored = False

    def angleDelta(self) -> QPoint:
        return QPoint(0, self._delta)

    def position(self) -> QPointF:
        return self._position

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


def _multi_tool_bundle(tmp_path: Path, *, count: int) -> AtlasDataBundle:
    base = _library_bundle(tmp_path)
    tools = tuple(
        ToolRecord(
            tool=f"828003{i:04d}/20",
            label=f"Tool 828003{i:04d}/20",
            compatible_eoats=("P4-EOAT-0052",),
            compatible_machines=("36", "52"),
            part_description=f"Demo tool family {i}",
        )
        for i in range(count)
    )
    machines = tuple(
        MachineRecord(
            machine=str(50 + i),
            label=f"Machine {50 + i}",
            robot_type="Engel Viper",
            compatible_eoats=("P4-EOAT-0052",),
            compatible_tools=(tools[i % count].tool,),
            documentation_score=91,
        )
        for i in range(max(2, min(count, 6)))
    )
    indexes = AtlasIndexes(
        eoat_by_id=base.indexes.eoat_by_id,
        eoats_by_tool={normalized_tool_key(tool.tool): ("P4-EOAT-0052",) for tool in tools},
        eoats_by_machine={normalized_machine_key(machine.machine): ("P4-EOAT-0052",) for machine in machines},
        machines_by_tool={normalized_tool_key(tool.tool): tuple(machine.machine for machine in machines) for tool in tools},
        machines_by_eoat={normalized_eoat_key("P4-EOAT-0052"): tuple(machine.machine for machine in machines)},
        tools_by_machine={normalized_machine_key(machine.machine): (tools[index % count].tool,) for index, machine in enumerate(machines)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at=base.loaded_at,
        eoats=base.eoats,
        tools=tools,
        machines=machines,
        indexes=indexes,
    )


def _multi_navigation_bundle(tmp_path: Path, *, count: int) -> AtlasDataBundle:
    eoats = []
    tools = []
    machines = []
    for index in range(count):
        eoat_id = f"P4-EOAT-{index + 1:04d}"
        tool_id = f"NAV-TOOL-{index + 1:04d}"
        machine_id = str(101 + index)
        eoats.append(
            EOATRecord(
                eoat_id=eoat_id,
                display_id=eoat_id,
                tools=(tool_id,),
                machines=(machine_id,),
                eoat_type="Vacuum",
                status="Installed",
                documentation=DocumentationStatus(score=86, status_label="Good"),
            )
        )
        tools.append(
            ToolRecord(
                tool=tool_id,
                label=f"Tool {tool_id}",
                compatible_eoats=(eoat_id,),
                compatible_machines=(machine_id,),
                part_description=f"Navigation test tool {index + 1}",
            )
        )
        machines.append(
            MachineRecord(
                machine=machine_id,
                label=f"Machine {machine_id}",
                robot_type="Engel Viper",
                compatible_eoats=(eoat_id,),
                compatible_tools=(tool_id,),
                current_eoat=eoat_id,
                documentation_score=90,
            )
        )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat.eoat_id): eoat.eoat_id for eoat in eoats},
        eoats_by_tool={normalized_tool_key(tool.tool): (eoats[index].eoat_id,) for index, tool in enumerate(tools)},
        eoats_by_machine={normalized_machine_key(machine.machine): (eoats[index].eoat_id,) for index, machine in enumerate(machines)},
        machines_by_tool={normalized_tool_key(tool.tool): (machines[index].machine,) for index, tool in enumerate(tools)},
        machines_by_eoat={normalized_eoat_key(eoat.eoat_id): (machines[index].machine,) for index, eoat in enumerate(eoats)},
        tools_by_machine={normalized_machine_key(machine.machine): (tools[index].tool,) for index, machine in enumerate(machines)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-01 12:00",
        eoats=tuple(eoats),
        tools=tuple(tools),
        machines=tuple(machines),
        indexes=indexes,
    )


def _machine36_bundle(tmp_path: Path) -> AtlasDataBundle:
    photo = PhotoItem(path=str(tmp_path / "P4-EOAT-0014.png"), filename="P4-EOAT-0014.png")
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0014",
        display_id="P4-EOAT-0014",
        tools=("8280030010/20",),
        machines=("36",),
        eoat_type="Mechanical / Gripper",
        status="Complete",
        connection_type="QD",
        documentation=DocumentationStatus(score=84, status_label="Good"),
        photos=PhotoSet(eoat_id="P4-EOAT-0014", photos=(photo,)),
    )
    tool = ToolRecord(
        tool="8280030010/20",
        label="Tool 8280030010/20",
        compatible_eoats=("P4-EOAT-0014",),
        compatible_machines=("36",),
        part_description="RATCHET GEAR",
    )
    machine = MachineRecord(
        machine="36",
        label="Machine 36",
        robot_type="Sytrama 811G",
        compatible_eoats=("P4-EOAT-0014",),
        compatible_tools=("8280030010/20",),
        current_eoat="P4-EOAT-0014",
        current_eoat_status="indexed",
        current_eoat_source="Audit AUD-36",
        current_eoat_confidence="high",
        current_eoat_resolution_reason="latest audit",
        documentation_score=91,
        source_rows=({"Audit ID": "AUD-36", "Audit Date": "2026-06-08", "Press/Machine #": "36", "EOAT Assembly ID": "P4-EOAT-0014", "Status": "Complete"},),
    )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat.eoat_id): eoat.eoat_id},
        eoats_by_tool={normalized_tool_key(tool.tool): (eoat.eoat_id,)},
        eoats_by_machine={normalized_machine_key("36"): (eoat.eoat_id,)},
        machines_by_tool={normalized_tool_key(tool.tool): ("36",)},
        machines_by_eoat={normalized_eoat_key(eoat.eoat_id): ("36",)},
        tools_by_machine={normalized_machine_key("36"): (tool.tool,)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-01 12:00",
        eoats=(eoat,),
        tools=(tool,),
        machines=(machine,),
        indexes=indexes,
    )


class _Controller:
    def __init__(self) -> None:
        self.recent: list[tuple[str, str]] = []
        self.settings = object()

    def record_recent(self, item_type: str, key: str) -> None:
        self.recent.append((item_type, key))
