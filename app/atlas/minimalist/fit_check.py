from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord
from core.atlas_record_details import RecordDetailData
from core.atlas_setup_packets import (
    PACKET_TYPE_SETUP_VERIFICATION,
    PHOTO_KEY,
    PHOTO_NONE,
    SetupPacketOptions,
    atlas_setup_packet_dir,
    build_setup_packet_context,
)
from core.atlas_utils import display_value, normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.fit_check_service import (
    FitCheckAlternativeEOAT,
    FitCheckAlternativeMachine,
    FitCheckRequest,
    FitCheckResult,
    FitCheckService,
)
from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
from core.packet_builder_packets import PacketSetup, is_valid_fit_result
from core.reporting.pdf_preview_session import PdfPreviewSession, setup_packet_preview_dir
from core.setup_packet_pdf import export_setup_packet_pdf, setup_packet_filename

from .data import loaded_status_text, machine_label
from .library import PDFPreviewOverlay
from .theme import effective_minimalist_theme, minimalist_tokens, qss_rgba
from .widgets import (
    ACCENT_BRIGHT,
    STATUS_ERROR,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    STATUS_WARNING,
    TEXT_PLACEHOLDER,
    AnimatedGlassPanel,
    CloseIconButton,
    GlassPanel,
    MinimalistToast,
    SearchMiniIcon,
    StatusDot,
    TitleAccentBar,
    clear_layout,
    glyph_icon,
    prefers_reduced_motion,
    set_placeholder_color,
)

FIT_CHECK_STYLES = """
QWidget#AtlasMinimalistFitCheckPage,
QWidget#MinimalistFitCheckContent,
QWidget#FitCheckBody,
QWidget#FitCheckResultArea,
QWidget#FitCheckBottomCards,
QWidget#FitCheckRowHost,
QWidget#FitCheckSelectorHost,
QWidget#FitCheckInputButtons,
QWidget#FitCheckSetupPath,
QWidget#FitCheckOverlayBody {
    background: transparent;
}
QScrollArea#FitCheckScroll {
    background: transparent;
    border: 0;
}
QScrollArea#FitCheckScroll QWidget {
    background: transparent;
}
QLabel#FitCheckTitle {
    color: #f8fbff;
    font-size: 31pt;
    font-weight: 820;
}
QLabel#FitCheckSubtitle {
    color: #d7e2f0;
    font-size: 10.5pt;
    font-weight: 500;
}
QFrame#FitCheckTitleAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 89, 200, 0), stop:.52 #047aff, stop:1 rgba(0, 89, 200, 0));
    border: 0;
    min-height: 3px;
    max-height: 3px;
}
QLabel#FitCheckSectionTitle {
    color: #ffffff;
    font-size: 12pt;
    font-weight: 760;
}
QLabel#FitCheckSelectorLabel {
    color: #f0f6ff;
    font-size: 9.2pt;
    font-weight: 650;
}
QLineEdit#FitCheckSelectorInput {
    background: transparent;
    border: 0;
    color: #ffffff;
    font-size: 10.4pt;
    font-weight: 560;
    selection-background-color: #1f87ff;
}
QLabel#FitCheckSelectorSecondary,
QLabel#FitCheckInputHint,
QLabel#FitCheckMuted,
QLabel#FitCheckHelper,
QLabel#FitCheckWarningMessage {
    color: #c6d3e3;
    font-size: 9.2pt;
    font-weight: 470;
}
QLabel#FitCheckHelper {
    color: #cfe3fb;
    background: rgba(7, 25, 52, 98);
    border: 1px solid rgba(57, 150, 255, 74);
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}
QLabel#FitCheckDropdownGroup {
    color: #62c7ff;
    font-size: 7.6pt;
    font-weight: 780;
    letter-spacing: 0;
    padding: 3px 6px 0 6px;
}
QLabel#FitCheckInputHint {
    color: #d9e8ff;
    font-size: 9.2pt;
    font-weight: 650;
}
QLabel#FitCheckResultHeadline {
    font-size: 16.5pt;
    font-weight: 820;
}
QLabel#FitCheckResultMessage,
QLabel#FitCheckPathSub,
QLabel#FitCheckRecommendedType {
    color: #d7e2f0;
    font-size: 9.5pt;
    font-weight: 520;
}
QLabel#FitCheckRecommendedLabel,
QLabel#FitCheckPathLabel {
    color: #f2f7ff;
    font-size: 8.7pt;
    font-weight: 650;
}
QLabel#FitCheckRecommendedId,
QLabel#FitCheckPathTitle {
    color: #ffffff;
    font-size: 13pt;
    font-weight: 820;
}
QLabel#FitCheckConfidence {
    color: #d6e1ef;
    font-size: 9.3pt;
    font-weight: 560;
}
QLabel#FitCheckConfidenceValue {
    color: #36d86a;
    font-size: 9.3pt;
    font-weight: 720;
}
QLabel#FitCheckRequirementName,
QLabel#FitCheckWarningTitle,
QLabel#FitCheckAltTitle {
    color: #f2f7ff;
    font-size: 9.3pt;
    font-weight: 620;
}
QLabel#FitCheckRequirementValue {
    font-size: 9pt;
    font-weight: 640;
}
QLabel#FitCheckAltSub {
    color: #c3d0e1;
    font-size: 8.5pt;
    font-weight: 500;
}
QLabel#FitCheckPill {
    border-radius: 9px;
    padding: 4px 10px;
    font-size: 8pt;
    font-weight: 760;
}
QLabel#FitCheckPill[tone="best"],
QLabel#FitCheckPill[tone="current"] {
    color: #d9fff0;
    background: rgba(12, 101, 79, 126);
}
QLabel#FitCheckPill[tone="verify"] {
    color: #ffe7b7;
    background: rgba(126, 79, 24, 118);
}
QLabel#FitCheckPill[tone="incompatible"] {
    color: #ffd4d9;
    background: rgba(116, 24, 44, 126);
}
QLabel#FitCheckPill[tone="available"] {
    color: #d9fff0;
    background: rgba(12, 101, 79, 96);
}
QLabel#FitCheckPill[tone="missing_data"],
QLabel#FitCheckPill[tone="not_recommended"] {
    color: #c3cfdd;
    background: rgba(61, 75, 100, 118);
}
QPushButton#FitCheckPrimaryButton {
    background-color: #1677ff;
    color: #ffffff;
    border: 1px solid rgba(103, 190, 255, 180);
    border-radius: 7px;
    min-height: 44px;
    padding: 0 18px;
    font-size: 9.2pt;
    font-weight: 760;
}
QPushButton#FitCheckPrimaryButton:hover {
    background-color: #248fff;
    border-color: rgba(145, 220, 255, 220);
}
QPushButton#FitCheckSecondaryButton,
QPushButton#FitCheckGhostButton,
QPushButton#FitCheckTabButton,
QPushButton#FitCheckClearButton {
    background: rgba(6, 18, 38, 128);
    color: #ffffff;
    border: 1px solid rgba(73, 111, 157, 134);
    border-radius: 7px;
    min-height: 40px;
    padding: 0 14px;
    font-size: 9pt;
    font-weight: 700;
}
QPushButton#FitCheckSecondaryButton:hover,
QPushButton#FitCheckGhostButton:hover,
QPushButton#FitCheckClearButton:hover {
    background: rgba(12, 42, 88, 174);
    border-color: rgba(31, 135, 255, 196);
}
QPushButton#FitCheckClearButton {
    min-height: 32px;
    padding: 0 13px;
    font-size: 8.5pt;
    font-weight: 720;
}
QPushButton#FitCheckClearButton:disabled {
    color: rgba(190, 205, 226, 96);
    border-color: rgba(73, 111, 157, 60);
    background: rgba(6, 18, 38, 70);
}
QPushButton#FitCheckTabButton {
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: #d7e2f1;
    background: transparent;
}
QPushButton#FitCheckTabButton[active="true"] {
    color: #1496ff;
    border-bottom-color: #1496ff;
}
QPushButton#FitCheckAltRow {
    background: rgba(5, 17, 36, 116);
    border: 1px solid rgba(73, 111, 157, 96);
    border-radius: 7px;
    text-align: left;
}
QPushButton#FitCheckAltRow:hover {
    background: rgba(9, 35, 76, 170);
    border-color: rgba(31, 135, 255, 178);
}
QLabel#FitCheckOverlayTitle {
    color: #ffffff;
    font-size: 18pt;
    font-weight: 820;
}
QLabel#FitCheckOverlaySubtitle {
    color: #c7d6e8;
    font-size: 9.2pt;
    font-weight: 520;
}
QLabel#FitCheckOverlaySection {
    color: #83d8ff;
    font-size: 11.2pt;
    font-weight: 780;
}
QLabel#FitCheckOverlayText {
    color: #dce8f8;
    font-size: 10pt;
    font-weight: 520;
    line-height: 140%;
}
"""


def fit_check_styles(preference: str | None = None) -> str:
    t = minimalist_tokens(preference)
    light = effective_minimalist_theme(preference) == "light"
    return (
        FIT_CHECK_STYLES
        + f"""
QLabel#FitCheckTitle {{
    color: {t.text_primary};
}}
QLabel#FitCheckSubtitle {{
    color: {t.text_secondary};
}}
QLabel#FitCheckHelper {{
    color: {t.text_secondary};
    background: {qss_rgba(t.card_background, 238 if light else 98)};
    border-color: {qss_rgba(t.accent, 94 if light else 74)};
}}
QLabel#FitCheckSectionTitle,
QLabel#FitCheckSelectorLabel {{
    color: {t.text_primary};
}}
QLabel#FitCheckSelectorSecondary,
QLabel#FitCheckInputHint,
QLabel#FitCheckMuted,
QLabel#FitCheckWarningMessage {{
    color: {t.text_secondary};
}}
"""
    )

FIT_CHECK_PRIMARY_ACTION_STYLE = """
QPushButton {
    background-color: #1677ff;
    color: #ffffff;
    border: 1px solid rgba(103, 190, 255, 180);
    border-radius: 7px;
    padding: 0 16px;
    font-size: 9pt;
    font-weight: 760;
}
QPushButton:hover {
    background-color: #248fff;
    border-color: rgba(145, 220, 255, 220);
}
QPushButton:disabled {
    color: rgba(190, 205, 226, 92);
    border-color: rgba(73, 111, 157, 58);
    background-color: rgba(6, 18, 38, 70);
}
"""


_RECORD_KINDS = ("tool", "machine", "eoat")
RECENT_SAVE_DELAY_MS = 21_000


def _fit_setting(controller, dotted_path: str, default: Any = None) -> Any:
    settings = getattr(controller, "minimalist_app_settings", None)
    if not isinstance(settings, dict):
        return default
    node: Any = settings
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return default if node is None else node


def _fit_bool(controller, dotted_path: str, default: bool = True) -> bool:
    return bool(_fit_setting(controller, dotted_path, default))


def _fit_int(controller, dotted_path: str, default: int) -> int:
    try:
        return int(_fit_setting(controller, dotted_path, default))
    except (TypeError, ValueError):
        return int(default)


