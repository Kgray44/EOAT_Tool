from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QLabel, QPushButton

from app.atlas.pages import (
    CompareDialog,
    InformationLibraryPage,
    PhotoCarouselDialog,
    PhotosPage,
    ToolSearchPage,
    _build_information_entries,
    _information_score,
    _load_photo_pixmap,
    _tool_compare_rows,
)
from app.atlas.photo_loader import PhotoLoadManager
from app.atlas.settings import AtlasSettings, load_atlas_settings, save_atlas_settings
from app.atlas.styles import atlas_stylesheet
from core.atlas_data_loader import invalidate_atlas_data_cache, load_atlas_data
from core.atlas_exports import qr_payload_warning
from core.atlas_information_library import validate_information_library
from core.atlas_models import EOATRecord, PhotoItem, PhotoSet, ToolRecord
from core.atlas_recommendations import recommend_for_query
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_atlas_settings_persist_color_scheme(tmp_path: Path) -> None:
    settings_path = tmp_path / "atlas_settings.json"
    save_atlas_settings(
        AtlasSettings(
            theme="dark",
            color_scheme="aurora_tech",
            photo_preload_mode="balanced",
            enable_qr_codes=True,
            qr_payload_mode="json",
            qr_error_correction="quartile",
            qr_default_label_size="large",
            qr_show_payload_preview_before_export=False,
            qr_warn_phone_like_payloads=False,
            command_palette_enabled=False,
            hide_tools_missing_eoat_links=True,
            recent_eoats=("EOAT-1",),
            pinned_machines=("101",),
        ),
        settings_path,
    )

    loaded = load_atlas_settings(settings_path)

    assert loaded.theme == "dark"
    assert loaded.color_scheme == "aurora_tech"
    assert loaded.photo_preload_mode == "balanced"
    assert loaded.enable_qr_codes is True
    assert loaded.qr_payload_mode == "json"
    assert loaded.qr_error_correction == "quartile"
    assert loaded.qr_default_label_size == "large"
    assert loaded.qr_show_payload_preview_before_export is False
    assert loaded.qr_warn_phone_like_payloads is True
    assert loaded.command_palette_enabled is False
    assert loaded.hide_tools_missing_eoat_links is True
    assert loaded.recent_eoats == ("EOAT-1",)
    assert loaded.pinned_machines == ("101",)
    assert AtlasSettings(color_scheme="mystery").normalized().color_scheme == "atlas_blue"
    assert AtlasSettings(photo_preload_mode="wild").normalized().photo_preload_mode == "conservative"
    assert AtlasSettings(qr_payload_mode="id_only").normalized().qr_payload_mode == "compact"


def test_nolato_stylesheet_uses_logo_accent_tokens() -> None:
    light = atlas_stylesheet("light", "nolato_logo")
    graphite = atlas_stylesheet("light", "industrial_graphite")
    aurora_dark = atlas_stylesheet("dark", "aurora_tech")

    assert "#d80621" in light
    assert "#3d6f8f" in graphite
    assert "#4ca3ff" in aurora_dark
    assert "QTreeWidget#InformationTree" in light
    assert "QPushButton#HeroDisabledButton" in aurora_dark


def test_photo_loader_decodes_png_and_reports_heic_failure(qapp, tmp_path: Path) -> None:
    png_path = tmp_path / "preview.png"
    image = QImage(18, 12, QImage.Format.Format_RGB32)
    image.fill(QColor("#d80621"))
    assert image.save(str(png_path), "PNG")

    png_result = _load_photo_pixmap(str(png_path))
    assert png_result.state == "loaded"
    assert not png_result.pixmap.isNull()

    heic_path = tmp_path / "preview.HEIC"
    heic_path.write_bytes(b"not a real heic file")
    heic_result = _load_photo_pixmap(str(heic_path))

    assert heic_result.state in {"unsupported_format", "decode_failed"}
    assert heic_result.message
    assert heic_result.pixmap.isNull()


