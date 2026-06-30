from __future__ import annotations

import argparse
import os
import shutil
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
    from app.atlas.command_palette import AtlasCommandPalette
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
    capture_settings = AtlasSettings(
        enable_qr_codes=True,
        photo_preload_mode="aggressive",
        hide_tools_missing_eoat_links=True,
        pinned_eoats=("AUD-20260518-001",),
        recent_eoats=("AUD-20260518-002",),
        pinned_machines=("101",),
        recent_machines=("102",),
        recent_tools=("TOOL-A",),
    )
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

    palette = AtlasCommandPalette(window, window)
    palette.open_with_query("tool")
    palette.show()
    app.processEvents()
    command_index = len(PAGE_LABELS) + 1
    palette.grab().save(str(output_dir / f"{command_index:02d}_command_palette.png"), "PNG")
    palette.close()

    _capture_photo_viewer(app, window, project_root, output_dir, command_index + 1)
    cleanup_dirs = []
    setup_capture_dir = _capture_setup_packet_page_states(app, window, output_dir, command_index + 2)
    if setup_capture_dir is not None:
        cleanup_dirs.append(setup_capture_dir)

    window.close()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    for folder in cleanup_dirs:
        _rmtree_with_retry(folder)
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


def _rmtree_with_retry(path: Path, attempts: int = 8) -> None:
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                return
            time.sleep(0.25)


def _prepare_page(window, key: str) -> None:
    from PySide6.QtWidgets import QCheckBox

    bundle = window.bundle
    window.show_page(key)
    page = window.pages[key]
    if bundle is None:
        return
    if key == "what" and hasattr(page, "run_query"):
        page.run_query(_first_tool(bundle))
        for checkbox in page.findChildren(QCheckBox):
            if "score breakdown" in checkbox.text().casefold():
                checkbox.setChecked(True)
                break
    elif key in {"eoats", "machines"} and hasattr(page, "filter") and (bundle.eoats if key == "eoats" else bundle.machines):
        page.filter.setText("")
        page.refresh()
        _select_first_data_row(page)
    elif key == "tools" and hasattr(page, "search"):
        page.search.setText(_first_tool(bundle))
    elif key == "setup_packet" and hasattr(page, "prefill_context") and bundle.eoats:
        eoat = bundle.eoats[0]
        page.prefill_context(
            machine_id=eoat.machines[0] if eoat.machines else "",
            tool_id=eoat.tools[0] if eoat.tools else "",
            eoat_id=eoat.eoat_id,
            context_label="Sidebar",
        )
    elif key == "photos" and hasattr(page, "filter") and bundle.eoats:
        page.filter.setText(bundle.eoats[0].eoat_id)
    elif key == "standards" and hasattr(page, "filter"):
        page.filter.setText("")
    elif key == "library" and hasattr(page, "search"):
        page.search.setText("standard")
    elif key == "diagnostics" and hasattr(page, "scroll"):
        page.refresh()
        page.scroll.verticalScrollBar().setValue(430)
    elif hasattr(page, "refresh"):
        page.refresh()


def _first_tool(bundle) -> str:
    for tool in bundle.tools:
        if getattr(tool, "compatible_eoats", ()):
            return f"Tool {tool.tool}"
    if bundle.tools:
        return f"Tool {bundle.tools[0].tool}"
    if bundle.eoats and bundle.eoats[0].tools:
        return f"Tool {bundle.eoats[0].tools[0]}"
    return "Tool TOOL-A"


def _select_first_data_row(page) -> None:
    list_widget = getattr(page, "list", None)
    if list_widget is None:
        return
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        if item.data(0x0100) is not None:
            list_widget.setCurrentRow(index)
            return


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


