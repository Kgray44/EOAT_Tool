from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from app.atlas.pages import InformationLibraryPage, _build_information_entries, _information_score, _load_photo_pixmap
from app.atlas.settings import AtlasSettings, load_atlas_settings, save_atlas_settings
from app.atlas.styles import atlas_stylesheet
from core.atlas_data_loader import invalidate_atlas_data_cache, load_atlas_data
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_atlas_settings_persist_color_scheme(tmp_path: Path) -> None:
    settings_path = tmp_path / "atlas_settings.json"
    save_atlas_settings(AtlasSettings(theme="dark", color_scheme="nolato_logo"), settings_path)

    loaded = load_atlas_settings(settings_path)

    assert loaded.theme == "dark"
    assert loaded.color_scheme == "nolato_logo"
    assert AtlasSettings(color_scheme="mystery").normalized().color_scheme == "atlas_blue"


def test_nolato_stylesheet_uses_logo_accent_tokens() -> None:
    light = atlas_stylesheet("light", "nolato_logo")
    dark = atlas_stylesheet("dark", "nolato_logo")

    assert "#d80621" in light
    assert "#ff4b5f" in dark
    assert "QTreeWidget#InformationTree" in light


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
    assert any(entry.tree_path[0] == "Atlas App Help" for entry in page.entries)
    assert any("Standardization" in entry.title or "Design Guidelines" in entry.title for entry in page.entries)
    assert any(_information_score(entry, "photos documentation") > 0 for entry in page.entries)

    page.search.setText("photo viewer")
    assert page.filtered_entries
    assert _tree_leaf_count(page) == len(page.filtered_entries)


def _tree_leaf_count(page: InformationLibraryPage) -> int:
    count = 0
    stack = [page.tree.topLevelItem(index) for index in range(page.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.data(0, Qt.ItemDataRole.UserRole):
            count += 1
        stack.extend(item.child(index) for index in range(item.childCount()))
    return count