def test_information_library_tree_represents_all_filtered_entries(qapp, tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    standard = root / "EOAT Standardization Guide.md"
    standard.write_text("# Design Guidelines\n\nKeep EOAT records complete and photos useful.\n", encoding="utf-8")
    invalidate_atlas_data_cache(root)
    bundle = load_atlas_data(root, force_refresh=True)

    class Controller:
        settings = AtlasSettings()

        def show_status(self, _message: str) -> None:
            return None

    page = InformationLibraryPage(Controller())
    page.set_bundle(bundle)

    assert len(page.entries) == len(_build_information_entries(bundle))
    assert _tree_leaf_count(page) == len(page.filtered_entries)
    assert not _has_duplicate_parent_child(page)
    assert any(entry.tree_path[0] == "Atlas App Help" for entry in page.entries)
    assert any("Standardization" in entry.title or "Design Guidelines" in entry.title for entry in page.entries)
    assert {
        "app_help",
        "eoat_standard",
        "compatibility_rule",
        "data_dictionary",
        "troubleshooting",
        "report_guide",
        "pm_inspection",
        "source_document",
    }.issubset({entry.entry_type for entry in page.entries})
    assert not validate_information_library(page.entries)
    assert any(_information_score(entry, "photos documentation") > 0 for entry in page.entries)
    assert any(entry.title == "Off-Machine EOAT Audit Handling" and entry.examples for entry in page.entries)
    assert all(entry.source.file_label != "-" for entry in page.entries)

    page.search.setText("photo viewer")
    assert page.filtered_entries
    assert _tree_leaf_count(page) == len(page.filtered_entries)
    assert not _has_duplicate_parent_child(page)


def test_photo_load_manager_caches_loaded_images(qapp, tmp_path: Path) -> None:
    png_path = tmp_path / "cached.png"
    image = QImage(24, 18, QImage.Format.Format_RGB32)
    image.fill(QColor("#147dff"))
    assert image.save(str(png_path), "PNG")

    manager = PhotoLoadManager()
    seen = []
    manager.image_ready.connect(lambda request_id, result: seen.append((request_id, result)))
    manager.request_image(str(png_path), request_id="first")
    _wait_for(lambda: len(seen) == 1, qapp)
    manager.request_image(str(png_path), request_id="second")
    _wait_for(lambda: len(seen) == 2, qapp)

    assert seen[0][1].state == "loaded"
    assert seen[1][1].from_cache is True
    assert manager.stats()["cache_entries"] >= 1


def test_photo_preloader_queues_idle_jobs_in_aggressive_mode(qapp, tmp_path: Path) -> None:
    paths = []
    for index in range(3):
        png_path = tmp_path / f"preload_{index}.png"
        image = QImage(28, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("#2f80ed"))
        assert image.save(str(png_path), "PNG")
        paths.append(png_path)
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0001",
        display_id="P4-EOAT-0001",
        photos=PhotoSet(
            eoat_id="P4-EOAT-0001",
            photos=tuple(PhotoItem(path=str(path), filename=path.name, eoat_id="P4-EOAT-0001") for path in paths),
        ),
    )
    manager = PhotoLoadManager()
    manager.set_preload_mode("aggressive")
    manager.set_photo_catalog([eoat])
    manager.set_ui_ready_for_preload(True)
    manager._last_activity = time.perf_counter() - 5
    manager._last_lag_ms = 0
    manager._scheduler_tick()
    assert manager.stats()["jobs_queued"] + manager.stats()["active_jobs"] + manager.stats()["cache_entries"] > 0
    _wait_for(lambda: manager.stats()["cache_entries"] >= 1, qapp)
    assert "preload" in str(manager.stats()["last_preload_reason"]).casefold()


def test_photo_preloader_waits_until_ui_ready(qapp, tmp_path: Path) -> None:
    png_path = tmp_path / "wait_until_ready.png"
    image = QImage(28, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f80ed"))
    assert image.save(str(png_path), "PNG")
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0001",
        display_id="P4-EOAT-0001",
        photos=PhotoSet(
            eoat_id="P4-EOAT-0001",
            photos=(PhotoItem(path=str(png_path), filename=png_path.name, eoat_id="P4-EOAT-0001"),),
        ),
    )
    manager = PhotoLoadManager()
    manager.set_preload_mode("aggressive")
    manager.set_photo_catalog([eoat])
    manager._last_activity = time.perf_counter() - 5
    manager._last_lag_ms = 0

    manager._scheduler_tick()
    assert manager.stats()["jobs_queued"] == 0
    assert manager.stats()["active_jobs"] == 0
    assert manager.stats()["cache_entries"] == 0
    assert manager.stats()["last_preload_reason"] == "Paused: app loading"

    manager.set_ui_ready_for_preload(True)
    manager._last_activity = time.perf_counter() - 5
    manager._scheduler_tick()
    assert manager.stats()["jobs_queued"] + manager.stats()["active_jobs"] + manager.stats()["cache_entries"] > 0