def _capture_photo_viewer(app, window, project_root: Path, output_dir: Path, index: int) -> None:
    import tempfile

    from app.atlas.pages import PhotoCarouselDialog
    from core.atlas_models import PhotoItem, PhotoSet

    if not window.bundle or not window.bundle.eoats:
        return
    with tempfile.TemporaryDirectory(prefix="atlas_viewer_capture_") as temp_root:
        temp_dir = Path(temp_root)
        photo_paths = _write_viewer_capture_images(temp_dir)
        eoat = replace(
            window.bundle.eoats[0],
            photos=PhotoSet(
                eoat_id=window.bundle.eoats[0].eoat_id,
                folder_path=str(temp_dir),
                folder_exists=True,
                photos=tuple(
                    PhotoItem(path=str(path), filename=path.name, category="Demo", eoat_id=window.bundle.eoats[0].eoat_id)
                    for path in photo_paths
                ),
            ),
        )
        dialog = PhotoCarouselDialog(eoat, parent=window)
        dialog.resize(1040, 720)
        dialog.show()
        for _ in range(30):
            app.processEvents()
            time.sleep(0.03)
        dialog.grab().save(str(output_dir / f"{index:02d}_photo_viewer_carousel.png"), "PNG")
        dialog.close()


def _capture_setup_packet_page_states(app, window, output_dir: Path, start_index: int) -> Path | None:
    import tempfile

    from app.atlas.pages import _SetupPacketPdfViewerDialog, _write_setup_packet_sidecar
    from core.atlas_setup_packets import PHOTO_NONE, SetupPacketOptions, build_setup_packet_context
    from core.setup_packet_pdf import export_setup_packet_pdf

    bundle = window.bundle
    if bundle is None or not bundle.eoats:
        return None
    eoat = bundle.eoats[0]
    tool_id = eoat.tools[0] if eoat.tools else (bundle.tools[0].tool if bundle.tools else "")
    machine_id = eoat.machines[0] if eoat.machines else (bundle.machines[0].machine if bundle.machines else "")
    window.open_setup_packet(
        machine=machine_id,
        tool=tool_id,
        eoat=eoat.eoat_id,
        context_label="Screenshot Capture",
    )
    page = window.pages["setup_packet"]
    page.advanced_toggle.setChecked(True)
    app.processEvents()
    window.grab().save(str(output_dir / f"{start_index:02d}_setup_packet_options.png"), "PNG")

    temp_root = Path(tempfile.mkdtemp(prefix="atlas_setup_packet_capture_"))
    context = build_setup_packet_context(
        bundle,
        machine_id,
        tool_id,
        eoat.eoat_id,
        SetupPacketOptions(photo_inclusion=PHOTO_NONE),
    )
    result = export_setup_packet_pdf(context, temp_root)
    _write_setup_packet_sidecar(result.path, context)
    page._set_latest_packet(result.path, context=context)
    page._sync_generate_state()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    window.grab().save(str(output_dir / f"{start_index + 1:02d}_setup_packet_result.png"), "PNG")
    viewer = _SetupPacketPdfViewerDialog(result.path, parent=window)
    viewer.resize(1180, 820)
    viewer.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    viewer.grab().save(str(output_dir / f"{start_index + 2:02d}_setup_packet_pdf_viewer.png"), "PNG")
    viewer.close()
    viewer.deleteLater()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    return temp_root


def _write_viewer_capture_images(folder: Path) -> list[Path]:
    from PIL import Image, ImageDraw

    colors = ["#2f80ed", "#087f5b", "#d80621", "#3d6f8f"]
    paths: list[Path] = []
    for index, color in enumerate(colors, start=1):
        image = Image.new("RGB", (980, 620), color)
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 40, 940, 580), outline="white", width=6)
        draw.text((74, 76), f"EOAT Atlas demo photo {index}", fill="white")
        draw.text((74, 120), "Carousel / gallery capture", fill="white")
        path = folder / f"atlas_demo_photo_{index}.png"
        image.save(path)
        paths.append(path)
    return paths


def _safe_slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "page"


if __name__ == "__main__":
    raise SystemExit(main())
