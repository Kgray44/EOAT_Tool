"""Capture real PySide Minimalist shell references for Project Mirrorline.

The script is intentionally isolated: it uses the deterministic test bundle,
offscreen Qt, fixed fonts, and an output directory outside the source tree.
It never opens a production data source or enables writes.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"))
os.environ.setdefault("QT_SCALE_FACTOR", "1")
os.environ.setdefault("QT_FONT_DPI", "96")
os.environ.setdefault("EOAT_DISABLE_GLOBAL_TYPE_SEARCH", "1")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.atlas.minimalist.home import AtlasMinimalistHomePage  # noqa: E402
from app.atlas.minimalist.window import MinimalistAtlasWindow  # noqa: E402
from core.config import UserConfig  # noqa: E402
from core.data_freshness import PollingState  # noqa: E402
from core.fit_check_service import FitCheckRequest  # noqa: E402
from core.versioning import get_app_version  # noqa: E402
from tests.test_minimalist_dropdown_lifecycle import _dropdown_bundle  # noqa: E402


class CaptureController:
    current_page_key = "minimalist_home"

    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            pinned_eoats=[], pinned_machines=[], pinned_tools=[], recent_eoats=[], recent_machines=["52"], recent_tools=[]
        )
        self.recent: list[tuple[str, str]] = []

    def record_recent(self, item_type: str, key: str) -> None:
        self.recent.append((item_type, key))

    def show_status(self, _message: str) -> None:
        pass

    def show_page(self, key: str) -> None:
        self.current_page_key = key

    def open_eoat(self, _key: str) -> None:
        pass

    def open_machine(self, _key: str) -> None:
        pass

    def open_tool(self, _key: str) -> None:
        pass


def capture(output: Path) -> list[str]:
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setFont(app.font())
    controller = CaptureController()
    page = AtlasMinimalistHomePage(controller)
    page.resize(1760, 1080)
    page.set_bundle(_dropdown_bundle(output))
    page.show()
    app.processEvents()
    names: list[str] = []

    def grab(name: str) -> None:
        QTest.qWait(280)
        app.processEvents()
        image = page.grab().toImage()
        target = output / f"{name}.png"
        if image.isNull() or not image.save(str(target)):
            raise RuntimeError(f"could not capture {name}")
        names.append(name)

    grab("home-dark")
    page.home_content.card.focus_search_text("")
    grab("home-recents")
    page.home_content.card.focus_search_text("P4-EOAT-0052")
    QTest.qWait(150)
    app.processEvents()
    grab("home-live-search")
    page.home_content.card.close_search_dropdown()
    page.shell.set_theme_preference("light")
    grab("home-light")
    page.shell.set_theme_preference("dark")
    page.shell.open_menu()
    grab("navigation-home")
    for name, active in (("navigation-fit-check", "fit_check"), ("navigation-library", "library"), ("navigation-settings", "settings")):
        page.shell.set_active_nav(active)
        grab(name)
    page.shell.close_overlays(immediate=True)
    page.shell.open_search()
    grab("global-search")
    page.close()
    app.processEvents()
    _capture_library_states(app, output, names)
    return names


def _capture_library_states(app: QApplication, output: Path, names: list[str]) -> None:
    """Capture the real desktop Library through the production shell.

    The fixture bundle is the same controlled bundle used by the home capture.
    Its temporary project root lives beside the external artifact output, so
    this capture never reads or writes a user profile or operational source.
    """
    project_root = output.parent / "qt-capture-state"
    window = MinimalistAtlasWindow(UserConfig(project_root=str(project_root)), auto_refresh=False)
    window.page_transition.reduced_motion = True
    window.resize(1760, 1080)
    window._data_loaded(_dropdown_bundle(project_root))
    window.show()
    app.processEvents()

    def grab(name: str) -> None:
        QTest.qWait(280)
        app.processEvents()
        image = window.grab().toImage()
        target = output / f"{name}.png"
        if image.isNull() or not image.save(str(target)):
            raise RuntimeError(f"could not capture {name}")
        names.append(name)

    if not window.show_page("library"):
        raise RuntimeError("could not open Library for visual capture")
    library = window.library_page.library_content
    browse = library.current_view
    grab("library-default")

    browse.search_bar.set_query_text("P4-EOAT-0052")
    QTest.qWait(360)
    app.processEvents()
    grab("library-query")

    browse.search_bar.set_query_text("")
    browse.filter_bar.type_dropdown.combo.setCurrentText("Machines")
    browse.filter_bar.status_dropdown.combo.setCurrentText("Active")
    QTest.qWait(120)
    app.processEvents()
    grab("library-filters")

    library.select_entity("eoat", "P4-EOAT-0052")
    grab("eoat-profile")
    library.select_entity("machine", "52")
    grab("machine-profile")
    library.select_entity("tool", "6201510010")
    grab("tool-profile")

    if not window.show_page("fit_check"):
        raise RuntimeError("could not open Fit Check for visual capture")
    fit = window.fit_check_page.fit_content
    grab("fit-empty")
    fit.input_card.apply_request(FitCheckRequest(tool_id="6201510010"))
    fit._sync_selector_options()
    fit._refresh_result(animate=False)
    grab("fit-populated")
    fit.input_card.apply_request(
        FitCheckRequest(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052", eoat_mode="manual")
    )
    fit._sync_selector_options()
    fit._refresh_result(animate=False)
    grab("fit-compatible")
    fit.input_card.apply_request(
        FitCheckRequest(tool_id="6201510010", machine_id="99", eoat_id="P4-EOAT-0052", eoat_mode="manual")
    )
    fit._sync_selector_options()
    fit._refresh_result(animate=False)
    grab("fit-warning")

    if not window.show_page("settings"):
        raise RuntimeError("could not open Settings for visual capture")
    grab("settings-dark")
    if window.settings_page is None:
        raise RuntimeError("could not initialize Settings for visual capture")
    window.settings_page.shell.set_theme_preference("light")
    grab("settings-light")
    window.settings_page.shell.set_theme_preference("dark")

    window.show_page("library")
    library._show_browse()
    browse = library.current_view
    browse.loading_message = "Loading deterministic Library fixture"
    browse.refresh()
    grab("loading")
    browse.loading_message = ""
    browse.search_bar.set_query_text("missing-fixture")
    QTest.qWait(360)
    app.processEvents()
    grab("empty")
    grab("not-found")

    window.show_page("minimalist_home")
    window.data_freshness.record_failure("deterministic API outage")
    window._freshness_poll_failed("deterministic API outage")
    grab("api-unavailable")
    window.data_freshness.state = PollingState.OFFLINE_CACHED
    window._refresh_freshness_indicators()
    grab("stale-data")
    window.page_transition.reduced_motion = True
    grab("reduced-motion")
    window.close()
    window.deleteLater()
    app.processEvents()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(tempfile.gettempdir()) / "eoat-project-mirrorline" / "qt",
    )
    args = parser.parse_args(argv)
    names = capture(args.output.resolve())
    print({"application_version": get_app_version(), "output": str(args.output.resolve()), "captures": names})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