def test_photo_preloader_drops_queued_jobs_on_user_activity(qapp, tmp_path: Path) -> None:
    paths = []
    for index in range(4):
        png_path = tmp_path / f"user_active_{index}.png"
        image = QImage(36, 28, QImage.Format.Format_RGB32)
        image.fill(QColor("#2f80ed"))
        assert image.save(str(png_path), "PNG")
        paths.append(png_path)
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0001",
        display_id="P4-EOAT-0001",
        photos=PhotoSet(
            eoat_id="P4-EOAT-0001",
            photos=tuple(PhotoItem(path=str(path), filename=path.name, eoat_id="P4-EOAT-0001") for path in paths),
        ),
    )
    manager = PhotoLoadManager()
    manager.set_preload_mode("aggressive")
    manager.set_photo_catalog([eoat])
    manager.set_ui_ready_for_preload(True)
    manager._last_activity = time.perf_counter() - 5
    manager._last_lag_ms = 0

    manager._scheduler_tick()
    assert manager.stats()["jobs_queued"] > 0
    assert manager.stats()["active_jobs"] <= manager.max_active_preload_workers

    manager.mark_user_activity()

    assert manager.stats()["jobs_queued"] == 0
    assert manager.stats()["last_preload_reason"] == "Paused: user active"


def test_photo_preloader_does_not_enqueue_when_cache_is_full(qapp, tmp_path: Path) -> None:
    cached_path = tmp_path / "cached_full.png"
    next_path = tmp_path / "blocked_preload.png"
    for path in (cached_path, next_path):
        image = QImage(36, 28, QImage.Format.Format_RGB32)
        image.fill(QColor("#2f80ed"))
        assert image.save(str(path), "PNG")
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0001",
        display_id="P4-EOAT-0001",
        photos=PhotoSet(
            eoat_id="P4-EOAT-0001",
            photos=(PhotoItem(path=str(next_path), filename=next_path.name, eoat_id="P4-EOAT-0001"),),
        ),
    )
    manager = PhotoLoadManager(max_entries=1)
    manager.image_ready.connect(lambda *_args: None)
    manager.request_image(str(cached_path), request_id="foreground")
    _wait_for(lambda: manager.stats()["cache_entries"] == 1, qapp)
    manager.set_preload_mode("aggressive")
    manager.set_ui_ready_for_preload(True)
    manager.set_photo_catalog([eoat])
    manager._last_activity = time.perf_counter() - 5
    manager._last_lag_ms = 0

    for _ in range(3):
        manager._scheduler_tick()
        qapp.processEvents()

    stats = manager.stats()
    assert stats["cache_status"] == "Cache full"
    assert stats["jobs_queued"] == 0
    assert stats["active_jobs"] == 0
    assert "Photo cache full" in str(stats["last_preload_reason"])


def test_clearing_full_photo_cache_allows_queueing_to_resume(qapp, tmp_path: Path) -> None:
    cached_path = tmp_path / "cached_resume.png"
    next_path = tmp_path / "resume_preload.png"
    for path in (cached_path, next_path):
        image = QImage(36, 28, QImage.Format.Format_RGB32)
        image.fill(QColor("#087f5b"))
        assert image.save(str(path), "PNG")
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0001",
        display_id="P4-EOAT-0001",
        photos=PhotoSet(
            eoat_id="P4-EOAT-0001",
            photos=(PhotoItem(path=str(next_path), filename=next_path.name, eoat_id="P4-EOAT-0001"),),
        ),
    )
    manager = PhotoLoadManager(max_entries=1)
    manager.request_image(str(cached_path), request_id="foreground")
    _wait_for(lambda: manager.stats()["cache_entries"] == 1, qapp)
    manager.set_preload_mode("aggressive")
    manager.set_ui_ready_for_preload(True)
    manager.set_photo_catalog([eoat])
    manager._last_activity = time.perf_counter() - 5
    manager._last_lag_ms = 0
    manager._scheduler_tick()
    assert manager.stats()["cache_status"] == "Cache full"

    manager.clear_cache()
    manager._last_activity = time.perf_counter() - 5
    manager._scheduler_tick()

    assert manager.stats()["jobs_queued"] + manager.stats()["active_jobs"] + manager.stats()["cache_entries"] > 0


