from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget

from app.atlas.minimalist.window import MinimalistAtlasWindow
from app.atlas.page_transition import PageTransitionController
from core.config import UserConfig
from core.fit_check_service import FitCheckRequest
from core.packet_builder_packets import PacketSetup
from tests.test_minimalist_dropdown_lifecycle import _dropdown_bundle


def test_page_transition_switches_immediately_and_restores_geometry(qapp) -> None:
    stack = QStackedWidget()
    first = QWidget()
    second = QWidget()
    stack.addWidget(first)
    stack.addWidget(second)
    stack.resize(420, 280)
    stack.show()
    qapp.processEvents()
    transition = PageTransitionController(stack, incoming_duration_ms=120, outgoing_duration_ms=80)

    assert transition.switch_to_widget(second)

    assert stack.currentWidget() is second
    assert transition.is_animating

    _wait_for_transition(qapp, transition)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()

    assert stack.currentWidget() is second
    assert second.pos() == QPoint(0, 0)
    assert second.graphicsEffect() is None
    assert not stack.findChildren(QLabel, "AtlasPageTransitionSnapshot")
    stack.close()


def test_minimalist_transition_preserves_fit_check_state_and_return_path(qapp, tmp_path: Path) -> None:
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.page_transition.incoming_duration_ms = 120
    window.page_transition.outgoing_duration_ms = 80
    window.resize(1400, 900)
    window._data_loaded(_dropdown_bundle(tmp_path))
    window.show()
    window.show_page("fit_check")
    _wait_for_transition(qapp, window.page_transition)

    content = window.fit_check_page.fit_content
    content.input_card.apply_request(
        FitCheckRequest(tool_id="6201510010", machine_id="Machine 52", eoat_id="P4-EOAT-0052")
    )
    content._sync_selector_options()
    content._run_requested()
    qapp.processEvents()

    expected_setup = PacketSetup(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052")
    assert window.current_fit_check_setup() == expected_setup

    window.open_eoat("P4-EOAT-0052", source="fit_check")
    _wait_for_transition(qapp, window.page_transition)

    assert window.current_page_key == "library"
    assert window.library_page.library_content.selected_entity is not None
    assert window.library_page.library_content.selected_entity.key == "P4-EOAT-0052"

    window.library_page.library_content.go_back_to_library()
    _wait_for_transition(qapp, window.page_transition)

    assert window.current_page_key == "fit_check"
    assert window.current_fit_check_setup() == expected_setup
    assert content.input_card.selected_key("tool") == "6201510010"
    assert content.input_card.selected_key("machine") == "52"
    assert content.input_card.selected_key("eoat") == "P4-EOAT-0052"
    _cleanup_widget(qapp, window)


def _wait_for_transition(qapp, transition: PageTransitionController, *, timeout_ms: int = 1000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if not transition.is_animating:
            return
        QTest.qWait(20)
    qapp.processEvents()
    assert not transition.is_animating


def _cleanup_widget(qapp, widget) -> None:
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
