from __future__ import annotations

import argparse
import os
import sys
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
    app.setStyleSheet(atlas_stylesheet())
    bundle = load_atlas_data(project_root, force_refresh=True)
    window = AtlasWindow(UserConfig(project_root=str(project_root)), auto_refresh=False)
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
        old_png.unlink()

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
    elif hasattr(page, "refresh"):
        page.refresh()


def _first_tool(bundle) -> str:
    if bundle.tools:
        return f"Tool {bundle.tools[0].tool}"
    if bundle.eoats and bundle.eoats[0].tools:
        return f"Tool {bundle.eoats[0].tools[0]}"
    return "Tool TOOL-A"


def _safe_slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "page"


if __name__ == "__main__":
    raise SystemExit(main())