def test_photo_user_request_promotes_existing_preload_job(qapp, tmp_path: Path) -> None:
    png_path = tmp_path / "promote_preload.png"
    image = QImage(36, 28, QImage.Format.Format_RGB32)
    image.fill(QColor("#2f80ed"))
    assert image.save(str(png_path), "PNG")
    manager = PhotoLoadManager()
    manager.set_preload_mode("aggressive")
    manager.set_ui_ready_for_preload(True)

    manager.request_image(str(png_path), request_id="preload", priority=5)
    assert manager.stats()["jobs_queued"] == 1
    assert manager._job_queue[0].priority == 5

    manager.request_image(str(png_path), request_id="foreground", priority=0)

    assert manager.stats()["jobs_queued"] + manager.stats()["active_jobs"] >= 1
    assert all(job.priority == 0 for job in manager._job_queue)


def test_photo_viewer_carousel_instantiates_and_changes_selected_photo(qapp, tmp_path: Path) -> None:
    photos = []
    for index, color in enumerate(["#d80621", "#2f80ed"]):
        png_path = tmp_path / f"carousel_{index}.png"
        image = QImage(32, 24, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        assert image.save(str(png_path), "PNG")
        photos.append(PhotoItem(path=str(png_path), filename=png_path.name, category="Overall"))
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0001",
        display_id="P4-EOAT-0001",
        photos=PhotoSet(eoat_id="P4-EOAT-0001", folder_path=str(tmp_path), photos=tuple(photos)),
    )

    dialog = PhotoCarouselDialog(eoat, parent=None)
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    assert len(dialog.thumbnails) == 2
    dialog.select_photo(1)
    qapp.processEvents()
    assert dialog.index == 1
    assert dialog.count_label.text() == "2 / 2"
    assert dialog.thumbnails[1].property("selected") is True
    dialog.close()


