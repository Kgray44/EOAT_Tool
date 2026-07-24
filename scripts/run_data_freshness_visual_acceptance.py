"""Render the data-freshness visual acceptance matrix in an isolated Qt session.

This is deliberately a test-only native UI harness.  It drives the real
``MinimalistAtlasWindow`` and its ``DataFreshnessService`` with deterministic
status transitions, rather than sleeping for wall-clock polling intervals or
editing a production data source.  Output belongs in a temporary directory and
is never a repository artifact.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(
    os.environ.get("EOAT_NATIVE_FRESHNESS_EVIDENCE_DIR")
    or Path(tempfile.gettempdir()) / "eoat-data-freshness-native-evidence"
).resolve()
EVIDENCE.mkdir(parents=True, exist_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"].casefold() == "offscreen":
    font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    if not font_directory.is_dir():
        raise RuntimeError(f"Offscreen evidence requires the system font directory: {font_directory}")
    os.environ.setdefault("QT_QPA_FONTDIR", str(font_directory))
    os.environ.setdefault("QT_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_FONT_DPI", "96")
os.environ.setdefault("EOAT_ATLAS_DATA_BACKEND", "mysql_api")
os.environ.setdefault("EOAT_ATLAS_USER_DATA_DIR", str(EVIDENCE / "user-data"))

# These imports must follow the offscreen environment initialization above.
from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QPoint  # noqa: E402
from PySide6.QtGui import QFont, QFontInfo, QFontMetrics, QGuiApplication, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QToolTip  # noqa: E402

from app.atlas.minimalist.window import MinimalistAtlasWindow  # noqa: E402
from core.config import UserConfig  # noqa: E402
from core.data_freshness import FreshnessSettings, PollingState  # noqa: E402
from core.fit_check_service import FitCheckRequest  # noqa: E402
from tests.test_minimalist_dropdown_lifecycle import _dropdown_bundle  # noqa: E402


def _status(revision: int, modified_at: datetime) -> dict[str, object]:
    return {
        "status": "available",
        "data_revision": revision,
        "data_last_modified_at": modified_at.isoformat(),
        "last_import_at": "",
        "last_import_source": "visual-acceptance",
        "server_time": modified_at.isoformat(),
        "source": "mysql",
        "environment": "test",
    }


def _set_current(window: MinimalistAtlasWindow, *, revision: int = 1, age_seconds: int = 0) -> None:
    service = window.data_freshness
    service.configure(FreshnessSettings(automatic_polling_enabled=True, refresh_when_data_changes="notify"))
    now = datetime.now(timezone.utc)
    service.current_revision = revision
    service.data_last_modified_at = now - timedelta(seconds=age_seconds)
    service.last_checked_at = now
    service.server_time = now
    service.state = PollingState.CURRENT
    for page in service.pages.values():
        page.displayed_revision = revision
        page.stale = False
        page.refresh_pending = False
        page.refresh_deferred_reason = ""
    service.refresh_deferred_reason = ""
    window._refresh_freshness_indicators()


def _advance(window: MinimalistAtlasWindow, revision: int, *, automatic: bool = False) -> None:
    service = window.data_freshness
    service.configure(
        FreshnessSettings(
            automatic_polling_enabled=True,
            refresh_when_data_changes="automatic" if automatic else "notify",
            pause_refresh_while_editing=True,
        )
    )
    now = datetime.now(timezone.utc)
    assert service.begin_check(manual=True)
    transition = service.receive_status(_status(revision, now), received_at=now)
    assert transition.kind == "advanced", transition
    window._freshness_transitioned(service, transition)


def _unlock(settings_content) -> None:
    settings_content._start_admin_session(
        {
            "provider": "development",
            "identity": {"username": "dev.admin", "display_name": "Development Administrator"},
        }
    )
    settings_content.authentication_gateway.authorize = lambda *_args, **_kwargs: {"authorized": True}  # type: ignore[method-assign]
    settings_content.authentication_gateway.audit_settings_action = lambda *_args, **_kwargs: {"recorded": True}  # type: ignore[method-assign]


class VisualAcceptance:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.events: list[dict[str, object]] = []
        self.screenshots: list[dict[str, object]] = []
        self.failures: list[dict[str, str]] = []
        self.window: MinimalistAtlasWindow | None = None
        self.base_bundle = _dropdown_bundle(EVIDENCE)

    def new_window(self) -> MinimalistAtlasWindow:
        self.close_window()
        window = MinimalistAtlasWindow(UserConfig(project_root=str(EVIDENCE)), auto_refresh=False)
        window.page_transition.reduced_motion = True
        window.resize(1440, 900)
        window._data_loaded(replace(self.base_bundle, metrics={**self.base_bundle.metrics, "data_revision": 1}))
        window.show()
        self.app.processEvents()
        _set_current(window, revision=1, age_seconds=8 * 60)
        self.window = window
        return window

    def close_window(self) -> None:
        if self.window is None:
            return
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.window = None

    def record(self, name: str, action: Callable[[MinimalistAtlasWindow], tuple[str, ...]], *, page: str = "home") -> None:
        window = self.new_window()
        try:
            expected = action(window)
            self.capture(window, name, expected, page=page)
        except Exception as exc:
            self.failures.append({"scenario": name, "error": f"{type(exc).__name__}: {exc}"})
            self.events.append({"scenario": name, "state": "failed", "traceback": traceback.format_exc(limit=6)})
        finally:
            self.close_window()

    def _wait_for_render(self, window: MinimalistAtlasWindow, expected: tuple[str, ...], *, page: str) -> dict[str, object]:
        expected_page = "minimalist_home" if page == "home" else "settings" if page == "diagnostics" else page
        if page not in {"home", "minimalist_home"}:
            assert window.show_page(page), f"could not activate {page}"
        deadline = 0
        for deadline in range(30):
            self.app.processEvents()
            target = window.stack.currentWidget()
            content = next(
                (
                    getattr(target, attr)
                    for attr in ("home_content", "fit_content", "library_content", "settings_content", "simple_content")
                    if getattr(target, attr, None) is not None
                ),
                None,
            )
            visible_text = "\n".join(
                label.text() for label in window.findChildren(QLabel) if label.isVisible() and label.text().strip()
            )
            if (
                target is not None
                and target.isVisible()
                and target.width() > 300
                and target.height() > 300
                and content is not None
                and content.isVisible()
                and content.geometry().width() > 100
                and content.geometry().height() > 100
                and all(value.casefold() in visible_text.casefold() for value in expected)
            ):
                target.layout().activate() if target.layout() is not None else None
                content.update()
                content.repaint()
                self.app.processEvents()
                return {
                    "route": window.current_page_key,
                    "selected_page": target.objectName() or type(target).__name__,
                    "content_class": type(content).__name__,
                    "content_geometry": [content.x(), content.y(), content.width(), content.height()],
                    "visible_text": visible_text,
                    "event_cycles": deadline + 1,
                }
            QTest.qWait(10)
        raise AssertionError(f"render predicate not met for {page}; expected visible text: {expected}")

    @staticmethod
    def _image_profile(image: QImage) -> dict[str, int]:
        frame = image.convertToFormat(QImage.Format.Format_RGBA8888)
        colors: set[tuple[int, int, int]] = set()
        non_dark = 0
        high_contrast = 0
        samples = 0
        for y in range(0, frame.height(), 12):
            for x in range(0, frame.width(), 12):
                color = frame.pixelColor(x, y)
                colors.add((color.red(), color.green(), color.blue()))
                non_dark += int(max(color.red(), color.green(), color.blue()) > 35)
                high_contrast += int(
                    max(color.red(), color.green(), color.blue()) > 150
                    and min(color.red(), color.green(), color.blue()) > 80
                )
                samples += 1
        return {
            "sampled_colors": len(colors),
            "non_dark_samples": non_dark,
            "high_contrast_samples": high_contrast,
            "samples": samples,
        }

    def _wait_for_painted_window(self, window: MinimalistAtlasWindow) -> tuple[QImage, dict[str, int]]:
        """Wait for a real full-window paint, not only a visible QWidget tree."""
        for _ in range(30):
            target = window.stack.currentWidget()
            shell = getattr(target, "shell", None)
            if window.layout() is not None:
                window.layout().activate()
            if target is not None and target.layout() is not None:
                target.layout().activate()
            for widget in (window, window.stack, target, shell, getattr(shell, "top_bar", None)):
                if widget is not None and widget.isVisible():
                    widget.update()
                    widget.repaint()
            self.app.processEvents()
            image = window.grab().toImage()
            if not image.isNull():
                profile = self._image_profile(image)
                # A real rendered page always has title/controls/text above
                # the footer.  A surface containing only the dark shell or a
                # lingering toast fails this stronger visual predicate.
                if profile["high_contrast_samples"] >= 10 and self._has_shell_header(image):
                    return image, profile
            QTest.qWait(20)
        raise AssertionError("full window did not complete a readable paint within the bounded event drain")

    @staticmethod
    def _has_shell_header(image: QImage) -> bool:
        """The EOAT Atlas wordmark proves this is the full window, not a child surface."""
        frame = image.convertToFormat(QImage.Format.Format_RGBA8888)
        left = max(0, frame.width() // 2 - 180)
        right = min(frame.width(), frame.width() // 2 + 180)
        bottom = min(frame.height(), 100)
        bright = 0
        for y in range(18, bottom, 3):
            for x in range(left, right, 3):
                color = frame.pixelColor(x, y)
                if max(color.red(), color.green(), color.blue()) > 150 and min(color.red(), color.green(), color.blue()) > 70:
                    bright += 1
        return bright >= 8

    def capture(self, window: MinimalistAtlasWindow, name: str, expected: tuple[str, ...], *, page: str) -> None:
        render = self._wait_for_render(window, expected, page=page)
        image, profile = self._wait_for_painted_window(window)
        if "tooltip" in name:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                screen_image = screen.grabWindow(0).toImage()
                if not screen_image.isNull():
                    image = screen_image
                    profile = self._image_profile(image)
        assert not image.isNull(), f"{name}: window grab is null"
        assert profile["sampled_colors"] >= 40, f"{name}: image lacks visual detail: {profile}"
        assert profile["non_dark_samples"] >= 40, f"{name}: image body is unexpectedly blank: {profile}"
        path = EVIDENCE / f"{name}.png"
        assert image.save(str(path)), f"could not save {path}"
        service = window.data_freshness
        page_state = service.pages.get(window.current_page_key)
        self.screenshots.append(
            {
                "name": name,
                "path": str(path),
                "dimensions": [image.width(), image.height()],
                "status": service.primary_text(),
                "server_revision": service.current_revision,
                "page_revision": page_state.displayed_revision if page_state is not None else None,
                "connection": str(service.state),
                "polling_interval_seconds": service.settings.polling_interval_seconds,
                "render": render,
                "image_profile": profile,
            }
        )


def _font_environment(app: QApplication) -> dict[str, object]:
    font = app.font()
    info = QFontInfo(font)
    metrics = QFontMetrics(font)
    glyphs = {
        "U+002E FULL STOP": ".",
        "U+007C VERTICAL LINE": "|",
        "U+00B7 MIDDLE DOT": "·",
        "U+2026 HORIZONTAL ELLIPSIS": "…",
        "U+2192 RIGHTWARDS ARROW": "→",
        "U+2713 CHECK MARK": "✓",
        "U+26A0 WARNING SIGN": "⚠",
        "U+1F552 CLOCK FACE THREE OCLOCK": "🕒",
    }
    missing = [name for name, glyph in glyphs.items() if not metrics.inFontUcs4(ord(glyph))]
    if missing:
        raise RuntimeError(f"Selected offscreen font lacks required glyphs: {', '.join(missing)}")
    screen = QGuiApplication.primaryScreen()
    return {
        "platform_plugin": QGuiApplication.platformName(),
        "requested_family": font.family(),
        "resolved_family": info.family(),
        "exact_match": info.exactMatch(),
        "point_size": font.pointSizeF(),
        "scale_factor": os.environ.get("QT_SCALE_FACTOR"),
        "font_dpi": os.environ.get("QT_FONT_DPI"),
        "logical_dpi": screen.logicalDotsPerInch() if screen is not None else None,
        "device_pixel_ratio": screen.devicePixelRatio() if screen is not None else None,
        "locale": QLocale().name(),
        "font_directory": os.environ.get("QT_QPA_FONTDIR"),
        "glyphs": {name: f"U+{ord(glyph):04X}" for name, glyph in glyphs.items()},
    }


def main() -> int:
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Segoe UI", 9))
    app.processEvents()
    acceptance = VisualAcceptance(app)
    summary: dict[str, object] = {
        "app_version": "0.18.0",
        "rendering": os.environ["QT_QPA_PLATFORM"],
        "evidence_directory": str(EVIDENCE),
        "font_environment": _font_environment(app),
        "scenarios": [],
    }

    def checking(window):
        assert window.data_freshness.begin_check(manual=True)
        window._refresh_freshness_indicators()
        return ("Checking for updates",)

    def current_recent(window):
        _set_current(window, age_seconds=5)
        return ("Data last updated just now",)

    def current_old(window):
        _set_current(window, age_seconds=7 * 60)
        return ("Data last updated 7 minutes ago",)

    def update_available(window):
        _advance(window, 2)
        return ("New data available",)

    def refreshing(window):
        window.data_freshness.mark_refreshing()
        window._refresh_freshness_indicators()
        return ("Refreshing data",)

    def offline_cached(window):
        _set_current(window, age_seconds=8 * 60)
        window.data_freshness.record_failure("simulated disposable API outage")
        window._freshness_poll_failed("simulated disposable API outage")
        return ("Offline", "Showing cached data", "Last verified")

    def poll_failure(window):
        window.data_freshness.current_revision = None
        window.data_freshness.data_last_modified_at = None
        window.data_freshness.record_failure("simulated first-contact failure")
        window._freshness_poll_failed("simulated first-contact failure")
        return ("Could not check for updates",)

    def manual(window):
        window.data_freshness.configure(FreshnessSettings(automatic_polling_enabled=False))
        window._refresh_freshness_indicators()
        return ("Manual updates enabled",)

    def paused_edit(window):
        assert window.show_page("settings")
        content = window.settings_page.settings_content
        _unlock(content)
        content.select_section("refresh_cache")
        content._set_setting("data_loading.polling_interval_seconds", 30)
        _advance(window, 2, automatic=True)
        assert window.data_freshness.state == PollingState.PAUSED_FOR_EDIT
        return ("Data Freshness", "Refresh is deferred")

    def unknown(window):
        window.data_freshness.current_revision = None
        window.data_freshness.data_last_modified_at = None
        window.data_freshness.last_checked_at = None
        window.data_freshness.state = PollingState.WAITING
        window._refresh_freshness_indicators()
        return ("Data freshness unknown",)

    def offline_verified(window):
        _set_current(window, age_seconds=8 * 60)
        window.data_freshness.record_failure("simulated outage after verification")
        window._freshness_poll_failed("simulated outage after verification")
        return ("Offline", "Last verified just now")

    def status_tooltip(window):
        _set_current(window, age_seconds=8 * 60)
        status = window.home_page.home_content.status.label
        QToolTip.showText(status.mapToGlobal(QPoint(status.width() // 2, 0)), status.toolTip(), status)
        QTest.qWait(50)
        return ("Data last updated",)

    def polling_settings(window):
        assert window.show_page("settings")
        content = window.settings_page.settings_content
        content.select_section("refresh_cache")
        return ("Automatic polling", "Polling interval", "Pause refresh while editing")

    def diagnostics(window):
        _set_current(window, age_seconds=8 * 60)
        assert window.show_page("diagnostics")
        content = window.settings_page.settings_content
        content.select_section("diagnostics_support")
        content._sync_main_scroll_extent()
        app.processEvents()
        for label in content.main_body.findChildren(QLabel):
            if label.text().strip() == "Data Freshness":
                target_y = label.mapTo(content.main_body, QPoint(0, 0)).y()
                content.main_scroll.verticalScrollBar().setValue(max(0, target_y - 64))
                break
        app.processEvents()
        return ("Data Freshness", "Polling enabled", "Configured interval", "Server data revision")

    def fit_stale(window):
        assert window.show_page("fit_check")
        content = window.fit_check_page.fit_content
        content.input_card.apply_request(
            FitCheckRequest(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052", eoat_mode="manual")
        )
        content._sync_selector_options()
        content._refresh_result(animate=False)
        _advance(window, 2)
        return ("Result needs refresh", "Server data changed", "stale")

    def fit_refreshed(window):
        assert window.show_page("fit_check")
        content = window.fit_check_page.fit_content
        content.input_card.apply_request(
            FitCheckRequest(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052", eoat_mode="manual")
        )
        content._sync_selector_options()
        content._refresh_result(animate=False)
        _advance(window, 2)
        refreshed = replace(window.bundle, metrics={**window.bundle.metrics, "data_revision": 2})
        window._data_loaded(refreshed)
        return ("Compatible",)

    scenarios: tuple[tuple[str, Callable[[MinimalistAtlasWindow], tuple[str, ...]], str], ...] = (
        ("01_checking_data_status", checking, "home"),
        ("02_data_current_just_now", current_recent, "home"),
        ("03_data_current_older_relative", current_old, "home"),
        ("04_new_data_available", update_available, "home"),
        ("05_refreshing_data", refreshing, "home"),
        ("06_offline_cached_data", offline_cached, "home"),
        ("07_poll_check_failure", poll_failure, "home"),
        ("08_manual_updates_enabled", manual, "home"),
        ("09_update_paused_while_editing", paused_edit, "settings"),
        ("10_data_freshness_unknown", unknown, "home"),
        ("11_offline_last_verified", offline_verified, "home"),
        ("12_status_details_tooltip", status_tooltip, "home"),
        ("13_polling_settings_controls", polling_settings, "settings"),
        ("14_diagnostics_freshness", diagnostics, "diagnostics"),
        ("15_fit_check_stale_warning", fit_stale, "fit_check"),
        ("16_fit_check_refreshed_result", fit_refreshed, "fit_check"),
    )
    for name, scenario, page in scenarios:
        acceptance.record(name, scenario, page=page)

    summary["scenarios"] = acceptance.screenshots
    summary["failures"] = acceptance.failures
    summary["event_trace"] = acceptance.events
    (EVIDENCE / "visual-acceptance-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 1 if acceptance.failures else 0


if __name__ == "__main__":
    sys.exit(main())
