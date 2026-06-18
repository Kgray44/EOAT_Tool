from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT_DIR = Path("EOAT_Atlas_pages")
DEFAULT_SIZE = (1400, 900)


def main() -> int:
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from app.atlas.atlas_window import PAGE_LABELS, AtlasWindow
    from app.atlas.settings import AtlasSettings
    from app.atlas.styles import atlas_stylesheet
    from core.atlas_data_loader import load_atlas_data
    from core.config import UserConfig
    from core.resources import resource_path

    parser = argparse.ArgumentParser(description="Capture one current screenshot for every EOAT Atlas page.")
    parser.add_argument("--project-root", default=str(resource_path("examples/demo_project")))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--width", type=int, default=DEFAULT_SIZE[0])
    parser.add_argument("--height", type=int, default=DEFAULT_SIZE[1])
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    output_dir = Path(args.output_dir).resolve()

    app = QApplication.instance() or QApplication(sys.argv)
    _register_capture_font(app, QFont, QFontDatabase)
    capture_settings = AtlasSettings()
    app.setStyleSheet(atlas_stylesheet(capture_settings.effective_theme, capture_settings.color_scheme))
    bundle = _sanitize_demo_bundle(load_atlas_data(project_root, force_refresh=True), project_root)
    window = AtlasWindow(UserConfig(project_root=str(project_root)), auto_refresh=False, settings=capture_settings)
    window.resize(args.width, args.height)
    window.bundle = bundle
    for page in window.pages.values():
        if hasattr(page, "set_bundle"):
            page.set_bundle(bundle)
    window.status_label.setText(f"Screenshot data: {bundle.loaded_at}")
    window.show()
    app.processEvents()

    output_dir.mkdir(parents=True, exist_ok=True)
    for old_png in output_dir.glob("*.png"):
        _unlink_with_retry(old_png)

    for index, (key, label) in enumerate(PAGE_LABELS, start=1):
        _prepare_page(window, key)
        app.processEvents()
        pixmap = window.grab()
        filename = f"{index:02d}_{_safe_slug(label)}.png"
        pixmap.save(str(output_dir / filename), "PNG")

    window.close()
    return 0


def _register_capture_font(app, qfont, qfont_database) -> None:
    for font_path in [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"]:
        if not font_path.exists():
            continue
        font_id = qfont_database.addApplicationFont(str(font_path))
        families = qfont_database.applicationFontFamilies(font_id) if font_id >= 0 else []
        if families:
            app.setFont(qfont(families[0], 10))
            return


def _unlink_with_retry(path: Path, attempts: int = 8) -> None:
    for attempt in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25)


def _prepare_page(window, key: str) -> None:
    bundle = window.bundle
    window.show_page(key)
    page = window.pages[key]
    if bundle is None:
        return
    if key == "what" and hasattr(page, "run_query"):
        page.run_query(_first_tool(bundle))
    elif key == "eoats" and hasattr(page, "open_record") and bundle.eoats:
        page.open_record(bundle.eoats[0].eoat_id)
    elif key == "machines" and hasattr(page, "open_record") and bundle.machines:
        page.open_record(bundle.machines[0].machine)
    elif key == "tools" and hasattr(page, "search"):
        page.search.setText(_first_tool(bundle))
    elif key == "photos" and hasattr(page, "filter") and bundle.eoats:
        page.filter.setText(bundle.eoats[0].eoat_id)
    elif key == "standards" and hasattr(page, "filter"):
        page.filter.setText("")
    elif key == "library" and hasattr(page, "search"):
        page.search.setText("standard")
    elif hasattr(page, "refresh"):
        page.refresh()


def _first_tool(bundle) -> str:
    if bundle.tools:
        return f"Tool {bundle.tools[0].tool}"
    if bundle.eoats and bundle.eoats[0].tools:
        return f"Tool {bundle.eoats[0].tools[0]}"
    return "Tool TOOL-A"


def _sanitize_demo_bundle(bundle, project_root: Path):
    display_root = "examples/demo_project"
    root_variants = {
        str(project_root),
        str(project_root.resolve(strict=False)),
    }
    root_variants |= {value.replace("\\", "/") for value in root_variants}

    def clean(value):
        if not isinstance(value, str):
            return value
        cleaned = value
        for root in sorted(root_variants, key=len, reverse=True):
            cleaned = cleaned.replace(root, display_root)
        if display_root in cleaned:
            cleaned = cleaned.replace("\\", "/")
        return cleaned

    def clean_warning(warning):
        return replace(
            warning,
            message=clean(warning.message),
            why_it_matters=clean(warning.why_it_matters),
            suggested_fix=clean(warning.suggested_fix),
        )

    def clean_standard(standard):
        return replace(standard, path=clean(standard.path), snippet=clean(standard.snippet))

    def clean_photo(photo):
        return replace(photo, path=clean(photo.path))

    def clean_photo_set(photo_set):
        return replace(
            photo_set,
            folder_path=clean(photo_set.folder_path),
            photos=tuple(clean_photo(photo) for photo in photo_set.photos),
            indexed_photos=tuple(clean_photo(photo) for photo in photo_set.indexed_photos),
        )

    def clean_eoat(eoat):
        return replace(
            eoat,
            photos=clean_photo_set(eoat.photos),
            warnings=tuple(clean_warning(warning) for warning in eoat.warnings),
            standards=tuple(clean_standard(standard) for standard in eoat.standards),
        )

    def clean_machine(machine):
        return replace(machine, warnings=tuple(clean_warning(warning) for warning in machine.warnings))

    def clean_tool(tool):
        return replace(tool, warnings=tuple(clean_warning(warning) for warning in tool.warnings))

    indexes = replace(
        bundle.indexes,
        photos_by_eoat={key: tuple(clean(path) for path in paths) for key, paths in bundle.indexes.photos_by_eoat.items()},
        photos_by_tool={key: tuple(clean(path) for path in paths) for key, paths in bundle.indexes.photos_by_tool.items()},
        warnings_by_eoat={
            key: tuple(clean_warning(warning) for warning in warnings)
            for key, warnings in bundle.indexes.warnings_by_eoat.items()
        },
        warnings_by_machine={
            key: tuple(clean_warning(warning) for warning in warnings)
            for key, warnings in bundle.indexes.warnings_by_machine.items()
        },
    )
    return replace(
        bundle,
        project_root=display_root,
        source_statuses=tuple(
            replace(status, path=clean(status.path), message=clean(status.message))
            for status in bundle.source_statuses
        ),
        eoats=tuple(clean_eoat(eoat) for eoat in bundle.eoats),
        machines=tuple(clean_machine(machine) for machine in bundle.machines),
        tools=tuple(clean_tool(tool) for tool in bundle.tools),
        standards=tuple(clean_standard(standard) for standard in bundle.standards),
        warnings=tuple(clean_warning(warning) for warning in bundle.warnings),
        indexes=indexes,
    )


def _safe_slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "page"


if __name__ == "__main__":
    raise SystemExit(main())