def test_photos_page_tree_selects_eoat_and_opens_detail_panel(qapp, tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    invalidate_atlas_data_cache(root)
    bundle = load_atlas_data(root, force_refresh=True)
    controller = _ControllerStub()
    page = PhotosPage(controller)

    page.set_bundle(bundle)
    qapp.processEvents()

    assert page.tree.topLevelItemCount() >= 4
    assert page.current is not None
    first_id = page.current.eoat_id
    target = next((record for record in bundle.eoats if record.eoat_id != first_id), bundle.eoats[0])
    item = _find_tree_item(page.tree, target.eoat_id)
    assert item is not None

    page.tree.setCurrentItem(item)
    qapp.processEvents()

    assert page.current is not None
    assert page.current.eoat_id == target.eoat_id
    assert "Photo Category Checklist" in _widget_text(page.detail_panel)


def test_tool_page_list_selects_tool_and_opens_detail_panel(qapp, tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    invalidate_atlas_data_cache(root)
    bundle = load_atlas_data(root, force_refresh=True)
    controller = _ControllerStub()
    page = ToolSearchPage(controller)

    page.set_bundle(bundle)
    qapp.processEvents()

    assert page.list.count() > 0
    assert page.current_tool is not None
    target = bundle.tools[-1]
    item = _find_list_item(page.list, target.tool)
    assert item is not None

    page.list.setCurrentItem(item)
    qapp.processEvents()

    assert page.current_tool is not None
    assert page.current_tool.tool == target.tool
    assert "Tool Actions" in _widget_text(page.detail_panel)


def test_tool_missing_eoat_filter_hides_missing_link_tools(qapp, tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    bundle = load_atlas_data(root, force_refresh=True)
    missing = ToolRecord(tool="MISSING-EOAT", label="Tool MISSING-EOAT", compatible_machines=("101",), source="Unit Test")
    bundle = replace(bundle, tools=tuple([*bundle.tools, missing]))
    controller = _ControllerStub(settings=AtlasSettings(hide_tools_missing_eoat_links=True))
    page = ToolSearchPage(controller)

    page.set_bundle(bundle)
    qapp.processEvents()

    assert _find_list_item(page.list, "MISSING-EOAT") is None
    page.hide_missing_check.setChecked(False)
    page.refresh()
    qapp.processEvents()
    assert _find_list_item(page.list, "MISSING-EOAT") is not None


def test_what_do_i_need_scoring_explanation_has_points_and_polarity(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    bundle = load_atlas_data(root, force_refresh=True)

    result = recommend_for_query(bundle, "Tool TOOL-A")

    assert result.best is not None
    assert result.best.factors
    assert sum(factor.points for factor in result.best.factors) == result.best.score
    assert any(factor.polarity == "positive" and factor.points > 0 for factor in result.best.factors)
    assert any(factor.polarity in {"negative", "neutral"} for factor in result.best.factors)


def test_compare_dialog_instantiates_in_light_and_dark_themes(qapp, tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    bundle = load_atlas_data(root, force_refresh=True)
    records = list(bundle.tools[:2])
    rows = _tool_compare_rows(records)
    columns = [f"Tool {record.tool}" for record in records]

    for theme in ("light", "dark"):
        qapp.setStyleSheet(atlas_stylesheet(theme, "atlas_blue"))
        dialog = CompareDialog("Tool Compare", rows, columns)
        dialog.show()
        qapp.processEvents()
        assert dialog.objectName() == "CompareDialog"
        assert dialog.isVisible()
        assert "Different" in _widget_text(dialog) or "Same" in _widget_text(dialog)
        dialog.close()


def test_dialog_styles_and_qr_warning_text_are_readable() -> None:
    dark = atlas_stylesheet("dark", "atlas_blue")
    light = atlas_stylesheet("light", "atlas_blue")

    assert "QDialog, QMessageBox" in dark
    assert "QDialog#CompareDialog" in dark
    assert "#e5edf7" in dark
    assert "QMessageBox QPushButton" in light
    assert "Full Offline Record mode creates a large QR payload" in qr_payload_warning("EOAT_ATLAS_FULL_RECORD\n" + ("X" * 950), mode="full")


class _ControllerStub:
    def __init__(self, settings: AtlasSettings | None = None):
        self.settings = settings or AtlasSettings()
        self.opened: list[tuple[str, str]] = []
        self.status_messages: list[str] = []

    def record_recent(self, item_type: str, key: str) -> None:
        self.opened.append((f"recent:{item_type}", key))

    def is_pinned(self, _item_type: str, _key: str) -> bool:
        return False

    def open_eoat(self, eoat_id: str) -> None:
        self.opened.append(("eoat", eoat_id))

    def open_machine(self, machine: str) -> None:
        self.opened.append(("machine", machine))

    def open_tool(self, tool: str) -> None:
        self.opened.append(("tool", tool))

    def open_recommendation(self, query: str) -> None:
        self.opened.append(("recommendation", query))

    def show_status(self, message: str) -> None:
        self.status_messages.append(message)

    def update_settings(self, settings: AtlasSettings) -> None:
        self.settings = settings.normalized()


def _tree_leaf_count(page: InformationLibraryPage) -> int:
    count = 0
    stack = [page.tree.topLevelItem(index) for index in range(page.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.data(0, Qt.ItemDataRole.UserRole):
            count += 1
        stack.extend(item.child(index) for index in range(item.childCount()))
    return count


def _has_duplicate_parent_child(page: InformationLibraryPage) -> bool:
    stack = [page.tree.topLevelItem(index) for index in range(page.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        for index in range(item.childCount()):
            child = item.child(index)
            if item.text(0).casefold() == child.text(0).casefold():
                return True
            stack.append(child)
    return False


def _find_tree_item(tree, text: str):
    stack = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    folded = text.casefold()
    while stack:
        item = stack.pop()
        if folded in item.text(0).casefold():
            return item
        stack.extend(item.child(index) for index in range(item.childCount()))
    return None


def _find_list_item(list_widget, tool: str):
    folded = tool.casefold()
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        record = item.data(Qt.ItemDataRole.UserRole)
        if getattr(record, "tool", "").casefold() == folded:
            return item
    return None


def _widget_text(widget) -> str:
    texts = []
    for child in [*widget.findChildren(QLabel), *widget.findChildren(QPushButton)]:
        value = child.text()
        if value:
            texts.append(value)
    return "\n".join(texts)


def _wait_for(predicate, qapp, *, attempts: int = 80) -> None:
    for _ in range(attempts):
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.025)
    assert predicate()
