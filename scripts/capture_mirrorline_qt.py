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
    return names


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