def _safe_filename_component(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    return text.strip("-_.") or "Unknown"


@dataclass(frozen=True)
class SelectorOption:
    key: str
    display: str
    secondary: str = ""
    mode: str = "manual"
    keywords: str = ""
    kind: str = ""
    raw_record: object | None = None


@dataclass(frozen=True)
class RecentFitCheck:
    timestamp: datetime
    request: FitCheckRequest
    headline: str
    summary: str
    status: str
    confidence: str
    selected_items: tuple[dict[str, Any], ...] = ()
    ordered_signature: str = ""
    match_level: str = ""
    id: str = ""


class CompatibilityOptionFilter:
    def __init__(self, service: FitCheckService, options_for_kind):
        self.service = service
        self.options_for_kind = options_for_kind

    def suggestions(
        self,
        *,
        current: SelectorOption | None,
        query: str = "",
        context: list[SelectorOption] | tuple[SelectorOption, ...] = (),
        allowed_kinds: set[str] | None = None,
    ) -> list[SelectorOption]:
        allowed = set(allowed_kinds or _RECORD_KINDS)
        normalized_context = [option for option in context if option is not None and option.kind in _RECORD_KINDS]
        if not normalized_context:
            return _dedupe_options(
                [
                    option
                    for kind in _RECORD_KINDS
                    if kind in allowed
                    for option in self.options_for_kind(kind)
                ]
            )
        exact_matches = self._exact_query_matches(query, allowed)
        candidates = [
            option
            for kind in _RECORD_KINDS
            if kind in allowed
            for option in self.options_for_kind(kind)
            if all(self.options_are_compatible(option, selected) for selected in normalized_context)
        ]
        for option in reversed(exact_matches):
            if all(not _same_record_option(option, candidate) for candidate in candidates):
                candidates.insert(0, option)
        if current is not None and all(not _same_option(current, option) for option in candidates):
            candidates.insert(0, current)
        return _dedupe_options(candidates)

    def _exact_query_matches(self, query: str, allowed: set[str]) -> list[SelectorOption]:
        text = str(query or "").strip().casefold()
        if not text:
            return []
        matches: list[SelectorOption] = []
        for kind in _RECORD_KINDS:
            if kind not in allowed:
                continue
            for option in self.options_for_kind(kind):
                if text in {option.key.casefold(), option.display.casefold()}:
                    matches.append(option)
        return _dedupe_options(matches)

    def options_are_compatible(self, candidate: SelectorOption, selected: SelectorOption) -> bool:
        if candidate.kind == selected.kind:
            return _same_option(candidate, selected)
        kinds = {candidate.kind, selected.kind}
        if kinds == {"tool", "machine"}:
            tool_id = candidate.key if candidate.kind == "tool" else selected.key
            machine_id = candidate.key if candidate.kind == "machine" else selected.key
            return self._tool_machine_compatible(tool_id, machine_id)
        if kinds == {"tool", "eoat"}:
            tool_id = candidate.key if candidate.kind == "tool" else selected.key
            eoat_id = candidate.key if candidate.kind == "eoat" else selected.key
            return self._tool_eoat_compatible(tool_id, eoat_id)
        if kinds == {"machine", "eoat"}:
            machine_id = candidate.key if candidate.kind == "machine" else selected.key
            eoat_id = candidate.key if candidate.kind == "eoat" else selected.key
            return self._machine_eoat_compatible(machine_id, eoat_id)
        return False

    def _tool_machine_compatible(self, tool_id: str, machine_id: str) -> bool:
        tool = self.service._tool(tool_id)
        machine = self.service._machine(machine_id)
        return _linked(
            normalized_machine_key(machine_id),
            getattr(tool, "compatible_machines", ()) if tool is not None else (),
            normalized_tool_key(tool_id),
            getattr(machine, "compatible_tools", ()) if machine is not None else (),
            right_normalizer=normalized_tool_key,
            left_normalizer=normalized_machine_key,
        )

    def _tool_eoat_compatible(self, tool_id: str, eoat_id: str) -> bool:
        tool = self.service._tool(tool_id)
        eoat = self.service._eoat(eoat_id)
        return _linked(
            normalized_eoat_key(eoat_id),
            getattr(tool, "compatible_eoats", ()) if tool is not None else (),
            normalized_tool_key(tool_id),
            getattr(eoat, "tools", ()) if eoat is not None else (),
            right_normalizer=normalized_tool_key,
            left_normalizer=normalized_eoat_key,
        )

    def _machine_eoat_compatible(self, machine_id: str, eoat_id: str) -> bool:
        machine = self.service._machine(machine_id)
        eoat = self.service._eoat(eoat_id)
        return _linked(
            normalized_eoat_key(eoat_id),
            getattr(machine, "compatible_eoats", ()) if machine is not None else (),
            normalized_machine_key(machine_id),
            getattr(eoat, "machines", ()) if eoat is not None else (),
            right_normalizer=normalized_machine_key,
            left_normalizer=normalized_eoat_key,
        )


class AtlasMinimalistFitCheckPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle: AtlasDataBundle | None = None
        self.setObjectName("AtlasMinimalistFitCheckPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.fit_content = MinimalistFitCheckContent(controller)
        from .shell import AtlasMinimalistShell

        self.shell = AtlasMinimalistShell(controller, self.fit_content)
        layout.addWidget(self.shell)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.fit_content.set_bundle(bundle)
        self.shell.set_bundle(bundle)

    def refresh(self) -> None:
        self.fit_content.set_bundle(self.bundle)

    def page_shown(self) -> None:
        self.shell.close_overlays(immediate=True)
        self.fit_content.close_search_overlays()
        self.shell.set_active_nav("fit_check")
        self.shell.top_bar.set_back_visible(False, animated=False)
        # The page already receives ``set_bundle`` when a snapshot is applied.
        # Reapplying the existing bundle just because the user returns here
        # would erase an explicit stale-result warning before newer data was
        # actually loaded.
        self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_search_overlay(self) -> None:
        self.fit_content.close_search_overlays()
        self.shell.open_search()

    def show_toast(self, message: str) -> None:
        self.fit_content.show_toast(message)

    def focus_search_text(self, text: str) -> None:
        self.fit_content.focus_search_text(text)


class MinimalistFitCheckContent(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle: AtlasDataBundle | None = None
        self.service = FitCheckService(None)
        self.current_result: FitCheckResult | None = None
        self.recent_checks: list[RecentFitCheck] = _load_recent_fit_checks()
        self._auto_filled_slots: set[int] = set()
        self._autofill_sources: dict[int, str] = {}
        self._blocked_autofill_sources: set[str] = set()
        self._autofilling = False
        self._result_version = 0
        self._pending_recent_signature = ""
        self._last_saved_recent_signature = self.recent_checks[0].ordered_signature if self.recent_checks else ""
        self._result_target_y = 0
        self.setObjectName("MinimalistFitCheckContent")
        self._theme_preference = None
        self.setStyleSheet(fit_check_styles(self._theme_preference))

        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("FitCheckScroll")
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(False)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("FitCheckBody")
        self.body_scroll.setWidget(self.body)

        self.title = QLabel("Fit Check", self.body)
        self.title.setObjectName("FitCheckTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = QLabel("Validate a Tool, Machine, and EOAT combination before setup.", self.body)
        self.subtitle.setObjectName("FitCheckSubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.accent = TitleAccentBar(self.body)
        self.accent.setObjectName("FitCheckTitleAccent")

        self.input_card = FitCheckInputCard(self.body)
        self.input_card.recent_requested.connect(lambda: self.open_details("recent"))
        self.input_card.clear_requested.connect(self._clear_requested)
        self.input_card.selection_changed.connect(self._selection_changed)
        self.input_card.query_changed.connect(self._selector_query_changed)
        self.input_card.focus_changed.connect(self._selector_focus_changed)

        self.helper = QLabel("Choose at least one item to start a fit check.", self.body)
        self.helper.setObjectName("FitCheckHelper")
        self.helper.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.result_area = QWidget(self.body)
        self.result_area.setObjectName("FitCheckResultArea")
        self.result_effect = QGraphicsOpacityEffect(self.result_area)
        self.result_effect.setOpacity(0.0)
        self.result_area.setGraphicsEffect(self.result_effect)
        self.result_area.hide()

        self.result_card = FitCheckResultCard(self.result_area)
        self.result_card.details_requested.connect(lambda: self.open_details("details"))
        self.result_card.open_eoat_requested.connect(lambda: self._open_record("eoat", self._result_eoat_id()))
        self.result_card.create_packet_requested.connect(self._create_setup_packet_from_current)

        self.path_row = FitCheckPathRow(self.result_area)
        self.path_row.record_requested.connect(self._open_record)

        self.requirements_card = RequirementsCheckCard(self.result_area)
        self.requirements_card.details_requested.connect(lambda: self.open_details("requirements"))

        self.warnings_card = WarningsCard(self.result_area)
        self.warnings_card.details_requested.connect(lambda: self.open_details("warnings"))

        self.alternatives_card = AlternativesCard(self.result_area)
        self.alternatives_card.details_requested.connect(lambda: self.open_details("alternatives"))
        self.alternatives_card.machine_selected.connect(self._select_machine)
        self.alternatives_card.eoat_selected.connect(self._select_eoat)

        self.more_details = QPushButton("More Details")
        self.more_details.setObjectName("FitCheckGhostButton")
        self.more_details.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_details.clicked.connect(lambda: self.open_details("details"))
        self.more_details.hide()

        self.status = FitCheckStatusLine(self)
        self.toast = MinimalistToast(self)
        self.toast.hide()

        self.scrim = FitCheckScrim(self)
        self.scrim.clicked.connect(self._scrim_clicked)
        self.scrim.hide()
        self.details_overlay = FitCheckDetailsOverlay(self)
        self.details_overlay.close_requested.connect(self.close_details)
        self.details_overlay.recent_selected.connect(self._load_recent_check)
        self.details_overlay.recent_packet_requested.connect(self._create_setup_packet_from_recent)
        self.details_overlay.hide()
        self.setup_packet_overlay = SetupPacketOverlay(self)
        self.setup_packet_overlay.close_requested.connect(self.close_setup_packet)
        self.setup_packet_overlay.preview_requested.connect(lambda: self._generate_setup_packet_pdf(preview=True))
        self.setup_packet_overlay.generate_requested.connect(lambda: self._generate_setup_packet_pdf(preview=False))
        self.setup_packet_overlay.hide()
        self._pdf_preview_overlay = None

        self.result_anim = QPropertyAnimation(self.result_effect, b"opacity", self)
        self.result_anim.setDuration(500)
        self.result_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.result_geo_anim = QPropertyAnimation(self.result_area, b"geometry", self)
        self.result_geo_anim.setDuration(500)
        self.result_geo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._recent_save_timer = QTimer(self)
        self._recent_save_timer.setSingleShot(True)
        self._recent_save_timer.setInterval(_fit_int(self.controller, "fit_check.save_recent_after_seconds", 20) * 1000)
        self._recent_save_timer.timeout.connect(self._recent_save_timer_elapsed)
        self._result_stale = False

    def apply_theme_preference(self, preference: str | None) -> None:
        self._theme_preference = preference
        self.setStyleSheet(fit_check_styles(preference))
        self.update()

    def set_bundle(self, bundle: AtlasDataBundle | None) -> None:
        self._cancel_recent_save_timer()
        old_selection = self._request()
        # A newly applied bundle is the only event that can make a stale
        # result current again.  Selection changes alone still operate on the
        # previous snapshot and must retain the visible stale warning.
        self._result_stale = False
        self.bundle = bundle
        self.service = FitCheckService(bundle)
        self._sync_selector_options()
        self.input_card.apply_request(old_selection)
        self.status.set_status(loaded_status_text(bundle), ready=bundle is not None)
        self._refresh_result(animate=False)

    def mark_server_data_stale(self) -> None:
        """Keep the selected inputs, but never leave a prior result looking current."""
        if self.current_result is None:
            return
        self._result_stale = True
        self.helper.setText("Server data changed. This Fit Check result needs refresh before engineering use.")
        self._present_stale_result_notice()
        self.show_toast("New compatibility-relevant data is available. Your selected inputs were preserved.")

    def _present_stale_result_notice(self) -> None:
        """Put the stale state on the result card, not beneath its overlay."""
        if self.current_result is None:
            return
        self.result_card.headline.setText("Result needs refresh")
        self.result_card.headline.setStyleSheet("color: #f5b642;")
        self.result_card.message.setText(
            "Server data changed. This Fit Check result is stale and must be refreshed before engineering use."
        )
        self.result_card.message.setStyleSheet("color: #ffd98a;")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = self.width()
        height = self.height()
        self.body_scroll.setGeometry(self.rect())
        body_height = max(height, 1180 if self.current_result else 620)
        self.body.resize(width, body_height)

        x, content_width = self._content_column(width)
        title_y = 116
        self.title.setGeometry((width - 420) // 2, title_y, 420, 48)
        self.accent.setGeometry((width - 78) // 2, title_y + 56, 78, 9)
        self.subtitle.setGeometry((width - 720) // 2, title_y + 68, 720, 24)
        self.input_card.setGeometry(x, title_y + 110, content_width, 210)
        result_y = title_y + 342
        self._result_target_y = result_y
        self.helper.setGeometry((width - 560) // 2, result_y + 38, 560, 40)
        self._layout_result_area(x, result_y, content_width)

        status_width = min(340, max(220, width - 80))
        self.status.setGeometry(width - status_width - 62, height - 48, status_width, 30)
        toast_width = min(720, max(260, width - 90))
        self.toast.setGeometry((width - toast_width) // 2, height - 116, toast_width, 72)
        self.scrim.setGeometry(self.rect())
        if self.details_overlay.isVisible():
            self.details_overlay.setGeometry(self._details_rect())
        if self.setup_packet_overlay.isVisible():
            self.setup_packet_overlay.setGeometry(self._setup_packet_rect())

    def _content_column(self, available_width: int) -> tuple[int, int]:
        content_width = min(1228, max(900, available_width - 170))
        if available_width < 980:
            content_width = max(320, available_width - 44)
        return (available_width - content_width) // 2, content_width

    def _layout_result_area(self, x: int, y: int, width: int) -> None:
        result_height = 742
        if self.result_geo_anim.state():
            self.result_geo_anim.stop()
        self.result_area.setGeometry(x, y, width, result_height)
        self.result_card.setGeometry(0, 0, width, 116)
        self.path_row.setGeometry(0, 128, width, 112)
        gap = 10
        card_y = 252
        card_h = 360
        if width >= 1040:
            card_w = (width - gap * 2) // 3
            self.requirements_card.setGeometry(0, card_y, card_w, card_h)
            self.warnings_card.setGeometry(card_w + gap, card_y, card_w, card_h)
            self.alternatives_card.setGeometry((card_w + gap) * 2, card_y, width - (card_w + gap) * 2, card_h)
            button_y = card_y + card_h + 18
        else:
            card_w = width
            self.requirements_card.setGeometry(0, card_y, card_w, card_h)
            self.warnings_card.setGeometry(0, card_y + card_h + gap, card_w, card_h)
            self.alternatives_card.setGeometry(0, card_y + (card_h + gap) * 2, card_w, card_h)
            button_y = card_y + (card_h + gap) * 3 + 18
            result_height = button_y + 70
            self.result_area.setGeometry(x, y, width, result_height)

    def focus_search_text(self, text: str) -> None:
        self.input_card.tool_selector.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.input_card.tool_selector.set_query_text(text)

    def show_toast(self, message: str) -> None:
        self.toast.show_message(message)

    def close_search_overlays(self) -> None:
        self.input_card.close_dropdowns()
        if self.details_overlay.isVisible():
            self.details_overlay.hide()
        if self.setup_packet_overlay.isVisible():
            self.setup_packet_overlay.hide()
        if self.scrim.isVisible():
            self.scrim.hide()
        preview = getattr(self, "_pdf_preview_overlay", None)
        if preview is not None and preview.isVisible():
            preview.close_preview()

    def open_details(self, focus: str = "details") -> None:
        self.input_card.close_dropdowns()
        if self.setup_packet_overlay.isVisible():
            self.setup_packet_overlay.hide()
        if focus == "recent":
            self.details_overlay.set_recent_checks(self.recent_checks)
        else:
            self.details_overlay.set_result(self.current_result, focus=focus)
        self.scrim.setGeometry(self.rect())
        self.scrim.show()
        self.scrim.raise_()
        rect = self._details_rect()
        self.details_overlay.raise_()
        self.details_overlay.animate_open(rect)

    def close_details(self) -> None:
        self.scrim.hide()
        self.details_overlay.animate_close(self.details_overlay.geometry())

    def open_setup_packet_overlay(self, setup: PacketSetup | None = None) -> bool:
        if setup is not None:
            if not self._apply_setup_for_packet(setup):
                return False
        setup = self.current_valid_setup()
        if setup is None or self.current_result is None:
            self.show_toast("Run a complete compatible Fit Check before creating a packet.")
            return False
        self.input_card.close_dropdowns()
        if self.details_overlay.isVisible():
            self.details_overlay.hide()
        self.setup_packet_overlay.set_setup(setup, self.current_result, bundle=self.bundle)
        self.scrim.setGeometry(self.rect())
        self.scrim.show()
        self.scrim.raise_()
        self.setup_packet_overlay.raise_()
        self.setup_packet_overlay.animate_open(self._setup_packet_rect())
        return True

    def close_setup_packet(self) -> None:
        self.scrim.hide()
        self.setup_packet_overlay.animate_close(self.setup_packet_overlay.geometry())

    def _scrim_clicked(self) -> None:
        if self.setup_packet_overlay.isVisible():
            self.close_setup_packet()
            return
        if self.details_overlay.isVisible():
            self.close_details()
            return
        self.scrim.hide()

    def _clear_requested(self) -> None:
        self._result_version += 1
        self._cancel_recent_save_timer()
        self.input_card.clear_all(emit=False)
        self._auto_filled_slots.clear()
        self._autofill_sources.clear()
        self._blocked_autofill_sources.clear()
        self._sync_selector_options()
        self.current_result = None
        self.helper.show()
        self._hide_result()
        self.update()

    def mousePressEvent(self, event) -> None:
        if not self.input_card.geometry().contains(event.position().toPoint()):
            self.input_card.close_dropdowns()
        super().mousePressEvent(event)

    def _details_rect(self) -> QRect:
        width = min(1120, max(680, self.width() - 180))
        height = min(820, max(560, self.height() - 170))
        return QRect((self.width() - width) // 2, 112, width, height)

    def _setup_packet_rect(self) -> QRect:
        width = min(780, max(680, self.width() - 220))
        height = min(690, max(560, self.height() - 190))
        return QRect((self.width() - width) // 2, (self.height() - height) // 2 + 16, width, height)

    def _selection_changed(self) -> None:
        self._result_version += 1
        self._cancel_recent_save_timer()
        self.current_result = None
        self._handle_autofill_touch()
        self._clear_stale_autofill()
        self._sync_selector_options()
        self._auto_fill_third_slot()
        self._sync_selector_options()
        self._refresh_result(animate=True)

    def _selector_query_changed(self) -> None:
        self._cancel_recent_save_timer()
        query_index = self.input_card.last_query_index
        self._sync_selector_options()
        if query_index is not None:
            self.input_card.show_dropdown(query_index)

    def _selector_focus_changed(self) -> None:
        focus_index = self.input_card.last_focus_index
        self._sync_selector_options()
        if focus_index is None:
            return
        self.input_card.show_dropdown(focus_index)

    def _run_requested(self) -> None:
        self._cancel_recent_save_timer()
        self.input_card.close_dropdowns()
        self.input_card.commit_pending_text(emit=False)
        if self._request() == FitCheckRequest():
            self.show_toast("Select a Tool, Machine, or EOAT to begin.")
            return
        self._refresh_result(animate=True)

    def _refresh_result(self, *, animate: bool) -> None:
        version = self._result_version
        signature = self.input_card.selection_signature()
        request = self._request()
        result = self.service.run_fit_check(request)
        if result is not None:
            result = self._apply_compatibility_strictness(result)
        if version != self._result_version or signature != self.input_card.selection_signature():
            return
        self.current_result = result
        if result is None:
            self.helper.show()
            self._hide_result()
            return
        self.helper.hide()
        flow_options = self._flow_slot_options(result)
        self.result_card.set_result(result, selected_eoat_id=request.eoat_id, photo_path=self._eoat_photo_path(result.recommended_eoat))
        self.path_row.set_result(
            result,
            flow_options,
            photo_path=self._eoat_photo_path(result.selected_eoat),
        )
        self.requirements_card.set_result(result)
        self.warnings_card.set_result(result)
        self.alternatives_card.setVisible(
            _fit_bool(self.controller, "fit_check.show_compatible_machine_alternatives", True)
            or _fit_bool(self.controller, "fit_check.show_compatible_eoat_alternatives", True)
        )
        self.alternatives_card.enabled_kinds = {
            kind
            for kind, path in (
                ("machines", "fit_check.show_compatible_machine_alternatives"),
                ("eoats", "fit_check.show_compatible_eoat_alternatives"),
            )
            if _fit_bool(self.controller, path, True)
        }
        self.alternatives_card.set_result(result)
        if self._result_stale:
            self._present_stale_result_notice()
        self._show_result(animate=animate)
        self._schedule_recent_save_if_eligible()

    def _hide_result(self) -> None:
        self.result_anim.stop()
        self.result_geo_anim.stop()
        self.result_effect.setOpacity(0.0)
        self.result_area.hide()

    def _show_result(self, *, animate: bool) -> None:
        self.result_area.show()
        self.result_area.raise_()
        if prefers_reduced_motion() or not animate:
            self.result_effect.setOpacity(1.0)
            geo = self.result_area.geometry()
            self.result_area.setGeometry(geo.x(), self._result_target_y, geo.width(), geo.height())
            return
        end = self.result_area.geometry()
        end.moveTop(self._result_target_y)
        start = QRect(end)
        start.moveTop(self._result_target_y + 10)
        self.result_geo_anim.stop()
        self.result_anim.stop()
        self.result_area.setGeometry(start)
        self.result_effect.setOpacity(0.0)
        self.result_geo_anim.setStartValue(start)
        self.result_geo_anim.setEndValue(end)
        self.result_anim.setStartValue(0.0)
        self.result_anim.setEndValue(1.0)
        self.result_geo_anim.start()
        self.result_anim.start()

    def _request(self) -> FitCheckRequest:
        tool_id, machine_id, eoat_id = self._request_values()
        eoat_mode = "manual" if eoat_id else "auto"
        return FitCheckRequest(tool_id=tool_id, machine_id=machine_id, eoat_id=eoat_id, eoat_mode=eoat_mode)

    def _request_values(self) -> tuple[str, str, str]:
        values = {kind: self.input_card.selected_key(kind) for kind in _RECORD_KINDS}
        occupied = {kind for kind, value in values.items() if value}
        for index, text in enumerate(self.input_card.slot_texts()):
            if not text or self.input_card.option_at(index) is not None:
                continue
            kind = self._infer_kind_for_text(text, occupied)
            if kind and kind not in occupied:
                values[kind] = text
                occupied.add(kind)
        return values["tool"], values["machine"], values["eoat"]

    def _flow_slot_options(self, result: FitCheckResult) -> list[SelectorOption | None]:
        options = self.input_card.selected_slot_options()
        flow_options: list[SelectorOption | None] = []
        occupied = {option.kind for option in options if option is not None}
        for index, option in enumerate(options):
            if option is not None:
                flow_options.append(option)
                continue
            if not _fit_bool(self.controller, "fit_check.always_show_entered_flow_items", True):
                flow_options.append(None)
                continue
            text = self.input_card.query_at(index).strip()
            if not text:
                flow_options.append(None)
                continue
            kind = self._infer_kind_for_text(text, occupied)
            if not kind:
                flow_options.append(None)
                continue
            occupied.add(kind)
            flow_options.append(
                SelectorOption(
                    key=text,
                    display=text,
                    secondary=_flow_raw_secondary(result, kind),
                    mode="manual",
                    kind=kind,
                )
            )
        return flow_options

    def _apply_compatibility_strictness(self, result: FitCheckResult) -> FitCheckResult:
        strictness = str(_fit_setting(self.controller, "fit_check.compatibility_strictness", "strict") or "strict")
        if strictness == "strict":
            return result
        if strictness == "balanced" and result.status == "unknown":
            return replace(
                result,
                status="warning",
                headline="Needs Review",
                message="Atlas has partial compatibility data. Review warnings before using this setup.",
            )
        if strictness == "loose" and result.status in {"unknown", "not_compatible"} and result.validity.valid_for_inputs(result.input_completeness):
            return replace(
                result,
                status="warning",
                headline="Possible Match",
                message="Loose mode shows this as a possible setup with warnings. Verify before use.",
            )
        return result

    def _infer_kind_for_text(self, text: str, occupied_kinds: set[str] | None = None) -> str:
        value = display_value(text)
        if not value:
            return ""
        allowed = set(_RECORD_KINDS) - set(occupied_kinds or ())
        if not allowed:
            allowed = set(_RECORD_KINDS)
        exact = self._exact_options_for_text(value, allowed)
        if len(exact) == 1:
            return exact[0].kind
        if len({option.kind for option in exact}) == 1:
            return exact[0].kind
        if len(allowed) == 1:
            return next(iter(allowed))
        folded = value.casefold()
        if "eoat" in folded and "eoat" in allowed:
            return "eoat"
        if "machine" in folded and "machine" in allowed:
            return "machine"
        return ""

    def _exact_options_for_text(self, text: str, allowed_kinds: set[str]) -> list[SelectorOption]:
        folded = text.casefold()
        matches = []
        for kind in _RECORD_KINDS:
            if kind not in allowed_kinds:
                continue
            for option in self._options_for_kind(kind):
                if folded in {option.key.casefold(), option.display.casefold()}:
                    matches.append(option)
                    continue
                if _normalized_key_for_kind(kind, text) and _normalized_key_for_kind(kind, text) == _normalized_key_for_kind(kind, option.key):
                    matches.append(option)
        return _dedupe_options(matches)

    def _schedule_recent_save_if_eligible(self) -> None:
        self._cancel_recent_save_timer()
        if not self._is_recent_save_eligible():
            return
        signature = self._ordered_signature()
        if not signature:
            return
        if _fit_bool(self.controller, "fit_check.save_recent_only_when_different", True) and signature == self._last_saved_recent_signature:
            return
        self._pending_recent_signature = signature
        self._recent_save_timer.setInterval(_fit_int(self.controller, "fit_check.save_recent_after_seconds", 20) * 1000)
        self._recent_save_timer.start()

    def _cancel_recent_save_timer(self) -> None:
        timer = getattr(self, "_recent_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        self._pending_recent_signature = ""

    def _recent_save_timer_elapsed(self) -> None:
        signature = self._pending_recent_signature
        self._pending_recent_signature = ""
        if not signature:
            return
        if signature != self._ordered_signature():
            return
        if _fit_bool(self.controller, "fit_check.save_recent_only_when_different", True) and signature == self._last_saved_recent_signature:
            return
        if not self._is_recent_save_eligible(expected_signature=signature):
            return
        self._save_recent_check(signature)

    def _save_recent_check(self, signature: str) -> None:
        result = self.current_result
        if result is None:
            return
        request = self._request()
        check = RecentFitCheck(
            timestamp=datetime.now(),
            request=request,
            headline=_recent_items_headline(self.input_card.selected_item_payloads()) or self._recent_headline(request, result),
            summary=result.message,
            status=result.status,
            confidence=result.confidence,
            selected_items=self.input_card.selected_item_payloads(),
            ordered_signature=signature,
            match_level=_match_label(result),
            id=signature,
        )
        max_recent = max(1, _fit_int(self.controller, "fit_check.max_recent_fit_checks", 15))
        existing = (
            [item for item in self.recent_checks if (item.ordered_signature or item.id) != signature]
            if _fit_bool(self.controller, "fit_check.save_recent_only_when_different", True)
            else list(self.recent_checks)
        )
        self.recent_checks = [check, *existing][:max_recent]
        self._last_saved_recent_signature = signature
        _save_recent_fit_checks(self.recent_checks)

    def _is_recent_save_eligible(self, *, expected_signature: str = "") -> bool:
        if not self.isVisible() or not self.result_area.isVisible():
            return False
        if not _fit_bool(self.controller, "fit_check.save_recent_checks", True):
            return False
        result = self.current_result
        if result is None:
            return False
        signature = self._ordered_signature()
        if not signature or (expected_signature and signature != expected_signature):
            return False
        complete_only = _fit_bool(self.controller, "fit_check.save_recent_only_when_complete", True)
        if complete_only:
            if len(self.input_card.selected_options()) != 3:
                return False
            if any(option is None for option in self.input_card.selected_slot_options()):
                return False
        elif not any(option is not None for option in self.input_card.selected_slot_options()):
            return False
        if not complete_only:
            return True
        if not self._selected_records_are_current():
            return False
        return self._result_matches_ordered_selection(result)

    def _ordered_signature(self) -> str:
        return _ordered_signature(self.input_card.selected_slot_options())

    def _selected_records_are_current(self) -> bool:
        for option in self.input_card.selected_slot_options():
            if option is None:
                return False
            if option.kind == "tool" and self.service._tool(option.key) is None:
                return False
            if option.kind == "machine" and self.service._machine(option.key) is None:
                return False
            if option.kind == "eoat" and self.service._eoat(option.key) is None:
                return False
            if option.kind not in _RECORD_KINDS:
                return False
        return True

    def _result_matches_ordered_selection(self, result: FitCheckResult) -> bool:
        selected_tool = self.input_card.selected_key("tool")
        selected_machine = self.input_card.selected_key("machine")
        selected_eoat = self.input_card.selected_key("eoat")
        if not (selected_tool and selected_machine and selected_eoat):
            return False
        return (
            normalized_tool_key(getattr(result.selected_tool, "tool", "")) == normalized_tool_key(selected_tool)
            and normalized_machine_key(getattr(result.selected_machine, "machine", "")) == normalized_machine_key(selected_machine)
            and normalized_eoat_key(getattr(result.selected_eoat, "eoat_id", "")) == normalized_eoat_key(selected_eoat)
        )

    def _recent_headline(self, request: FitCheckRequest, result: FitCheckResult) -> str:
        parts = []
        if request.tool_id:
            parts.append(request.tool_id)
        if request.eoat_id:
            parts.append(request.eoat_id)
        elif result.recommended_eoat is not None:
            parts.append(result.recommended_eoat.eoat_id)
        if request.machine_id:
            parts.append(machine_label(request.machine_id))
        return " -> ".join(parts) or result.headline

    def _load_recent_check(self, check: RecentFitCheck) -> None:
        self.scrim.hide()
        self.details_overlay.hide()
        self.input_card.close_dropdowns()
        self._sync_selector_options()
        self.input_card.apply_recent_check(check)
        self._auto_filled_slots.clear()
        self._autofill_sources.clear()
        self._blocked_autofill_sources.clear()
        self._sync_selector_options()
        restored = self._request()
        missing = _missing_recent_parts(check.request, restored)
        if missing:
            self.show_toast(f"Some saved records are no longer indexed: {', '.join(missing)}.")
        if restored == FitCheckRequest():
            return
        self._refresh_result(animate=True)

    def current_valid_setup(self) -> PacketSetup | None:
        result = self.current_result
        request = self._request()
        if not (request.tool_id and request.machine_id and request.eoat_id):
            return None
        if not is_valid_fit_result(result):
            return None
        if not self._result_matches_ordered_selection(result):
            return None
        return PacketSetup(tool_id=request.tool_id, machine_id=request.machine_id, eoat_id=request.eoat_id)

    def _create_setup_packet_from_current(self) -> None:
        self.open_setup_packet_overlay()

    def _create_setup_packet_from_recent(self, check: RecentFitCheck) -> None:
        request = check.request
        if not (request.tool_id and request.machine_id and request.eoat_id) or check.status not in {"compatible", "warning"}:
            self.show_toast("This saved Fit Check is incomplete, so a setup packet cannot be created.")
            return
        self._load_recent_check(check)
        QTimer.singleShot(0, self, self.open_setup_packet_overlay)

    def _apply_setup_for_packet(self, setup: PacketSetup) -> bool:
        if self.bundle is None:
            self.show_toast("Atlas data is still loading.")
            return False
        normalized = setup.normalized()
        if not normalized.complete():
            self.show_toast("A Tool, Machine, and EOAT are required for a setup packet.")
            return False
        self.input_card.close_dropdowns()
        self._sync_selector_options()
        self.input_card.apply_request(normalized.to_fit_request())
        self._auto_filled_slots.clear()
        self._autofill_sources.clear()
        self._blocked_autofill_sources.clear()
        self._sync_selector_options()
        self._refresh_result(animate=True)
        if self.current_valid_setup() is None:
            self.show_toast("That setup is not currently a compatible Fit Check.")
            return False
        return True

    def _generate_setup_packet_pdf(self, *, preview: bool) -> None:
        if self.bundle is None:
            self.show_toast("Atlas data is still loading.")
            return
        preview = bool(preview or _fit_bool(self.controller, "pdf.preview_before_save", True))
        setup = self.current_valid_setup()
        if setup is None:
            self.show_toast("A packet cannot be generated until Fit Check is complete and compatible.")
            return
        packet_options = self.setup_packet_overlay.selected_options()
        packet_options["ask_location_when_save_clicked"] = _fit_bool(self.controller, "pdf.ask_location_when_save_clicked", True)
        include_photo = bool(packet_options.get("eoat_photo", True)) and _fit_bool(self.controller, "pdf.include_photos", True)
        detailed = (
            packet_options.get("format") == "detailed"
            or bool(packet_options.get("detailed_record_information"))
            or any(
                _fit_bool(self.controller, path, True)
                for path in ("pdf.include_eoat_profile", "pdf.include_tool_profile", "pdf.include_machine_profile")
            )
        )
        try:
            context = build_setup_packet_context(
                self.bundle,
                setup.machine_id,
                setup.tool_id,
                setup.eoat_id,
                SetupPacketOptions(
                    packet_type=PACKET_TYPE_SETUP_VERIFICATION,
                    photo_inclusion=PHOTO_KEY if include_photo else PHOTO_NONE,
                    detail_level="detailed" if detailed else "standard",
                    include_setup_summary=bool(packet_options.get("setup_summary", True)) and _fit_bool(self.controller, "pdf.include_fit_check_summary", True),
                    include_compatibility_result=bool(packet_options.get("compatibility_result", True)) and _fit_bool(self.controller, "pdf.include_compatibility_notes", True),
                    include_requirements_check=bool(packet_options.get("requirements_check", True)) and _fit_bool(self.controller, "pdf.include_required_setup_notes", True),
                    include_warnings=bool(packet_options.get("warnings", True)) and _fit_bool(self.controller, "pdf.include_reference_warnings", True),
                    include_alternatives=bool(packet_options.get("alternatives", True)),
                    include_eoat_photo=include_photo,
                    include_setup_checklist=bool(packet_options.get("setup_checklist", True)) and _fit_bool(self.controller, "pdf.include_required_setup_notes", True),
                    include_detailed_record_information=bool(packet_options.get("detailed_record_information", False)),
                    include_related_records=bool(packet_options.get("related_records", False)),
                    include_extra_notes=bool(packet_options.get("extra_notes", False)),
                ),
            )
            final_dir = self._pdf_output_dir()
            output_dir = setup_packet_preview_dir() if preview else final_dir
            result = export_setup_packet_pdf(context, output_dir=output_dir)
            default_save_path = final_dir / self._setup_packet_filename_from_settings(context)
            record_id = f"Tool {setup.tool_id} / Machine {setup.machine_id} / EOAT {setup.eoat_id}"
            detail_data = RecordDetailData(
                record_type="setup_packet",
                record_id=record_id,
                title="Setup Packet",
                subtitle="Generated from Fit Check",
                condition="Compatible",
                plant_area="",
                hero_fields=(),
                detail_sections=(),
                documentation_fields=(),
                photo_groups=(),
                history_fields=(),
                summary_fields=(),
                report_sections=(),
                warnings=context.warnings,
                source_rows=(),
            )
            session = PdfPreviewSession(
                record_type="setup_packet",
                record_id=record_id,
                temp_pdf_path=result.path,
                default_save_path=result.path if not preview else default_save_path,
                options=packet_options,
                auto_save_close_seconds=float(_fit_int(self.controller, "pdf.auto_save_if_closed_under_seconds", 10)),
                temp_preview_dir=output_dir if preview else None,
            )
            if not preview:
                session.save_as(result.path)
        except Exception as exc:
            self.show_toast(f"Setup Packet PDF generation failed: {exc}")
            return
        self.close_setup_packet()
        if not _fit_bool(self.controller, "pdf.open_in_app", True):
            if preview:
                session.defer_cleanup()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.path)))
            self.show_toast(f"Generated packet PDF: {result.path}")
            return
        self._pdf_preview_overlay = PDFPreviewOverlay.open_for(
            self,
            session,
            detail_data,
            project_root=self.bundle.project_root,
        )
        self._pdf_preview_overlay.destroyed.connect(lambda *_args: setattr(self, "_pdf_preview_overlay", None))

    def _pdf_output_dir(self) -> Path:
        configured = str(_fit_setting(self.controller, "paths.output_folder", "") or "").strip()
        if configured:
            return Path(configured).expanduser()
        return atlas_setup_packet_dir(self.bundle.project_root if self.bundle is not None else "")

    def _setup_packet_filename_from_settings(self, context) -> str:
        pattern = str(_fit_setting(self.controller, "pdf.default_file_name_pattern", "") or "").strip()
        if not pattern:
            return setup_packet_filename(context)
        replacements = {
            "{tool}": context.tool_id,
            "{machine}": context.machine_id,
            "{eoat}": context.eoat_id,
            "{date}": datetime.now().strftime("%Y%m%d"),
        }
        filename = pattern
        for token, value in replacements.items():
            filename = filename.replace(token, _safe_filename_component(value))
        if not filename.casefold().endswith(".pdf"):
            filename = f"{filename}.pdf"
        return filename

    def hideEvent(self, event) -> None:
        self._cancel_recent_save_timer()
        super().hideEvent(event)

    def _handle_autofill_touch(self) -> None:
        if self._autofilling:
            return
        changed_index = self.input_card.last_changed_index
        if changed_index is None:
            return
        source_key = self._autofill_sources.get(changed_index)
        if source_key is None and self.input_card.last_unselected_index == changed_index:
            source_key = self._autofill_pair_key(exclude_index=changed_index)
        if source_key:
            self._blocked_autofill_sources.add(source_key)
        self._auto_filled_slots.discard(changed_index)
        self._autofill_sources.pop(changed_index, None)

    def _clear_stale_autofill(self) -> None:
        if self._autofilling:
            return
        for index in list(self._auto_filled_slots):
            source_key = self._autofill_pair_key(exclude_index=index)
            if source_key != self._autofill_sources.get(index):
                self.input_card.clear_slot(index, emit=False)
                self._auto_filled_slots.discard(index)
                self._autofill_sources.pop(index, None)

    def _auto_fill_third_slot(self) -> bool:
        if self._autofilling:
            return False
        selected = self.input_card.selected_slot_options()
        selected_count = sum(option is not None for option in selected)
        if selected_count != 2:
            return False
        selected_indices = [index for index, option in enumerate(selected) if option is not None]
        if selected_indices != [0, 1]:
            return False
        try:
            empty_index = next(index for index, option in enumerate(selected) if option is None)
        except StopIteration:
            return False
        if not self.input_card.is_slot_empty(empty_index):
            return False
        source_key = self._autofill_pair_key(exclude_index=empty_index)
        if not source_key or source_key in self._blocked_autofill_sources:
            return False
        option = self._best_autofill_option(empty_index)
        if option is None:
            return False
        self._autofilling = True
        try:
            if not self.input_card.select_option_at(empty_index, option, emit=False):
                return False
            self._auto_filled_slots.add(empty_index)
            self._autofill_sources[empty_index] = source_key
            return True
        finally:
            self._autofilling = False

    def _autofill_pair_key(self, *, exclude_index: int) -> str:
        parts = [
            f"{option.kind}:{option.key}"
            for index, option in enumerate(self.input_card.selected_slot_options())
            if index != exclude_index and option is not None
        ]
        return "|".join(parts) if len(parts) == 2 else ""

    def _best_autofill_option(self, empty_index: int) -> SelectorOption | None:
        options = self._suggestions_for_slot(empty_index)
        if not options:
            return None
        context = [option for index, option in enumerate(self.input_card.selected_slot_options()) if index != empty_index and option is not None]
        kinds = {option.kind for option in context}
        if kinds == {"tool", "machine"}:
            tool = self.service._tool(next(option.key for option in context if option.kind == "tool"))
            machine = self.service._machine(next(option.key for option in context if option.kind == "machine"))
            best_eoat = self.service._best_eoat(tool, machine, None)
            if best_eoat is not None:
                key = normalized_eoat_key(best_eoat.eoat_id)
                for option in options:
                    if option.kind == "eoat" and normalized_eoat_key(option.key) == key:
                        return option
        ranked = sorted(options, key=lambda option: (-self._autofill_score(option, context), option.display.casefold()))
        return ranked[0] if ranked and self._autofill_score(ranked[0], context) > 0 else None

    def _autofill_score(self, option: SelectorOption, context: list[SelectorOption]) -> int:
        score = 0
        if all(self._options_are_compatible(option, selected) for selected in context):
            score += 100
        if option.kind == "eoat":
            eoat = self.service._eoat(option.key)
            machine = next((self.service._machine(selected.key) for selected in context if selected.kind == "machine"), None)
            if eoat is not None and machine is not None and normalized_eoat_key(getattr(machine, "current_eoat", "")) == normalized_eoat_key(eoat.eoat_id):
                score += 20
            if eoat is not None and display_value(getattr(eoat, "eoat_type", "")):
                score += 5
        if option.kind == "machine":
            machine = self.service._machine(option.key)
            if machine is not None and display_value(getattr(machine, "robot_model", "")):
                score += 5
        if option.kind == "tool":
            tool = self.service._tool(option.key)
            if tool is not None and display_value(getattr(tool, "part_description", "")):
                score += 5
        return score

    def _sync_selector_options(self) -> None:
        self.input_card.set_options(
            slot_options=(
                self._suggestions_for_slot(0),
                self._suggestions_for_slot(1),
                self._suggestions_for_slot(2),
            )
        )

    def _all_record_options(self) -> list[SelectorOption]:
        return [*self._tool_options(), *self._machine_options(), *self._eoat_options()]

    def _options_for_kind(self, kind: str) -> list[SelectorOption]:
        if kind == "tool":
            return self._tool_options()
        if kind == "machine":
            return self._machine_options()
        if kind == "eoat":
            return self._eoat_options()
        return []

    def _tool_options(self) -> list[SelectorOption]:
        options = []
        for tool in getattr(self.bundle, "tools", ()) or ():
            secondary = tool.part_description or tool.part_family or ", ".join(tool.parts[:2])
            keywords = " ".join((tool.label, tool.part_family, tool.part_description, " ".join(tool.molds), " ".join(tool.parts)))
            options.append(SelectorOption(tool.tool, tool.tool, secondary, keywords=keywords, kind="tool", raw_record=tool))
        return sorted(options, key=lambda option: option.display.casefold())

    def _machine_options(self) -> list[SelectorOption]:
        options = []
        for machine in getattr(self.bundle, "machines", ()) or ():
            secondary = machine.robot_model or machine.robot_type or "Robot type unknown"
            keywords = " ".join((machine.label, machine.robot_type, machine.robot_model, machine.controller))
            options.append(SelectorOption(machine.machine, machine_label(machine.machine), secondary, keywords=keywords, kind="machine", raw_record=machine))
        return sorted(options, key=lambda option: _machine_key(option.key))

    def _eoat_options(self, machine_id: str = "") -> list[SelectorOption]:
        options = []
        for eoat in getattr(self.bundle, "eoats", ()) or ():
            keywords = " ".join((eoat.eoat_type, eoat.part_family, eoat.part_description, " ".join(eoat.tools), " ".join(eoat.machines)))
            options.append(SelectorOption(eoat.eoat_id, eoat.eoat_id, eoat.eoat_type or "EOAT", mode="manual", keywords=keywords, kind="eoat", raw_record=eoat))
        return options

    def _suggestions_for_slot(self, index: int) -> list[SelectorOption]:
        current = self.input_card.option_at(index)
        query = self.input_card.query_at(index).strip()
        context = [
            option
            for slot, option in enumerate(self.input_card.selected_slot_options())
            if slot != index and option is not None
        ]
        allowed_kinds = self._allowed_kinds_for_slot(current, context)
        suggestions = CompatibilityOptionFilter(self.service, self._options_for_kind).suggestions(
            current=current,
            query=query,
            context=context,
            allowed_kinds=allowed_kinds,
        )
        visible_kinds = {
            kind
            for kind, setting_path in (
                ("eoat", "fit_check.show_compatible_eoat_alternatives"),
                ("machine", "fit_check.show_compatible_machine_alternatives"),
                ("tool", "fit_check.show_compatible_tool_alternatives"),
            )
            if _fit_bool(self.controller, setting_path, True)
        }
        return [option for option in suggestions if option.kind in visible_kinds or current is not None and option.kind == current.kind]

    def _allowed_kinds_for_slot(self, current: SelectorOption | None, context: list[SelectorOption]) -> set[str]:
        if current is not None and current.kind in _RECORD_KINDS:
            return {current.kind}
        selected_kinds = {option.kind for option in context if option.kind in _RECORD_KINDS}
        missing = set(_RECORD_KINDS) - selected_kinds
        return missing or set(_RECORD_KINDS)

    def _next_empty_slot_after(self, index: int | None) -> int | None:
        if index is None:
            return None
        for candidate in range(index + 1, len(self.input_card.selectors)):
            if self.input_card.is_slot_empty(candidate):
                return candidate
        return None

    def _options_are_compatible(self, candidate: SelectorOption, selected: SelectorOption) -> bool:
        return CompatibilityOptionFilter(self.service, self._options_for_kind).options_are_compatible(candidate, selected)

    def _tool_machine_compatible(self, tool_id: str, machine_id: str) -> bool:
        return CompatibilityOptionFilter(self.service, self._options_for_kind)._tool_machine_compatible(tool_id, machine_id)

    def _tool_eoat_compatible(self, tool_id: str, eoat_id: str) -> bool:
        return CompatibilityOptionFilter(self.service, self._options_for_kind)._tool_eoat_compatible(tool_id, eoat_id)

    def _machine_eoat_compatible(self, machine_id: str, eoat_id: str) -> bool:
        return CompatibilityOptionFilter(self.service, self._options_for_kind)._machine_eoat_compatible(machine_id, eoat_id)

    def _select_machine(self, machine: MachineRecord) -> None:
        option = SelectorOption(
            machine.machine,
            machine_label(machine.machine),
            machine.robot_model or machine.robot_type or "Robot type unknown",
            keywords=" ".join((machine.label, machine.robot_type, machine.robot_model, machine.controller)),
            kind="machine",
            raw_record=machine,
        )
        self._select_alternative_option(option)

    def _select_eoat(self, eoat: EOATRecord) -> None:
        option = SelectorOption(
            eoat.eoat_id,
            eoat.eoat_id,
            eoat.eoat_type or "EOAT",
            mode="manual",
            keywords=" ".join((eoat.eoat_type, eoat.part_family, eoat.part_description, " ".join(eoat.tools), " ".join(eoat.machines))),
            kind="eoat",
            raw_record=eoat,
        )
        self._select_alternative_option(option)

    def _select_alternative_option(self, option: SelectorOption) -> None:
        if not _fit_bool(self.controller, "fit_check.click_alternatives_to_apply", True):
            self.show_toast("Alternative click-to-apply is disabled in Settings.")
            return
        index = self.input_card.index_for_kind(option.kind)
        if index is None:
            index = self.input_card.first_empty_index()
        if index is None and self._auto_filled_slots:
            index = sorted(self._auto_filled_slots)[0]
        if index is None:
            self.show_toast("Clear a setup item before adding this option.")
            return
        self._cancel_recent_save_timer()
        self._result_version += 1
        self.current_result = None
        source_key = self._autofill_sources.get(index)
        if source_key:
            self._blocked_autofill_sources.add(source_key)
        self._auto_filled_slots.discard(index)
        self._autofill_sources.pop(index, None)
        self.input_card.close_dropdowns()
        if not self.input_card.select_option_at(index, option, emit=False):
            self.show_toast("Could not apply that alternative.")
            return
        self.input_card.mark_slot_changed(index)
        self._sync_selector_options()
        self._refresh_result(animate=True)

    def _open_record(self, entity_type: str, key: str) -> None:
        if not key:
            return
        if entity_type == "tool" and hasattr(self.controller, "open_tool"):
            self.controller.open_tool(key, source="fit_check")
        elif entity_type == "machine" and hasattr(self.controller, "open_machine"):
            self.controller.open_machine(key, source="fit_check")
        elif entity_type == "eoat" and hasattr(self.controller, "open_eoat"):
            self.controller.open_eoat(key, source="fit_check")

    def _result_eoat_id(self) -> str:
        eoat = getattr(self.current_result, "recommended_eoat", None)
        return getattr(eoat, "eoat_id", "") if eoat is not None else ""

    def _eoat_photo_path(self, eoat: EOATRecord | None) -> str:
        if eoat is None:
            return ""
        photo_set = getattr(eoat, "photos", None)
        photos = [*(getattr(photo_set, "indexed_photos", ()) or ()), *(getattr(photo_set, "photos", ()) or ())]
        for photo in photos:
            for candidate in (
                getattr(photo, "path", ""),
                getattr(photo, "stored_relative_path", ""),
                getattr(photo, "photo_link", ""),
            ):
                text = str(candidate or "").strip()
                if not text:
                    continue
                path = Path(text)
                if not path.is_absolute() and getattr(self.bundle, "project_root", ""):
                    path = Path(self.bundle.project_root) / path
                if path.exists():
                    return str(path)
        return ""


class FitCheckInstructionStrip(GlassPanel):
    def __init__(self, text: str, parent=None):
        super().__init__(parent, radius=8)
        self.setFixedHeight(36)
        self.set_glass(alpha=92, border_alpha=92, border_color=QColor("#2b86e7"), fill_color=QColor("#071d3c"), outer_glow_alpha=30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 0, 13, 0)
        layout.setSpacing(9)
        icon = QLabel()
        icon.setPixmap(glyph_icon("status", ACCENT_BRIGHT, 16).pixmap(16, 16))
        label = QLabel(text)
        label.setObjectName("FitCheckInputHint")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        label.setWordWrap(False)
        layout.addWidget(icon)
        layout.addWidget(label, 1)


class FitCheckInputCard(GlassPanel):
    selection_changed = Signal()
    query_changed = Signal()
    focus_changed = Signal()
    run_requested = Signal()
    recent_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=8, streaks=True)
        self.set_glass(alpha=122, border_alpha=80, border_color=QColor("#1f87ff"), fill_color=QColor("#051226"))
        self.last_changed_index: int | None = None
        self.last_query_index: int | None = None
        self.last_focus_index: int | None = None
        self.last_unselected_index: int | None = None
        self.active_input_index: int | None = None
        self.open_dropdown_index: int | None = None
        self.tool_selector = FitCheckSelector("Setup Item 1", "Type or select Tool, Machine, or EOAT...")
        self.machine_selector = FitCheckSelector("Setup Item 2", "Compatible options appear here...")
        self.eoat_selector = FitCheckSelector("Setup Item 3", "Add the remaining setup item...")
        self.selectors = (self.tool_selector, self.machine_selector, self.eoat_selector)
        for selector in self.selectors:
            selector.selection_changed.connect(lambda selector=selector: self._selector_changed(selector))
            selector.query_changed.connect(lambda selector=selector: self._selector_query_changed(selector))
            selector.focus_requested.connect(lambda selector=selector: self._selector_focused(selector))
        self.hint = FitCheckInstructionStrip("Start with any Tool, Machine, or EOAT. Compatible choices will appear automatically.")
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("FitCheckClearButton")
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setFixedSize(70, 34)
        self.clear_button.clicked.connect(self._clear_button_clicked)
        self.recent_button = QPushButton("View Recent Checks")
        self.recent_button.setObjectName("FitCheckSecondaryButton")
        self.recent_button.setIcon(glyph_icon("status", QColor("#ffffff"), 16))
        self.recent_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_button.setFixedHeight(42)
        self.recent_button.clicked.connect(self.recent_requested.emit)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 20, 22, 20)
        outer.setSpacing(12)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.hint, 1)
        header.addWidget(self.clear_button, 0)
        outer.addLayout(header)
        self._layout = QHBoxLayout()
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(32)
        self._layout.addWidget(self.tool_selector, 1)
        self._layout.addWidget(self.machine_selector, 1)
        self._layout.addWidget(self.eoat_selector, 1)
        buttons = QWidget()
        buttons.setObjectName("FitCheckInputButtons")
        buttons.setMinimumWidth(170)
        buttons.setMinimumHeight(44)
        button_layout = QVBoxLayout(buttons)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(8)
        button_layout.addWidget(self.recent_button)
        self._layout.addWidget(buttons, 0)
        outer.addLayout(self._layout)
        self._update_clear_button()

    def set_options(
        self,
        *,
        tool_options: list[SelectorOption] | None = None,
        machine_options: list[SelectorOption] | None = None,
        eoat_options: list[SelectorOption] | None = None,
        slot_options: tuple[list[SelectorOption], list[SelectorOption], list[SelectorOption]] | None = None,
        preserve_eoat: bool = False,
    ) -> None:
        if slot_options is None:
            merged = [*(tool_options or ()), *(machine_options or ()), *(eoat_options or ())]
            slot_options = (merged, merged, merged)
        for selector, options in zip(self.selectors, slot_options):
            selector.set_options(_dedupe_options(options))

    def apply_request(self, request: FitCheckRequest) -> None:
        self.clear_all(emit=False)
        self.select_kind("tool", request.tool_id, emit=False)
        self.select_kind("machine", request.machine_id, emit=False)
        if request.eoat_id:
            self.select_kind("eoat", request.eoat_id, emit=False)
        self._update_clear_button()

    def apply_recent_check(self, check: RecentFitCheck) -> None:
        self.clear_all(emit=False)
        restored = False
        for item in check.selected_items:
            kind = str(item.get("type", "")).strip()
            key = str(item.get("id", "")).strip()
            if kind in _RECORD_KINDS and key and self.select_kind(kind, key, emit=False):
                restored = True
        if not restored:
            self.apply_request(check.request)
        self._update_clear_button()

    def clear_all(self, *, emit: bool = True) -> None:
        self.close_dropdowns()
        for selector in self.selectors:
            selector.clear_selection(emit=False)
        self.last_changed_index = None
        self.last_query_index = None
        self.last_focus_index = None
        self.last_unselected_index = None
        self.active_input_index = None
        self.open_dropdown_index = None
        self._update_clear_button()
        if emit:
            self.selection_changed.emit()

    def commit_pending_text(self, *, emit: bool = False) -> None:
        for selector in self.selectors:
            selector.commit_pending_selection(emit=emit)

    def selected_key(self, kind: str) -> str:
        option = self.selected_option(kind)
        return option.key if option is not None else ""

    def selected_values(self, kind: str) -> list[str]:
        return [option.key for option in self.selected_options() if option.kind == kind and option.key]

    def selected_option(self, kind: str) -> SelectorOption | None:
        for option in self.selected_options():
            if option.kind == kind:
                return option
        return None

    def selected_options(self) -> list[SelectorOption]:
        return [option for option in (selector.selected_option() for selector in self.selectors) if option is not None]

    def selected_slot_options(self) -> list[SelectorOption | None]:
        return [selector.selected_option() for selector in self.selectors]

    def slot_texts(self) -> list[str]:
        return [selector.query_text().strip() for selector in self.selectors]

    def selected_item_payloads(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "slotIndex": index,
                "id": option.key,
                "type": option.kind,
                "label": option.display,
                "subtitle": option.secondary,
            }
            for index, option in enumerate(self.selected_slot_options())
            if option is not None
        )

    def selection_signature(self) -> tuple[tuple[str, str], ...]:
        return tuple((option.kind, option.key) if option is not None else ("", "") for option in self.selected_slot_options())

    def index_for_kind(self, kind: str) -> int | None:
        for index, option in enumerate(self.selected_slot_options()):
            if option is not None and option.kind == kind:
                return index
        return None

    def first_empty_index(self) -> int | None:
        for index, selector in enumerate(self.selectors):
            if selector.is_empty():
                return index
        return None

    def mark_slot_changed(self, index: int) -> None:
        self.last_changed_index = index
        self.last_unselected_index = None
        self.last_query_index = None
        self.last_focus_index = None
        self.active_input_index = None
        self.open_dropdown_index = None
        self._update_clear_button()

    def option_at(self, index: int | None) -> SelectorOption | None:
        if index is None or index < 0 or index >= len(self.selectors):
            return None
        return self.selectors[index].selected_option()

    def query_at(self, index: int | None) -> str:
        if index is None or index < 0 or index >= len(self.selectors):
            return ""
        return self.selectors[index].query_text()

    def is_slot_empty(self, index: int) -> bool:
        return 0 <= index < len(self.selectors) and self.selectors[index].is_empty()

    def select_kind(self, kind: str, key: str, *, emit: bool = True) -> bool:
        if not str(key or "").strip():
            return False
        target = next((selector for selector in self.selectors if selector.selected_kind() == kind), None)
        if target is None:
            target = next((selector for selector in self.selectors if selector.is_empty()), self.selectors[-1])
        selected = target.select_key(key, kind=kind, emit=emit)
        if selected:
            self._update_clear_button()
        return selected

    def select_option_at(self, index: int, option: SelectorOption, *, emit: bool = True) -> bool:
        if index < 0 or index >= len(self.selectors):
            return False
        selector = self.selectors[index]
        selector.set_options(_dedupe_options([option, *selector.options()]))
        selected = selector.select_key(option.key, kind=option.kind, emit=emit)
        if selected:
            self._update_clear_button()
        return selected

    def clear_slot(self, index: int, *, emit: bool = True) -> None:
        if index < 0 or index >= len(self.selectors):
            return
        self.selectors[index].clear_selection(emit=emit)
        self._update_clear_button()

    def show_suggestions(self, index: int, options: list[SelectorOption]) -> None:
        if index < 0 or index >= len(self.selectors):
            return
        selector = self.selectors[index]
        selector.set_options(_dedupe_options(options), preserve_selection=False)
        self.show_dropdown(index)

    def show_dropdown(self, index: int) -> None:
        if not 0 <= index < len(self.selectors):
            return
        self.close_dropdowns(except_index=index)
        self.active_input_index = index
        self.open_dropdown_index = index
        self.selectors[index].show_dropdown()
        if not self.selectors[index].dropdown.isVisible():
            self.open_dropdown_index = None

    def close_dropdowns(self, *, except_index: int | None = None) -> None:
        for index, selector in enumerate(self.selectors):
            if except_index is not None and index == except_index:
                continue
            selector.close_dropdown()
        if except_index is None:
            self.active_input_index = None
            self.open_dropdown_index = None
        else:
            self.open_dropdown_index = except_index

    def _selector_changed(self, selector: FitCheckSelector) -> None:
        option = selector.selected_option()
        index = self.selectors.index(selector)
        self.last_changed_index = index
        self.last_unselected_index = index if option is None else None
        if option is not None and option.kind in {"tool", "machine", "eoat"}:
            for other in self.selectors:
                if other is not selector and other.selected_kind() == option.kind:
                    other.clear_selection(emit=False)
        self.close_dropdowns()
        self._update_clear_button()
        self.selection_changed.emit()

    def _selector_query_changed(self, selector: FitCheckSelector) -> None:
        index = self.selectors.index(selector)
        self.close_dropdowns(except_index=index)
        self.active_input_index = index
        self.last_query_index = index
        self.last_unselected_index = index if selector.selected_option() is None else None
        self._update_clear_button()
        self.query_changed.emit()

    def _selector_focused(self, selector: FitCheckSelector) -> None:
        index = self.selectors.index(selector)
        self.close_dropdowns(except_index=index)
        self.active_input_index = index
        self.open_dropdown_index = index
        self.last_focus_index = index
        self.focus_changed.emit()

    def _clear_button_clicked(self) -> None:
        self.clear_requested.emit()

    def _update_clear_button(self) -> None:
        has_content = any(selector.has_content() for selector in self.selectors)
        self.clear_button.setEnabled(has_content)

class FitCheckSelector(QWidget):
    selection_changed = Signal()
    query_changed = Signal()
    focus_requested = Signal()

    def __init__(
        self,
        label: str,
        placeholder: str,
        *,
        default_mode: str = "",
        show_empty_results: bool = True,
        empty_prompt: str = "Start typing to search...",
        parent=None,
    ):
        super().__init__(parent)
        self._options: list[SelectorOption] = []
        self._selected: SelectorOption | None = None
        self._updating = False
        self.default_mode = default_mode
        self.show_empty_results = show_empty_results
        self.empty_prompt = empty_prompt
        self.empty_results_text = ""
        self._kind = _selector_kind(label)
        self.setObjectName("FitCheckSelectorHost")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label = QLabel(label)
        self.label.setObjectName("FitCheckSelectorLabel")
        self.frame = GlassPanel(radius=6)
        self.frame.setFixedHeight(48)
        self.frame.set_glass(alpha=92, border_alpha=112, border_color=QColor("#2b86e7"), fill_color=QColor("#020b18"))
        frame_layout = QHBoxLayout(self.frame)
        frame_layout.setContentsMargins(11, 0, 8, 0)
        frame_layout.setSpacing(8)
        self.search_icon = SearchMiniIcon()
        self.input = QLineEdit()
        self.input.setObjectName("FitCheckSelectorInput")
        self.input.setPlaceholderText(placeholder)
        self.input.setClearButtonEnabled(True)
        set_placeholder_color(self.input, QColor(TEXT_PLACEHOLDER))
        self.input.textChanged.connect(self._text_changed)
        self.input.returnPressed.connect(self._select_first_match)
        self.frame.installEventFilter(self)
        self.search_icon.installEventFilter(self)
        self.input.installEventFilter(self)
        frame_layout.addWidget(self.search_icon)
        frame_layout.addWidget(self.input, 1)
        self.secondary = QLabel("")
        self.secondary.setObjectName("FitCheckSelectorSecondary")
        layout.addWidget(self.label)
        layout.addWidget(self.frame)
        layout.addWidget(self.secondary)
        self.dropdown = FitCheckDropdownPopup(self)
        self.dropdown.option_selected.connect(self._dropdown_selected)

    def set_options(self, options: list[SelectorOption], *, preserve_selection: bool = True, default_index: int | None = None) -> None:
        current_key = self._selected.key if self._selected is not None else ""
        current_kind = self._selected.kind if self._selected is not None else ""
        current_mode = self._selected.mode if self._selected is not None else self.default_mode
        self._options = list(options)
        preserved = False
        if preserve_selection:
            if current_key and self.select_key(current_key, kind=current_kind, emit=False) or current_mode and self.select_mode(current_mode, emit=False):
                preserved = True
        if not preserved and default_index is not None and 0 <= default_index < len(self._options):
            self._set_selected(self._options[default_index], emit=False)
        if self.dropdown.isVisible():
            self._show_dropdown()

    def selected_key(self) -> str:
        return self._selected.key if self._selected is not None else ""

    def selected_option(self) -> SelectorOption | None:
        return self._selected

    def query_text(self) -> str:
        return self.input.text()

    def options(self) -> list[SelectorOption]:
        return list(self._options)

    def selected_kind(self) -> str:
        return self._selected.kind if self._selected is not None else ""

    def is_empty(self) -> bool:
        return self._selected is None and not self.input.text().strip()

    def has_content(self) -> bool:
        return self._selected is not None or bool(self.input.text().strip())

    def clear_selection(self, *, emit: bool = True) -> None:
        self._set_selected(None, emit=emit)

    def set_query_text(self, text: str) -> None:
        self.input.setText(text)
        self.input.setCursorPosition(len(text))

    def set_empty_results_text(self, text: str) -> None:
        self.empty_results_text = str(text or "")

    def show_dropdown(self) -> None:
        self._show_dropdown()

    def close_dropdown(self) -> None:
        self.dropdown.reset_highlight()
        self.dropdown.hide()

    def commit_pending_selection(self, *, emit: bool = False) -> bool:
        if self._selected is not None:
            return False
        text = self.input.text()
        match = self._find_option(text)
        if match is None:
            matches, total = self._filtered_options(text, limit=2)
            if total == 1 and matches:
                match = matches[0]
        if match is None:
            return False
        self._set_selected(match, emit=emit)
        self.close_dropdown()
        return True

    def select_key(self, key: str, *, kind: str = "", emit: bool = True) -> bool:
        if not str(key or "").strip():
            self._set_selected(None, emit=emit)
            return False
        text = str(key).strip()
        folded = text.casefold()
        for option in self._options:
            if kind and option.kind != kind:
                continue
            if folded in {option.key.casefold(), option.display.casefold()}:
                self._set_selected(option, emit=emit)
                return True
            if kind and _normalized_key_for_kind(kind, text) == _normalized_key_for_kind(kind, option.key):
                self._set_selected(option, emit=emit)
                return True
        return False

    def select_mode(self, mode: str, *, emit: bool = True) -> bool:
        for option in self._options:
            if option.mode == mode:
                self._set_selected(option, emit=emit)
                return True
        return False

    def setFocus(self, reason: Qt.FocusReason = Qt.FocusReason.OtherFocusReason) -> None:  # noqa: N802
        self.input.setFocus(reason)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched in (self.frame, self.search_icon) and event.type() == QEvent.Type.MouseButtonPress:
            self.input.setFocus(Qt.FocusReason.MouseFocusReason)
            self.focus_requested.emit()
            return True
        if watched is self.input:
            if event.type() in {QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress}:
                self.focus_requested.emit()
            elif event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Escape:
                    self.close_dropdown()
                    return True
                if key in {Qt.Key.Key_Down, Qt.Key.Key_Up}:
                    if not self.dropdown.isVisible():
                        self.focus_requested.emit()
                    else:
                        self.dropdown.move_highlight(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self._select_first_match()
                    return True
        return super().eventFilter(watched, event)

    def _select_first_match(self) -> None:
        match = self.dropdown.highlighted_option() if self.dropdown.isVisible() else None
        match = match or self._find_option(self.input.text()) or self._first_contains(self.input.text())
        if match is not None:
            self._set_selected(match, emit=True)
            self.close_dropdown()

    def _text_changed(self, text: str) -> None:
        if self._updating:
            return
        if not text.strip():
            if self.default_mode:
                self.select_mode(self.default_mode, emit=True)
            else:
                self._set_selected(None, emit=True)
            self.query_changed.emit()
            return
        if self._selected is not None:
            self._selected = None
            self.secondary.setText("")
            self.selection_changed.emit()
        self.query_changed.emit()

    def _find_option(self, text: str) -> SelectorOption | None:
        folded = str(text or "").strip().casefold()
        if not folded:
            return None
        for option in self._options:
            if folded in {option.display.casefold(), option.key.casefold()}:
                return option
        return None

    def _first_contains(self, text: str) -> SelectorOption | None:
        matches, _total = self._filtered_options(text, limit=1)
        return matches[0] if matches else None

    def _filtered_options(self, text: str, *, limit: int = 7) -> tuple[list[SelectorOption], int]:
        folded = str(text or "").strip().casefold()
        if not folded:
            if not self.show_empty_results:
                return [], 0
            return self._options[:limit], len(self._options)
        scored: list[tuple[int, int, str, SelectorOption]] = []
        for index, option in enumerate(self._options):
            display = option.display.casefold()
            key = option.key.casefold()
            secondary = option.secondary.casefold()
            keywords = option.keywords.casefold()
            blob = " ".join((display, key, secondary, keywords))
            if folded == display or (key and folded == key):
                score = 0
            elif display.startswith(folded) or (key and key.startswith(folded)):
                score = 1
            elif secondary.startswith(folded):
                score = 2
            elif folded in blob:
                score = 3
            else:
                continue
            scored.append((score, index, display, option))
        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        matches = [option for _score, _index, _display, option in scored]
        return matches[:limit], len(matches)

    def _show_dropdown(self) -> None:
        if not self.isVisible():
            self.close_dropdown()
            return
        matches, total = self._filtered_options(self.input.text(), limit=7)
        empty_text = ""
        if not self.input.text().strip():
            empty_text = self.empty_results_text or (self.empty_prompt if not self.show_empty_results else "")
        self.dropdown.set_options(
            matches,
            query=self.input.text(),
            total_count=total,
            kind=self._kind,
            empty_text=empty_text,
        )
        width = max(320, self.frame.width())
        height = self.dropdown.preferred_height()
        container = self._dropdown_container()
        if container is not None and self.dropdown.parentWidget() is not container:
            self.dropdown.hide()
            self.dropdown.setParent(container)
        origin = self.frame.mapToGlobal(QPoint(0, self.frame.height() + 5))
        parent = self.dropdown.parentWidget()
        local_origin = parent.mapFromGlobal(origin) if parent is not None else origin
        self.dropdown.setGeometry(local_origin.x(), local_origin.y(), width, height)
        self.dropdown.show()
        self.dropdown.raise_()
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)
        QTimer.singleShot(0, self, lambda: self.input.setFocus(Qt.FocusReason.OtherFocusReason))

    def _dropdown_selected(self, option: SelectorOption) -> None:
        self._set_selected(option, emit=True)
        self.close_dropdown()

    def _dropdown_container(self) -> QWidget:
        widget = self.parentWidget()
        while widget is not None:
            if widget.objectName() in {"FitCheckBody", "PacketBuilderBody"}:
                return widget
            widget = widget.parentWidget()
        return self.window() or self

    def _set_selected(self, option: SelectorOption | None, *, emit: bool) -> None:
        same_selection = self._selected == option
        self._selected = option
        self._updating = True
        try:
            self.input.setText(option.display if option is not None else "")
            self.input.setCursorPosition(len(self.input.text()))
            self.secondary.setText(option.secondary if option is not None else "")
        finally:
            self._updating = False
        if emit and not same_selection:
            self.selection_changed.emit()


class FitCheckDropdownPopup(GlassPanel):
    option_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, radius=10)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.set_glass(alpha=236, border_alpha=150, border_color=QColor("#2b86e7"), fill_color=QColor("#020b18"), outer_glow_alpha=54)
        self._row_count = 0
        self._rows: list[FitCheckDropdownRow] = []
        self._highlight_index = -1
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)

    def set_options(
        self,
        options: list[SelectorOption],
        *,
        query: str,
        total_count: int,
        kind: str,
        empty_text: str = "",
    ) -> None:
        clear_layout(self._layout)
        self._rows = []
        self._highlight_index = -1
        self._row_count = len(options)
        if not options:
            empty = QLabel(empty_text or (f"No matches for \"{query.strip()}\"" if query.strip() else "No records available"))
            empty.setObjectName("FitCheckSelectorSecondary")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(54)
            self._layout.addWidget(empty)
            self._row_count = 1
            return
        grouped = _group_options(options)
        show_groups = len(grouped) > 1
        for group_kind, group_options in grouped:
            if show_groups:
                label = QLabel(_kind_label(group_kind))
                label.setObjectName("FitCheckDropdownGroup")
                self._layout.addWidget(label)
            for option in group_options:
                row = FitCheckDropdownRow(option, kind=option.kind or kind)
                row.pressed.connect(lambda option=option: self.option_selected.emit(option))
                self._rows.append(row)
                self._layout.addWidget(row)
        self._set_highlight(0)
        if total_count > len(options):
            more = QLabel(f"{total_count - len(options)} more match(es). Keep typing to narrow.")
            more.setObjectName("FitCheckSelectorSecondary")
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setMinimumHeight(24)
            self._layout.addWidget(more)

    def preferred_height(self) -> int:
        return min(430, 16 + self._row_count * 64 + max(0, self._layout.count() - self._row_count) * 30)

    def move_highlight(self, delta: int) -> None:
        if not self._rows:
            return
        self._set_highlight((self._highlight_index + delta) % len(self._rows))

    def highlighted_option(self) -> SelectorOption | None:
        if 0 <= self._highlight_index < len(self._rows):
            return self._rows[self._highlight_index].option
        return None

    def reset_highlight(self) -> None:
        self._highlight_index = -1
        for row in self._rows:
            row.set_highlighted(False)

    def _set_highlight(self, index: int) -> None:
        if not self._rows:
            self._highlight_index = -1
            return
        self._highlight_index = max(0, min(index, len(self._rows) - 1))
        for row_index, row in enumerate(self._rows):
            row.set_highlighted(row_index == self._highlight_index)


class FitCheckDropdownRow(QPushButton):
    def __init__(self, option: SelectorOption, *, kind: str, parent=None):
        super().__init__(parent)
        self.option = option
        self.kind = kind
        self._hovered = False
        self._highlighted = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(58)
        self.setMinimumWidth(260)
        self.setFlat(True)

    def set_highlighted(self, highlighted: bool) -> None:
        self._highlighted = highlighted
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        active = self._hovered or self._highlighted or self.hasFocus()
        fill = QColor("#09234a" if active else "#05152d")
        fill.setAlpha(220 if active else 174)
        border = QColor("#52aaff" if active else "#2d6aa5")
        border.setAlpha(190 if active else 110)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 7, 7)

        icon_name = _dropdown_icon(self.kind, self.option)
        icon = glyph_icon(icon_name, QColor("#d7e8ff"), 24)
        painter.drawPixmap(12, 17, icon.pixmap(24, 24))

        title_font = QFont(painter.font())
        title_font.setPointSize(9)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#f7fbff"))
        title_rect = QRect(48, 8, max(60, self.width() - 130), 22)
        title = painter.fontMetrics().elidedText(self.option.display or self.option.key or "Not Indexed", Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)

        subtitle_font = QFont(painter.font())
        subtitle_font.setPointSize(8)
        subtitle_font.setWeight(QFont.Weight.Normal)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#b8c7d9"))
        subtitle = self.option.secondary or self.option.keywords or self.option.key
        subtitle_rect = QRect(48, 30, max(60, self.width() - 72), 18)
        painter.drawText(
            subtitle_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            painter.fontMetrics().elidedText(subtitle, Qt.TextElideMode.ElideRight, subtitle_rect.width()),
        )

        pill = _dropdown_pill(self.kind, self.option)
        pill_font = QFont(painter.font())
        pill_font.setPointSize(7)
        pill_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(pill_font)
        pill_w = min(86, max(48, painter.fontMetrics().horizontalAdvance(pill) + 18))
        pill_rect = QRectF(self.width() - pill_w - 12, 14, pill_w, 26)
        pill_fill = QColor("#0a2b55")
        pill_fill.setAlpha(210)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pill_fill)
        painter.drawRoundedRect(pill_rect, 13, 13)
        painter.setPen(QColor("#83d8ff"))
        painter.drawText(pill_rect.toRect(), Qt.AlignmentFlag.AlignCenter, pill)


class FitCheckResultCard(GlassPanel):
    details_requested = Signal()
    open_eoat_requested = Signal()
    create_packet_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=120, border_alpha=86, border_color=QColor("#1f87ff"), fill_color=QColor("#061329"))
        self.status_icon = FitCheckLargeStatusIcon()
        self.headline = QLabel("")
        self.headline.setObjectName("FitCheckResultHeadline")
        self.message = QLabel("")
        self.message.setObjectName("FitCheckResultMessage")
        self.reco_label = QLabel("Recommended EOAT")
        self.reco_label.setObjectName("FitCheckRecommendedLabel")
        self.thumb = QLabel()
        self.thumb.setFixedSize(48, 58)
        self.thumb.setScaledContents(False)
        self.reco_id = QLabel("")
        self.reco_id.setObjectName("FitCheckRecommendedId")
        self.reco_type = QLabel("")
        self.reco_type.setObjectName("FitCheckRecommendedType")
        self.details = QPushButton("More Details")
        self.details.setObjectName("FitCheckSecondaryButton")
        self.details.setIcon(glyph_icon("status", QColor("#ffffff"), 16))
        self.details.setCursor(Qt.CursorShape.PointingHandCursor)
        self.details.setFixedHeight(40)
        self.details.setMinimumWidth(118)
        self.details.clicked.connect(self.details_requested.emit)
        self.create_packet = QPushButton("Create Packet")
        self.create_packet.setObjectName("FitCheckPrimaryButton")
        self.create_packet.setToolTip("Create Setup Packet")
        self.create_packet.setIcon(glyph_icon("doc", QColor("#ffffff"), 16))
        self.create_packet.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_packet.setFixedHeight(40)
        self.create_packet.setMinimumWidth(140)
        self.create_packet.setStyleSheet(FIT_CHECK_PRIMARY_ACTION_STYLE)
        self.create_packet.clicked.connect(self.create_packet_requested.emit)
        self.create_packet.hide()
        self.confidence_label = QLabel("Match:")
        self.confidence_label.setObjectName("FitCheckConfidence")
        self.confidence_value = QLabel("")
        self.confidence_value.setObjectName("FitCheckConfidenceValue")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 18, 28, 18)
        layout.setSpacing(20)
        layout.addWidget(self.status_icon)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(9)
        text_col.addStretch(1)
        text_col.addWidget(self.headline)
        text_col.addWidget(self.message)
        text_col.addStretch(1)
        layout.addLayout(text_col, 1)
        reco = QVBoxLayout()
        reco.setContentsMargins(0, 0, 0, 0)
        reco.setSpacing(7)
        reco.addWidget(self.reco_label)
        reco_row = QHBoxLayout()
        reco_row.setSpacing(12)
        reco_row.addWidget(self.thumb)
        reco_text = QVBoxLayout()
        reco_text.setSpacing(3)
        reco_text.addWidget(self.reco_id)
        reco_text.addWidget(self.reco_type)
        reco_row.addLayout(reco_text)
        reco.addLayout(reco_row)
        layout.addLayout(reco, 1)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(12)
        conf = QHBoxLayout()
        conf.setSpacing(6)
        dot = StatusDot()
        dot.set_ready(True)
        conf.addWidget(dot)
        conf.addWidget(self.confidence_label)
        conf.addWidget(self.confidence_value)
        conf.addStretch(1)
        right.addLayout(conf)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.addWidget(self.details)
        actions.addWidget(self.create_packet)
        right.addLayout(actions)
        right.addStretch(1)
        layout.addLayout(right)

    def set_result(self, result: FitCheckResult, *, selected_eoat_id: str = "", photo_path: str = "") -> None:
        self.status_icon.set_status(result.status)
        self.headline.setText(result.headline)
        self.headline.setStyleSheet(f"color: {_status_color(result.status).name()};")
        self.message.setText(result.message)
        eoat = result.recommended_eoat
        self.reco_label.setText("Recommended EOAT")
        if eoat is None:
            self.reco_id.setText("No confirmed EOAT found")
            self.reco_type.setText("")
            self.thumb.setPixmap(QPixmap())
        else:
            self.reco_id.setText(eoat.eoat_id)
            self.reco_type.setText(eoat.eoat_type or "EOAT")
            self.thumb.setPixmap(_thumb_pixmap(photo_path, QSize(48, 58), fallback="eoat"))
        self.confidence_value.setText(_match_label(result))
        can_create_packet = bool(selected_eoat_id and result.selected_tool and result.selected_machine and result.selected_eoat and is_valid_fit_result(result))
        self.create_packet.setVisible(can_create_packet)
        self.create_packet.setEnabled(can_create_packet)


class FitCheckPathRow(GlassPanel):
    record_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=104, border_alpha=78, border_color=QColor("#1f87ff"), fill_color=QColor("#061329"))
        self.cards = [FitCheckPathMiniCard(), FitCheckPathMiniCard(), FitCheckPathMiniCard()]
        self.links = [FitCheckConnector(), FitCheckConnector()]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(12)
        layout.addWidget(self.cards[0], 2)
        layout.addWidget(self.links[0], 1)
        layout.addWidget(self.cards[1], 2)
        layout.addWidget(self.links[1], 1)
        layout.addWidget(self.cards[2], 2)
        for card in self.cards:
            card.clicked.connect(lambda card=card: self._emit_record(card.entity_type, card.key))

    def set_result(self, result: FitCheckResult, selections: list[SelectorOption | None], *, photo_path: str = "") -> None:
        path_options = [option for option in selections if option is not None]
        for index, card in enumerate(self.cards):
            option = path_options[index] if index < len(path_options) else None
            if option is None:
                card.hide()
                continue
            card.show()
            card.set_record(
                _kind_display_name(option.kind),
                option.display,
                option.secondary,
                option.key,
                entity_type=option.kind,
                glyph=_glyph_for_kind(option.kind),
                photo_path=photo_path if option.kind == "eoat" else "",
                status=_flow_card_status(result, option),
            )
        for index, link in enumerate(self.links):
            left = path_options[index] if index < len(path_options) else None
            right = path_options[index + 1] if index + 1 < len(path_options) else None
            link.setVisible(left is not None and right is not None)
            link.set_status(_pair_status(result, left, right))

    def _emit_record(self, entity_type: str, key: str) -> None:
        if entity_type and key:
            self.record_requested.emit(entity_type, key)


class FitCheckPathMiniCard(GlassPanel):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=7)
        self.glyph = "grid"
        self.key = ""
        self.entity_type = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_glass(alpha=70, border_alpha=64, border_color=QColor("#286fa8"), fill_color=QColor("#07152b"))
        self.icon = QLabel()
        self.icon.setFixedSize(58, 58)
        self.label = QLabel("")
        self.label.setObjectName("FitCheckPathLabel")
        self.title = QLabel("")
        self.title.setObjectName("FitCheckPathTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("FitCheckPathSub")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        layout.addWidget(self.icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.label)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)

    def set_record(
        self,
        label: str,
        title: str,
        subtitle: str,
        key: str,
        *,
        entity_type: str = "",
        glyph: str = "grid",
        photo_path: str = "",
        status: str = "unknown",
    ) -> None:
        self.key = key
        self.entity_type = entity_type
        self.glyph = glyph
        self.label.setText(label)
        self.title.setText(title or "Not Indexed")
        self.subtitle.setText(subtitle or "Not Indexed")
        self.icon.setPixmap(_thumb_pixmap(photo_path, QSize(58, 58), fallback=self.glyph))
        self.set_glass(
            alpha=76,
            border_alpha=118 if status in {"conflict", "invalid"} else 72,
            border_color=_path_color("conflict" if status in {"conflict", "invalid"} else status),
            fill_color=QColor("#07152b"),
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class FitCheckConnector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = "unknown"
        self.setMinimumWidth(112)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = _path_color(self._status)
        mid = self.height() / 2
        line_pen = QPen(QColor(color.red(), color.green(), color.blue(), 150), 1.2)
        if self._status in {"unknown", "not_evaluated", "na"}:
            line_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(line_pen)
        painter.drawLine(4, mid, self.width() - 20, mid)
        painter.drawLine(self.width() - 28, mid - 6, self.width() - 18, mid)
        painter.drawLine(self.width() - 28, mid + 6, self.width() - 18, mid)
        painter.setPen(QPen(color, 1.8 if self._status in {"unknown", "not_evaluated", "na"} else 0))
        painter.setBrush(Qt.BrushStyle.NoBrush if self._status in {"unknown", "not_evaluated", "na"} else color)
        painter.drawEllipse(QRectF(self.width() / 2 - 13, mid - 13, 26, 26))
        painter.setPen(QPen(QColor("#02101f"), 2.2))
        if self._status == "conflict":
            painter.drawLine(QRectF(self.width() / 2 - 6, mid - 6, 12, 12).topLeft(), QRectF(self.width() / 2 - 6, mid - 6, 12, 12).bottomRight())
            painter.drawLine(QRectF(self.width() / 2 - 6, mid - 6, 12, 12).topRight(), QRectF(self.width() / 2 - 6, mid - 6, 12, 12).bottomLeft())
        elif self._status == "warning":
            painter.drawLine(self.width() / 2, mid - 7, self.width() / 2, mid + 2)
            painter.drawPoint(round(self.width() / 2), round(mid + 7))
        elif self._status in {"unknown", "not_evaluated", "na"}:
            painter.setPen(QPen(color, 2.1))
            painter.drawLine(self.width() / 2 - 6, mid, self.width() / 2 + 6, mid)
        else:
            painter.drawLine(self.width() / 2 - 6, mid, self.width() / 2 - 1, mid + 5)
            painter.drawLine(self.width() / 2 - 1, mid + 5, self.width() / 2 + 8, mid - 7)


class RequirementsCheckCard(GlassPanel):
    details_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=118, border_alpha=86, border_color=QColor("#1f87ff"), fill_color=QColor("#061329"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)
        title = QLabel("Requirements Check")
        title.setObjectName("FitCheckSectionTitle")
        layout.addWidget(title)
        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        layout.addWidget(self.rows, 1)
        self.button = QPushButton("View All Details")
        self.button.setObjectName("FitCheckSecondaryButton")
        self.button.setIcon(glyph_icon("status", QColor("#ffffff"), 16))
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.details_requested.emit)
        self.button.hide()

    def set_result(self, result: FitCheckResult) -> None:
        clear_layout(self.rows_layout)
        for requirement in result.requirements[:7]:
            self.rows_layout.addWidget(RequirementRow(requirement.label, requirement.value, requirement.status))
        self.rows_layout.addStretch(1)


class RequirementRow(QWidget):
    def __init__(self, label: str, value: str, status: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        icon = FitCheckSmallStatusIcon(status)
        name = QLabel(label)
        name.setObjectName("FitCheckRequirementName")
        result = QLabel(value)
        result.setObjectName("FitCheckRequirementValue")
        result.setStyleSheet(f"color: {_requirement_color(status).name()};")
        layout.addWidget(icon)
        layout.addWidget(name, 1)
        layout.addWidget(result)


class WarningsCard(GlassPanel):
    details_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=118, border_alpha=86, border_color=QColor("#1f87ff"), fill_color=QColor("#061329"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(14)
        title = QLabel("Warnings")
        title.setObjectName("FitCheckSectionTitle")
        layout.addWidget(title)
        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(16)
        layout.addWidget(self.rows, 1)
        self.button = QPushButton("See All (0)   >")
        self.button.setObjectName("FitCheckSecondaryButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.details_requested.emit)
        self.button.hide()

    def set_result(self, result: FitCheckResult) -> None:
        clear_layout(self.rows_layout)
        if not result.warnings:
            self.rows_layout.addWidget(WarningRow("No setup warnings found.", "This setup has no technician-facing warnings.", status="pass"))
        for warning in result.warnings[:4]:
            self.rows_layout.addWidget(WarningRow(warning.title, warning.message))
        self.rows_layout.addStretch(1)
        self.button.setText(f"See All ({len(result.warnings)})   >")


class WarningRow(QWidget):
    def __init__(self, title: str, message: str, *, status: str = "warning", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        icon = FitCheckSmallStatusIcon(status)
        text = QVBoxLayout()
        text.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("FitCheckWarningTitle")
        if status == "pass":
            title_label.setStyleSheet(f"color: {STATUS_SUCCESS.name()};")
        title_label.setWordWrap(True)
        message_label = QLabel(message)
        message_label.setObjectName("FitCheckWarningMessage")
        message_label.setWordWrap(True)
        text.addWidget(title_label)
        text.addWidget(message_label)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)


class AlternativesCard(GlassPanel):
    details_requested = Signal()
    machine_selected = Signal(object)
    eoat_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.active_tab = "machines"
        self.enabled_kinds: set[str] = {"machines", "eoats"}
        self.result: FitCheckResult | None = None
        self.set_glass(alpha=118, border_alpha=86, border_color=QColor("#1f87ff"), fill_color=QColor("#061329"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(10)
        title = QLabel("Alternative Options")
        title.setObjectName("FitCheckSectionTitle")
        layout.addWidget(title)
        tabs = QHBoxLayout()
        self.machines_tab = QPushButton("Other Machines")
        self.eoats_tab = QPushButton("Other EOATs")
        for button in (self.machines_tab, self.eoats_tab):
            button.setObjectName("FitCheckTabButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            tabs.addWidget(button)
        self.machines_tab.clicked.connect(lambda: self._set_tab("machines"))
        self.eoats_tab.clicked.connect(lambda: self._set_tab("eoats"))
        layout.addLayout(tabs)
        self.rows = QWidget()
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        layout.addWidget(self.rows, 1)
        self.button = QPushButton("View All Alternatives   >")
        self.button.setObjectName("FitCheckSecondaryButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.details_requested.emit)
        self.button.hide()
        self._sync_tabs()

    def set_result(self, result: FitCheckResult) -> None:
        self.result = result
        if self.active_tab not in self.enabled_kinds and self.enabled_kinds:
            self.active_tab = sorted(self.enabled_kinds)[0]
        self.machines_tab.setVisible("machines" in self.enabled_kinds)
        self.eoats_tab.setVisible("eoats" in self.enabled_kinds)
        self._sync_tabs()
        self._render_rows()

    def _set_tab(self, tab: str) -> None:
        if tab not in self.enabled_kinds:
            return
        self.active_tab = tab
        self._sync_tabs()
        self._render_rows()

    def _sync_tabs(self) -> None:
        self.machines_tab.setProperty("active", self.active_tab == "machines")
        self.eoats_tab.setProperty("active", self.active_tab == "eoats")
        for button in (self.machines_tab, self.eoats_tab):
            button.style().unpolish(button)
            button.style().polish(button)

    def _render_rows(self) -> None:
        clear_layout(self.rows_layout)
        if self.result is None:
            return
        if self.active_tab == "machines":
            for item in self.result.alternatives.machines[:5]:
                row = AlternativeMachineRow(item)
                row.clicked.connect(lambda _checked=False, item=item: self.machine_selected.emit(item.machine))
                self.rows_layout.addWidget(row)
        else:
            for item in self.result.alternatives.eoats[:5]:
                row = AlternativeEoatRow(item)
                row.clicked.connect(lambda _checked=False, item=item: self.eoat_selected.emit(item.eoat))
                self.rows_layout.addWidget(row)
        self.rows_layout.addStretch(1)


class AlternativeMachineRow(QPushButton):
    def __init__(self, item: FitCheckAlternativeMachine, parent=None):
        super().__init__(parent)
        self.setObjectName("FitCheckAltRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(glyph_icon("machine", QColor("#dfeeff"), 20).pixmap(20, 20))
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(machine_label(item.machine.machine))
        title.setObjectName("FitCheckAltTitle")
        sub = QLabel(item.machine.robot_model or item.machine.robot_type or "Robot type unknown")
        sub.setObjectName("FitCheckAltSub")
        text.addWidget(title)
        text.addWidget(sub)
        pill = QLabel(item.status_label)
        pill.setObjectName("FitCheckPill")
        pill.setProperty("tone", item.status)
        layout.addWidget(icon)
        layout.addLayout(text, 1)
        layout.addWidget(pill)


class AlternativeEoatRow(QPushButton):
    def __init__(self, item: FitCheckAlternativeEOAT, parent=None):
        super().__init__(parent)
        self.setObjectName("FitCheckAltRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(glyph_icon("eoat", QColor("#dfeeff"), 20).pixmap(20, 20))
        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(item.eoat.eoat_id)
        title.setObjectName("FitCheckAltTitle")
        sub = QLabel(item.eoat.eoat_type or "EOAT")
        sub.setObjectName("FitCheckAltSub")
        text.addWidget(title)
        text.addWidget(sub)
        pill = QLabel(item.status_label)
        pill.setObjectName("FitCheckPill")
        pill.setProperty("tone", item.status)
        layout.addWidget(icon)
        layout.addLayout(text, 1)
        layout.addWidget(pill)


class FitCheckRecentRow(GlassPanel):
    clicked = Signal()
    packet_requested = Signal(object)

    def __init__(self, check: RecentFitCheck, parent=None):
        super().__init__(parent, radius=8)
        self.check = check
        self._hovered = False
        self._pressed = False
        self.setObjectName("FitCheckRecentRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(90)
        self.setFixedHeight(92)
        self._apply_glass_state()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 13, 18, 13)
        layout.setSpacing(16)
        icon = QLabel()
        icon.setPixmap(glyph_icon("status", QColor("#dfeeff"), 22).pixmap(22, 22))
        icon.setFixedSize(26, 26)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(7)
        title = QLabel(check.headline or "Fit Check")
        title.setObjectName("FitCheckAltTitle")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sub = QLabel(_recent_summary_label(check))
        sub.setObjectName("FitCheckAltSub")
        sub.setWordWrap(False)
        sub.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setMinimumHeight(22)
        sub.setMinimumHeight(20)
        text.addWidget(title)
        text.addWidget(sub)
        meta_widget = QWidget()
        meta_widget.setMinimumWidth(220)
        meta_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        meta = QVBoxLayout(meta_widget)
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(7)
        time_label = QLabel(_recent_time_label(check.timestamp))
        time_label.setObjectName("FitCheckAltSub")
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_label.setMinimumHeight(20)
        pill = QLabel(_recent_result_label(check))
        pill.setObjectName("FitCheckPill")
        pill.setProperty("tone", _recent_status_tone(check.status))
        pill.setMinimumHeight(24)
        meta.addWidget(time_label)
        meta.addWidget(pill, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(icon)
        layout.addLayout(text, 1)
        layout.addWidget(meta_widget, 0)
        self.packet_button = QPushButton("Create Packet")
        self.packet_button.setObjectName("FitCheckSecondaryButton")
        self.packet_button.setIcon(glyph_icon("doc", QColor("#ffffff"), 16))
        self.packet_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.packet_button.setFixedHeight(34)
        can_packet = bool(check.request.tool_id and check.request.machine_id and check.request.eoat_id and check.status in {"compatible", "warning"})
        self.packet_button.setVisible(can_packet)
        self.packet_button.setEnabled(can_packet)
        self.packet_button.clicked.connect(lambda _checked=False: self.packet_requested.emit(self.check))
        layout.addWidget(self.packet_button, 0)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._apply_glass_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._pressed = False
        self._apply_glass_state()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._apply_glass_state()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self._apply_glass_state()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _apply_glass_state(self) -> None:
        active = self._hovered or self._pressed or self.hasFocus()
        self.set_glass(
            alpha=170 if active else 126,
            border_alpha=170 if active else 104,
            border_color=QColor("#52aaff" if active else "#2d6aa5"),
            fill_color=QColor("#09234a" if active else "#05152d"),
            outer_glow_alpha=36 if active else 0,
        )


class SetupPacketCheckBox(QCheckBox):
    def __init__(self, label: str, *, optional: bool = False, parent=None):
        super().__init__(label, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(28)
        self.setProperty("optional", bool(optional))
        self.setStyleSheet(
            """
            QCheckBox {
                color: #dce9f7;
                background: transparent;
                spacing: 9px;
                padding: 2px 6px;
                font-size: 9pt;
                font-weight: 600;
                min-height: 24px;
            }
            QCheckBox[optional="true"] {
                color: #c0ccdc;
            }
            QCheckBox:hover, QCheckBox:focus {
                color: #f0f7ff;
                background: rgba(8, 31, 64, 72);
                border-radius: 6px;
            }
            QCheckBox:checked {
                color: #f0f7ff;
            }
            QCheckBox:disabled {
                color: #8798ad;
            }
            """
        )


class SetupPacketRadioButton(QRadioButton):
    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(24)
        self.setStyleSheet(
            """
            QRadioButton {
                color: #dce9f7;
                background: transparent;
                spacing: 9px;
                font-size: 9pt;
                font-weight: 650;
                min-height: 24px;
            }
            QRadioButton:checked {
                color: #f4f9ff;
            }
            QRadioButton:hover, QRadioButton:focus {
                color: #f4f9ff;
            }
            """
        )


class SetupPacketFormatChoiceFrame(QFrame):
    def __init__(self, radio: QRadioButton, parent=None):
        super().__init__(parent)
        self.radio = radio
        self.setObjectName("SetupPacketFormatChoice")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
            event.accept()
            return
        super().mousePressEvent(event)


class SetupPacketOverlay(AnimatedGlassPanel):
    close_requested = Signal()
    preview_requested = Signal()
    generate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=16)
        self.setup = PacketSetup()
        self.result: FitCheckResult | None = None
        self.set_glass(alpha=240, border_alpha=104, border_color=QColor("#658fb8"), fill_color=QColor("#020b1b"), outer_glow_alpha=38)
        self.setStyleSheet(
            """
            QLabel#SetupPacketTitle { color: #f6fbff; font-size: 17pt; font-weight: 780; }
            QLabel#SetupPacketSubtitle { color: #c0ccdc; font-size: 9.4pt; font-weight: 500; }
            QLabel#SetupPacketSectionTitle { color: #e4eefb; font-size: 9.1pt; font-weight: 760; padding-bottom: 2px; }
            QLabel#SetupPacketGroupTitle { color: #78bff0; font-size: 7.7pt; font-weight: 760; padding-top: 4px; }
            QLabel#SetupPacketLabel { color: #a9b8ca; font-size: 8.15pt; font-weight: 700; }
            QLabel#SetupPacketValue { color: #eaf3ff; font-size: 8.9pt; font-weight: 620; }
            QLabel#SetupPacketHint, QLabel#SetupPacketDescription { color: #c0ccdc; font-size: 8.35pt; }
            QFrame#SetupPacketSection {
                background: rgba(5, 18, 39, 118);
                border: 1px solid rgba(91, 132, 178, 36);
                border-radius: 8px;
            }
            QFrame#SetupPacketFormatChoice {
                background: rgba(8, 27, 55, 70);
                border: 1px solid rgba(75, 128, 188, 28);
                border-radius: 7px;
            }
            QFrame#SetupPacketFormatChoice:hover {
                background: rgba(10, 36, 72, 94);
                border: 1px solid rgba(87, 156, 224, 58);
            }
            QFrame#SetupPacketFormatChoice[selected="true"] {
                background: rgba(10, 42, 86, 118);
                border: 1px solid rgba(83, 158, 233, 82);
            }
            QFrame#SetupPacketNote {
                background: rgba(7, 26, 54, 74);
                border: 1px solid rgba(87, 142, 204, 28);
                border-radius: 7px;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        title = QLabel("Setup Packet")
        title.setObjectName("SetupPacketTitle")
        subtitle = QLabel("Generate a setup reference packet from this Fit Check.")
        subtitle.setObjectName("SetupPacketSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        close = CloseIconButton(size=34)
        close.clicked.connect(self.close_requested.emit)
        header.addLayout(title_col, 1)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.summary_section, summary_layout = self._section("Selected Fit Check Setup", compact=True)
        summary_grid = QGridLayout()
        summary_grid.setContentsMargins(0, 0, 0, 0)
        summary_grid.setHorizontalSpacing(16)
        summary_grid.setVerticalSpacing(4)
        self.tool_value = self._grid_value(summary_grid, 0, 0, "Tool", "")
        self.machine_value = self._grid_value(summary_grid, 1, 0, "Machine", "")
        self.eoat_value = self._grid_value(summary_grid, 2, 0, "EOAT", "")
        self.status_value = self._grid_value(summary_grid, 0, 2, "Status", "")
        self.match_value = self._grid_value(summary_grid, 1, 2, "Match", "")
        summary_grid.setColumnStretch(1, 2)
        summary_grid.setColumnStretch(3, 1)
        summary_layout.addLayout(summary_grid)
        layout.addWidget(self.summary_section)

        body = QHBoxLayout()
        body.setSpacing(16)
        self.section_checks: dict[str, QCheckBox] = {}
        content_section, content_layout = self._section("Included Sections")
        content_layout.addWidget(self._group_title("Core Sections"))
        for key, label, checked in (
            ("setup_summary", "Setup summary", True),
            ("compatibility_result", "Compatibility result", True),
            ("requirements_check", "Requirements check", True),
            ("warnings", "Warnings", True),
            ("eoat_photo", "EOAT photo", True),
            ("setup_checklist", "Setup checklist", True),
        ):
            check = self._check(label, checked)
            self.section_checks[key] = check
            content_layout.addWidget(check)
        content_layout.addSpacing(4)
        content_layout.addWidget(self._group_title("Optional Sections"))
        for key, label, checked in (
            ("alternatives", "Alternatives", False),
            ("detailed_record_information", "Detailed record information", False),
            ("related_records", "Related machines/tools", False),
            ("extra_notes", "Extra notes section", False),
        ):
            check = self._check(label, checked, optional=True)
            self.section_checks[key] = check
            content_layout.addWidget(check)
        content_layout.addStretch(1)
        body.addWidget(content_section, 11)

        format_section, format_layout = self._section("Packet Format")
        self.one_page_radio = SetupPacketRadioButton("One-page summary")
        self.detailed_radio = SetupPacketRadioButton("Detailed packet")
        self.one_page_radio.setChecked(True)
        self.format_group = QButtonGroup(self)
        self.format_group.setExclusive(True)
        self.format_group.addButton(self.one_page_radio)
        self.format_group.addButton(self.detailed_radio)
        self.one_page_frame = self._format_choice(self.one_page_radio, "Best for quick setup reference.")
        self.detailed_frame = self._format_choice(self.detailed_radio, "Includes extra context and supporting details.")
        self.one_page_radio.toggled.connect(self._sync_format_choice_state)
        self.detailed_radio.toggled.connect(self._sync_format_choice_state)
        format_layout.addWidget(self.one_page_frame)
        format_layout.addWidget(self.detailed_frame)
        self._sync_format_choice_state()
        format_layout.addSpacing(8)
        note = QFrame()
        note.setObjectName("SetupPacketNote")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(12, 8, 12, 8)
        note_layout.setSpacing(0)
        hint = QLabel("Preview opens a temporary PDF. Generate creates the packet and opens it in the in-app viewer.")
        hint.setObjectName("SetupPacketHint")
        hint.setWordWrap(True)
        note_layout.addWidget(hint)
        format_layout.addWidget(note)
        format_layout.addStretch(1)
        body.addWidget(format_section, 10)
        layout.addLayout(body)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.setContentsMargins(0, 2, 0, 0)
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("FitCheckSecondaryButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.close_requested.emit)
        self.preview_button = QPushButton("Preview PDF")
        self.preview_button.setObjectName("FitCheckSecondaryButton")
        self.preview_button.setIcon(glyph_icon("target", QColor("#ffffff"), 16))
        self.preview_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_button.clicked.connect(self.preview_requested.emit)
        self.generate_button = QPushButton("Generate PDF")
        self.generate_button.setObjectName("FitCheckPrimaryButton")
        self.generate_button.setIcon(glyph_icon("doc", QColor("#ffffff"), 16))
        self.generate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generate_button.setStyleSheet(FIT_CHECK_PRIMARY_ACTION_STYLE)
        self.generate_button.clicked.connect(self.generate_requested.emit)
        for button in (self.cancel_button, self.preview_button, self.generate_button):
            button.setFixedHeight(42)
            button.setMinimumWidth(124)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.generate_button)
        layout.addLayout(actions)

    def animate_open(self, rect: QRect) -> None:
        self._opacity.setEnabled(True)
        super().animate_open(self._integer_rect(rect))

    def animate_close(self, rect: QRect) -> None:
        self._opacity.setEnabled(True)
        self._opacity.setOpacity(1.0)
        super().animate_close(self._integer_rect(rect))

    def _animation_finished(self) -> None:
        super()._animation_finished()
        if self.isVisible() and not self._closing:
            self._opacity.setEnabled(False)

    def set_setup(self, setup: PacketSetup, result: FitCheckResult, *, bundle: AtlasDataBundle | None = None) -> None:
        self.setup = setup.normalized()
        self.result = result
        tool = result.selected_tool
        machine = result.selected_machine
        eoat = result.selected_eoat or result.recommended_eoat
        self.tool_value.setText(f"{self.setup.tool_id} - {getattr(tool, 'part_description', '') or getattr(tool, 'label', '') or 'Not listed'}")
        self.machine_value.setText(f"{machine_label(self.setup.machine_id)} - {getattr(machine, 'robot_type', '') or getattr(machine, 'robot_model', '') or 'Robot type unknown'}")
        self.eoat_value.setText(f"{self.setup.eoat_id} - {getattr(eoat, 'eoat_type', '') or 'EOAT'}")
        self.status_value.setText(_status_display(result.status))
        self.match_value.setText(_match_label(result))

    def selected_options(self) -> dict[str, object]:
        values = {key: check.isChecked() for key, check in self.section_checks.items()}
        values["format"] = "detailed" if self.detailed_radio.isChecked() else "one_page"
        return values

    def _integer_rect(self, rect: QRect) -> QRect:
        return QRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))

    def _section(self, title: str, *, compact: bool = False) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("SetupPacketSection")
        section_layout = QVBoxLayout(frame)
        if compact:
            section_layout.setContentsMargins(16, 12, 16, 12)
        else:
            section_layout.setContentsMargins(16, 12, 16, 16)
        section_layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("SetupPacketSectionTitle")
        section_layout.addWidget(label)
        return frame, section_layout

    def _grid_value(self, layout: QGridLayout, row: int, column: int, label: str, value: str) -> QLabel:
        key = QLabel(label)
        key.setObjectName("SetupPacketLabel")
        val = QLabel(value)
        val.setObjectName("SetupPacketValue")
        val.setWordWrap(True)
        layout.addWidget(key, row, column)
        layout.addWidget(val, row, column + 1)
        return val

    def _value_row(self, layout: QVBoxLayout, label: str, value: str) -> QLabel:
        row = QHBoxLayout()
        row.setSpacing(12)
        key = QLabel(label)
        key.setObjectName("SetupPacketLabel")
        key.setFixedWidth(86)
        val = QLabel(value)
        val.setObjectName("SetupPacketValue")
        val.setWordWrap(True)
        row.addWidget(key)
        row.addWidget(val, 1)
        layout.addLayout(row)
        return val

    def _group_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SetupPacketGroupTitle")
        return label

    def _format_choice(self, radio: QRadioButton, description: str) -> QFrame:
        frame = SetupPacketFormatChoiceFrame(radio)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        desc = QLabel(description)
        desc.setObjectName("SetupPacketDescription")
        desc.setWordWrap(True)
        layout.addWidget(radio)
        layout.addWidget(desc)
        return frame

    def _sync_format_choice_state(self) -> None:
        for frame, selected in (
            (getattr(self, "one_page_frame", None), self.one_page_radio.isChecked()),
            (getattr(self, "detailed_frame", None), self.detailed_radio.isChecked()),
        ):
            if frame is None:
                continue
            frame.setProperty("selected", bool(selected))
            frame.style().unpolish(frame)
            frame.style().polish(frame)

    def _check(self, label: str, checked: bool, *, optional: bool = False) -> QCheckBox:
        widget = SetupPacketCheckBox(label, optional=optional)
        widget.setChecked(bool(checked))
        widget.setProperty("optional", bool(optional))
        return widget


class FitCheckDetailsOverlay(AnimatedGlassPanel):
    close_requested = Signal()
    recent_selected = Signal(object)
    recent_packet_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, radius=16)
        self.set_glass(alpha=236, border_alpha=184, border_color=QColor("#8cc4ff"), fill_color=QColor("#020b1b"), outer_glow_alpha=78)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        self.title = QLabel("Fit Check Details")
        self.title.setObjectName("FitCheckOverlayTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("FitCheckOverlaySubtitle")
        title_block.addWidget(self.title)
        title_block.addWidget(self.subtitle)
        close = CloseIconButton(size=34)
        close.clicked.connect(self.close_requested.emit)
        header.addLayout(title_block)
        header.addStretch(1)
        header.addWidget(close)
        layout.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("FitCheckScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("FitCheckOverlayBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)

    def set_result(self, result: FitCheckResult | None, *, focus: str = "details") -> None:
        self.title.setText("Fit Check Details")
        self.subtitle.setText("Review the selected setup, requirements, warnings, and alternatives.")
        clear_layout(self.body_layout)
        if result is None:
            self._add_section("Fit Check Details", ["No Fit Check has been run in this session."])
            self.body_layout.addStretch(1)
            return
        self._add_section(
            "Decision Summary",
            [
                f"Status: {result.headline}",
                result.message,
                f"Match: {_match_label(result)}",
                f"Tool: {getattr(result.selected_tool, 'tool', '') or 'Not selected'}",
                f"Machine: {machine_label(getattr(result.selected_machine, 'machine', '')) if result.selected_machine is not None else 'Not selected'}",
                f"Selected EOAT: {getattr(result.selected_eoat, 'eoat_id', '') or 'Not selected'}",
                f"Recommended EOAT: {getattr(result.recommended_eoat, 'eoat_id', '') or 'No confirmed EOAT found'}",
            ],
        )
        self._add_section(
            "Path Verification",
            [
                f"Tool -> EOAT: {result.tool_to_eoat.status.title()} - {result.tool_to_eoat.message}",
                f"EOAT -> Machine: {result.eoat_to_machine.status.title()} - {result.eoat_to_machine.message}",
            ],
        )
        self._add_section(
            "Requirements",
            [
                f"{item.label}: {item.value} ({item.status.title()})"
                + (f" - {item.explanation}" if item.explanation else "")
                for item in result.requirements
            ],
        )
        self._add_section(
            "Warnings",
            [f"{item.severity.title()} - {item.title}: {item.message}" for item in result.warnings]
            or ["No setup warnings found."],
        )
        machine_lines = [
            f"{item.machine.label or machine_label(item.machine.machine)}: {item.status_label}"
            + (f" - {item.reason}" if item.reason else "")
            for item in result.alternatives.machines
        ]
        eoat_lines = [
            f"{item.eoat.eoat_id}: {item.status_label}"
            + (f" - {item.reason}" if item.reason else "")
            for item in result.alternatives.eoats
        ]
        self._add_section("Alternative Machines", machine_lines or ["No alternative machines indexed."])
        self._add_section("Alternative EOATs", eoat_lines or ["No alternative EOATs indexed."])
        details = result.details
        self._add_section("Tool Details", _dict_lines(details.tool_details))
        self._add_section("EOAT Details", _dict_lines(details.eoat_details))
        self._add_section("Machine Details", _dict_lines(details.machine_details))
        self._add_section("Air / Pneumatic Requirements", _dict_lines(details.air_details))
        self._add_section("Sensor Requirements", _dict_lines(details.sensor_details))
        self._add_section("Audit & Documentation", _dict_lines(details.documentation_details))
        self._add_section("Match Explanation", list(details.confidence_explanation))
        self.body_layout.addStretch(1)

    def set_recent_checks(self, checks: list[RecentFitCheck]) -> None:
        self.title.setText("Recent Fit Checks")
        self.subtitle.setText("Select a previous check to reload it.")
        clear_layout(self.body_layout)
        recent = sorted(checks, key=lambda item: item.timestamp, reverse=True)[:15]
        if not recent:
            self._add_section("No recent fit checks yet.", ["Run a check and it will appear here."])
            self.body_layout.addStretch(1)
            return
        intro = QLabel("Newest checks are shown first. Selecting a row fills the setup items and runs Fit Check again.")
        intro.setObjectName("FitCheckOverlayText")
        intro.setWordWrap(True)
        self.body_layout.addWidget(intro)
        for check in recent:
            row = FitCheckRecentRow(check)
            row.clicked.connect(lambda _checked=False, check=check: self.recent_selected.emit(check))
            row.packet_requested.connect(self.recent_packet_requested.emit)
            self.body_layout.addWidget(row)
        self.body_layout.addStretch(1)

    def _add_section(self, title: str, lines: list[str]) -> None:
        card = GlassPanel(radius=10)
        card.set_glass(alpha=118, border_alpha=88, border_color=QColor("#2b86e7"), fill_color=QColor("#061329"))
        section_layout = QVBoxLayout(card)
        section_layout.setContentsMargins(18, 14, 18, 16)
        section_layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("FitCheckOverlaySection")
        section_layout.addWidget(label)
        for line in lines:
            if not str(line or "").strip():
                continue
            text = QLabel(str(line))
            text.setObjectName("FitCheckOverlayText")
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            section_layout.addWidget(text)
        self.body_layout.addWidget(card)


class FitCheckScrim(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 5, 13, 112))

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()


class FitCheckLargeStatusIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = "insufficient_data"
        self.setFixedSize(74, 74)

    def set_status(self, status: str) -> None:
        self.status = status
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = _status_color(self.status)
        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 28))
        painter.setPen(QPen(color, 2.4))
        painter.drawEllipse(rect)
        painter.setPen(QPen(color, 3.4))
        if self.status in {"not_compatible", "invalid_input"}:
            painter.drawLine(27, 27, 47, 47)
            painter.drawLine(47, 27, 27, 47)
        elif self.status in {"warning", "unknown"}:
            painter.drawLine(37, 23, 37, 43)
            painter.drawPoint(37, 51)
        elif self.status == "insufficient_data":
            painter.drawLine(37, 33, 37, 51)
            painter.drawPoint(37, 24)
        else:
            painter.drawLine(24, 39, 33, 48)
            painter.drawLine(33, 48, 51, 28)


class FitCheckSmallStatusIcon(QWidget):
    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self.status = status
        self.setFixedSize(18, 18)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = _requirement_color(self.status)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1, 1, 16, 16))
        painter.setPen(QPen(QColor("#02101f"), 1.6))
        if self.status in {"fail", "conflict", "critical"}:
            painter.drawLine(6, 6, 12, 12)
            painter.drawLine(12, 6, 6, 12)
        elif self.status in {"warning", "unknown"}:
            painter.drawLine(9, 5, 9, 10)
            painter.drawPoint(9, 13)
        elif self.status == "na":
            painter.drawLine(6, 9, 12, 9)
        else:
            painter.drawLine(5, 9, 8, 12)
            painter.drawLine(8, 12, 13, 6)


class FitCheckStatusLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dot = StatusDot(self)
        self.label = QLabel("Data loading...", self)
        self.label.setObjectName("MinimalistStatusText")

    def set_status(self, text: str, *, ready: bool) -> None:
        self.label.setText(text)
        self.dot.set_ready(ready)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.dot.setGeometry(0, 8, 14, 14)
        self.label.setGeometry(24, 1, self.width() - 24, 26)


def _status_color(status: str) -> QColor:
    if status == "compatible":
        return STATUS_SUCCESS
    if status == "warning":
        return STATUS_WARNING
    if status in {"not_compatible", "invalid_input"}:
        return STATUS_ERROR
    return STATUS_UNKNOWN


def _recent_time_label(value: datetime) -> str:
    time_text = value.strftime("%I:%M %p").lstrip("0")
    if value.date() == datetime.now().date():
        return f"Today, {time_text}"
    return f"{value.strftime('%b')} {value.day}, {value.year} {time_text}"


def _recent_status_tone(status: str) -> str:
    if status == "compatible":
        return "best"
    if status == "warning":
        return "verify"
    if status in {"not_compatible", "invalid_input"}:
        return "incompatible"
    if status in {"unknown", "insufficient_data"}:
        return "missing_data"
    return "available"


def _recent_summary_label(check: RecentFitCheck) -> str:
    if check.status == "insufficient_data":
        return check.summary or "Partial check - select more items"
    return check.summary or "Reload this Fit Check."


def _recent_result_label(check: RecentFitCheck) -> str:
    status = _status_display(check.status)
    match = check.match_level or _match_text_from_confidence(check.confidence)
    if check.status in {"insufficient_data", "not_compatible", "invalid_input", "unknown"}:
        return status
    return f"{status} - {match} match"


def _status_display(status: str) -> str:
    return {
        "compatible": "Compatible",
        "warning": "Compatible with setup warnings",
        "not_compatible": "Not Compatible",
        "invalid_input": "Invalid Input",
        "unknown": "Needs Review",
        "insufficient_data": "Partial Check",
    }.get(status, "Partial Check")


def _match_text_from_confidence(confidence: str) -> str:
    return {
        "high": "Direct",
        "medium": "Strong",
        "low": "Partial",
        "unknown": "Unknown",
    }.get(str(confidence or "").casefold(), "Unknown")


def _match_label(result: FitCheckResult) -> str:
    if result.status == "not_compatible":
        return "Not Compatible"
    if result.status == "invalid_input":
        return "Invalid Input"
    if result.status == "insufficient_data":
        return "Incomplete"
    if result.status == "unknown":
        return "Needs Review"
    if result.compatibility.full_setup == "pass":
        return "Confirmed"
    if result.confidence == "low" and any(segment.status == "unknown" for segment in (result.tool_to_eoat, result.eoat_to_machine)):
        return "Inferred"
    return _match_text_from_confidence(result.confidence)


def _kind_display_name(kind: str) -> str:
    return {"tool": "Tool", "machine": "Machine", "eoat": "EOAT"}.get(kind, "Setup Item")


def _glyph_for_kind(kind: str) -> str:
    return {"tool": "grid", "machine": "machine", "eoat": "eoat"}.get(kind, "grid")


def _pair_status(result: FitCheckResult, left: SelectorOption | None, right: SelectorOption | None) -> str:
    if left is None or right is None or left.kind == right.kind:
        return "unknown"
    kinds = {left.kind, right.kind}
    if kinds == {"tool", "eoat"}:
        return result.tool_to_eoat.status
    if kinds == {"machine", "eoat"}:
        return result.eoat_to_machine.status
    if kinds == {"tool", "machine"}:
        requirement = next((item for item in result.requirements if item.id == "machine_compatibility"), None)
        if requirement is None:
            return "unknown"
        return {
            "pass": "confirmed",
            "warning": "warning",
            "fail": "conflict",
            "unknown": "unknown",
            "na": "unknown",
        }.get(requirement.status, "unknown")
    return "unknown"


def _flow_card_status(result: FitCheckResult, option: SelectorOption) -> str:
    if option.kind == "tool" and result.input_completeness.has_tool and not result.validity.tool_exists:
        return "invalid"
    if option.kind == "machine" and result.input_completeness.has_machine and not result.validity.machine_exists:
        return "invalid"
    if option.kind == "eoat" and result.input_completeness.has_eoat and not result.validity.eoat_exists:
        return "invalid"
    if option.kind == "eoat" and (result.tool_to_eoat.status == "conflict" or result.eoat_to_machine.status == "conflict"):
        return "conflict"
    if option.kind in {"tool", "machine"} and result.compatibility.tool_machine == "fail":
        return "conflict"
    if result.compatibility.full_setup == "pass":
        return "confirmed"
    if result.status == "warning":
        return "warning"
    return "unknown"


def _flow_raw_secondary(result: FitCheckResult, kind: str) -> str:
    if result.status == "invalid_input":
        return f"Invalid {_kind_display_name(kind)}"
    return "Entered value"


def _path_color(status: str) -> QColor:
    return {
        "confirmed": STATUS_SUCCESS,
        "pass": STATUS_SUCCESS,
        "warning": STATUS_WARNING,
        "conflict": STATUS_ERROR,
        "fail": STATUS_ERROR,
        "invalid": STATUS_ERROR,
        "unknown": STATUS_UNKNOWN,
        "not_evaluated": STATUS_UNKNOWN,
        "na": STATUS_UNKNOWN,
    }.get(status, STATUS_UNKNOWN)


def _requirement_color(status: str) -> QColor:
    return {
        "pass": STATUS_SUCCESS,
        "warning": STATUS_WARNING,
        "fail": STATUS_ERROR,
        "unknown": STATUS_UNKNOWN,
        "na": STATUS_UNKNOWN,
        "confirmed": STATUS_SUCCESS,
        "conflict": STATUS_ERROR,
        "critical": STATUS_ERROR,
    }.get(status, STATUS_UNKNOWN)


def _selector_kind(label: str) -> str:
    folded = str(label or "").casefold()
    if "machine" in folded:
        return "machine"
    if "eoat" in folded:
        return "eoat"
    return "tool"


def _dropdown_icon(kind: str, option: SelectorOption) -> str:
    if option.mode in {"auto", "current"}:
        return "status"
    if kind == "machine":
        return "machine"
    if kind == "eoat":
        return "eoat"
    return "grid"


def _dropdown_pill(kind: str, option: SelectorOption) -> str:
    if option.mode == "auto":
        return "AUTO"
    if option.mode == "current":
        return "CURRENT"
    if kind == "machine":
        return "MACHINE"
    if kind == "eoat":
        return "EOAT"
    return "TOOL"


def _group_options(options: list[SelectorOption]) -> list[tuple[str, list[SelectorOption]]]:
    grouped: list[tuple[str, list[SelectorOption]]] = []
    for kind in _RECORD_KINDS:
        group = [option for option in options if option.kind == kind]
        if group:
            grouped.append((kind, group))
    extras = [option for option in options if option.kind not in _RECORD_KINDS]
    if extras:
        grouped.append(("record", extras))
    return grouped


def _kind_label(kind: str) -> str:
    return {"tool": "TOOLS", "machine": "MACHINES", "eoat": "EOATS"}.get(kind, "RECORDS")


def _normalized_key_for_kind(kind: str, value: str) -> str:
    if kind == "tool":
        return normalized_tool_key(value)
    if kind == "machine":
        return normalized_machine_key(value)
    if kind == "eoat":
        return normalized_eoat_key(value)
    return str(value or "").strip().casefold()


def _same_option(left: SelectorOption, right: SelectorOption) -> bool:
    return left.kind == right.kind and left.key.casefold() == right.key.casefold() and left.mode == right.mode


def _same_record_option(left: SelectorOption, right: SelectorOption) -> bool:
    return left.kind == right.kind and left.key.casefold() == right.key.casefold()


def _dedupe_options(options: list[SelectorOption]) -> list[SelectorOption]:
    deduped: list[SelectorOption] = []
    seen: set[tuple[str, str, str]] = set()
    for option in options:
        key = (option.kind, option.mode, option.key.casefold() or option.display.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(option)
    return deduped


def _linked(
    left_key: str,
    left_values: tuple[str, ...] | list[str],
    right_key: str,
    right_values: tuple[str, ...] | list[str],
    *,
    left_normalizer: Callable[[str], str],
    right_normalizer: Callable[[str], str],
) -> bool:
    left_links = {left_normalizer(value) for value in left_values or () if left_normalizer(value)}
    right_links = {right_normalizer(value) for value in right_values or () if right_normalizer(value)}
    left_match = bool(left_links) and left_key in left_links
    right_match = bool(right_links) and right_key in right_links
    if left_match or right_match:
        return True
    if not left_links and not right_links:
        return False
    return False


def _thumb_pixmap(path: str, size: QSize, *, fallback: str) -> QPixmap:
    if path:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            return QPixmap.fromImage(image).scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    return glyph_icon(fallback, QColor("#d7e8ff"), min(size.width(), size.height())).pixmap(size)


def _dict_lines(values: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in values.items():
        if value is None or value == "" or value == () or value == []:
            continue
        label = str(key).replace("_", " ").title()
        if isinstance(value, tuple | list):
            text = ", ".join(str(item) for item in value if str(item or "").strip()) or "Not Indexed"
        else:
            text = str(value)
        lines.append(f"{label}: {text}")
    return lines or ["Not Indexed"]


def _machine_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    return (0, int(text)) if text.isdigit() else (1, text.casefold())


def _recent_fit_checks_path() -> Path:
    runtime = ensure_runtime_layout(get_runtime_paths())
    return runtime.settings_dir / "eoat_atlas_recent_fit_checks.json"


def _load_recent_fit_checks() -> list[RecentFitCheck]:
    try:
        raw = json.loads(_recent_fit_checks_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = raw.get("eoat_atlas_recent_fit_checks") if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        return []
    checks = [_recent_check_from_dict(item) for item in records if isinstance(item, dict)]
    return sorted([check for check in checks if check is not None], key=lambda check: check.timestamp, reverse=True)[:15]


def _save_recent_fit_checks(checks: list[RecentFitCheck]) -> None:
    path = _recent_fit_checks_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"eoat_atlas_recent_fit_checks": [_recent_check_to_dict(check) for check in checks[:15]]}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def _recent_check_from_dict(raw: dict[str, Any]) -> RecentFitCheck | None:
    try:
        timestamp = datetime.fromisoformat(str(raw.get("timestamp", "")))
    except ValueError:
        timestamp = datetime.now()
    eoat_mode = str(raw.get("eoatMode") or raw.get("eoat_mode") or "auto").casefold()
    if eoat_mode not in {"auto", "manual", "current"}:
        eoat_mode = "auto"
    request = FitCheckRequest(
        tool_id=str(raw.get("selectedToolId") or raw.get("tool_id") or "").strip(),
        machine_id=str(raw.get("selectedMachineId") or raw.get("machine_id") or "").strip(),
        eoat_id=str(raw.get("selectedEOATId") or raw.get("eoat_id") or "").strip(),
        eoat_mode=eoat_mode,  # type: ignore[arg-type]
    )
    if request == FitCheckRequest():
        return None
    selected_items = raw.get("selectedItems")
    if not isinstance(selected_items, list):
        selected_items = []
    stored_items = tuple(_stored_selected_item(item) for item in selected_items if isinstance(item, dict))
    ordered_signature = str(raw.get("orderedSignature") or raw.get("ordered_signature") or "").strip()
    if not ordered_signature:
        ordered_signature = _stored_items_signature(stored_items)
    if not ordered_signature:
        ordered_signature = _request_signature(request)
    return RecentFitCheck(
        timestamp=timestamp,
        request=request,
        headline=str(raw.get("headline") or _request_headline(request)).strip(),
        summary=str(raw.get("summaryText") or raw.get("summary") or "").strip(),
        status=str(raw.get("resultStatus") or raw.get("status") or "insufficient_data").strip(),
        confidence=str(raw.get("confidence") or "unknown").strip(),
        selected_items=stored_items,
        ordered_signature=ordered_signature,
        match_level=str(raw.get("matchLevel") or raw.get("match_level") or "").strip(),
        id=str(raw.get("id") or ordered_signature or _recent_check_id(request)).strip(),
    )


def _recent_check_to_dict(check: RecentFitCheck) -> dict[str, Any]:
    return {
        "id": check.id or _recent_check_id(check.request),
        "timestamp": check.timestamp.isoformat(),
        "orderedSignature": check.ordered_signature or _stored_items_signature(check.selected_items) or _request_signature(check.request),
        "selectedItems": list(check.selected_items),
        "selectedToolId": check.request.tool_id,
        "selectedMachineId": check.request.machine_id,
        "selectedEOATId": check.request.eoat_id,
        "eoatMode": check.request.eoat_mode,
        "resultStatus": check.status,
        "confidence": check.confidence,
        "matchLevel": check.match_level or _match_text_from_confidence(check.confidence),
        "summaryText": check.summary,
        "headline": check.headline,
    }


def _stored_selected_item(raw: dict[str, Any]) -> dict[str, Any]:
    slot_value = raw.get("slotIndex", raw.get("slot_index", ""))
    try:
        slot_index: int | str = int(slot_value)
    except (TypeError, ValueError):
        slot_index = ""
    return {
        "slotIndex": slot_index,
        "id": str(raw.get("id") or "").strip(),
        "type": str(raw.get("type") or "").strip(),
        "label": str(raw.get("label") or "").strip(),
        "subtitle": str(raw.get("subtitle") or "").strip(),
    }


def _recent_check_id(request: FitCheckRequest) -> str:
    return "|".join((request.tool_id, request.machine_id, request.eoat_id, request.eoat_mode))


def _request_headline(request: FitCheckRequest) -> str:
    parts = []
    if request.tool_id:
        parts.append(request.tool_id)
    if request.eoat_id:
        parts.append(request.eoat_id)
    if request.machine_id:
        parts.append(machine_label(request.machine_id))
    return " -> ".join(parts) or "Fit Check"


def _recent_items_headline(items: tuple[dict[str, Any], ...]) -> str:
    parts = []
    for item in items:
        label = str(item.get("label") or item.get("id") or "").strip()
        kind = str(item.get("type") or "").strip()
        if kind == "machine":
            label = machine_label(label or str(item.get("id") or ""))
        if label:
            parts.append(label)
    return " -> ".join(parts)


def _ordered_signature(selections: list[SelectorOption | None]) -> str:
    if len(selections) != 3 or any(option is None for option in selections):
        return ""
    return "|".join(f"slot{index + 1}:{option.kind}:{option.key}" for index, option in enumerate(selections) if option is not None)


def _stored_items_signature(items: tuple[dict[str, Any], ...]) -> str:
    if not items:
        return ""
    def sort_key(item: dict[str, Any]) -> int:
        value = item.get("slotIndex")
        return value if isinstance(value, int) else 999

    ordered = sorted(items, key=sort_key)
    return "|".join(
        f"slot{index + 1}:{str(item.get('type') or '').strip()}:{str(item.get('id') or '').strip()}"
        for index, item in enumerate(ordered)
        if str(item.get("type") or "").strip() and str(item.get("id") or "").strip()
    )


def _request_signature(request: FitCheckRequest) -> str:
    if not (request.tool_id and request.machine_id and request.eoat_id):
        return ""
    return f"slot1:tool:{request.tool_id}|slot2:machine:{request.machine_id}|slot3:eoat:{request.eoat_id}"


def _missing_recent_parts(expected: FitCheckRequest, restored: FitCheckRequest) -> list[str]:
    missing = []
    if expected.tool_id and not restored.tool_id:
        missing.append(f"Tool {expected.tool_id}")
    if expected.machine_id and not restored.machine_id:
        missing.append(machine_label(expected.machine_id))
    if expected.eoat_id and not restored.eoat_id:
        missing.append(f"EOAT {expected.eoat_id}")
    return missing


__all__ = ["AtlasMinimalistFitCheckPage", "MinimalistFitCheckContent"]
