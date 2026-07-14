from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, ToolRecord
from core.atlas_setup_packets import (
    PACKET_TYPE_SETUP_VERIFICATION,
    PHOTO_KEY,
    SetupPacketOptions,
    build_setup_packet_context,
)
from core.atlas_utils import display_value
from core.fit_check_service import FitCheckResult, FitCheckService
from core.openers import open_path
from core.packet_builder_packets import (
    PACKET_TYPE_CHANGEOVER,
    PACKET_TYPE_SETUP,
    PacketSetup,
    RecentPacket,
    build_change_summary,
    changeover_checklist,
    export_changeover_packet_pdf,
    is_valid_fit_result,
    load_recent_packets,
    make_recent_packet,
    setup_checklist,
    upsert_recent_packet,
)
from core.setup_packet_pdf import export_setup_packet_pdf

from .data import loaded_status_text, machine_label
from .fit_check import FIT_CHECK_STYLES, CompatibilityOptionFilter, FitCheckScrim, FitCheckSelector, SelectorOption
from .widgets import (
    ACCENT_BRIGHT,
    AnimatedGlassPanel,
    CloseIconButton,
    GlassPanel,
    MinimalistToast,
    StatusDot,
    TitleAccentBar,
    clear_layout,
    glyph_icon,
)


def _minimalist_setting(controller, dotted_path: str, default=None):
    settings = getattr(controller, "minimalist_app_settings", None)
    if not isinstance(settings, dict):
        return default
    node = settings
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return default if node is None else node


PACKET_BUILDER_STYLES = (
    FIT_CHECK_STYLES
    + """
QWidget#AtlasMinimalistPacketBuilderPage,
QWidget#MinimalistPacketBuilderContent,
QWidget#PacketBuilderBody,
QWidget#PacketBuilderSetupPage,
QWidget#PacketBuilderChangeoverPage,
QWidget#PacketBuilderSetupGrid,
QWidget#PacketBuilderSummaryRow,
QWidget#PacketBuilderRecentBody,
QWidget#PacketBuilderActionRow,
QWidget#PacketBuilderFieldGrid,
QWidget#PacketBuilderHelperRow,
QWidget#PacketBuilderSetupField,
QWidget#PacketBuilderSummaryMetrics,
QWidget#PacketBuilderOverlayBody {
    background: transparent;
}
QScrollArea#PacketBuilderScroll {
    background: transparent;
    border: 0;
}
QScrollArea#PacketBuilderScroll QWidget {
    background: transparent;
}
QLabel#PacketBuilderTitle {
    color: #f8fbff;
    font-size: 31pt;
    font-weight: 820;
}
QLabel#PacketBuilderSubtitle {
    color: #d7e2f0;
    font-size: 10.5pt;
    font-weight: 500;
}
QFrame#PacketBuilderTitleAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(0, 89, 200, 0), stop:.52 #047aff, stop:1 rgba(0, 89, 200, 0));
    border: 0;
    min-height: 3px;
    max-height: 3px;
}
QLabel#PacketBuilderSectionTitle {
    color: #ffffff;
    font-size: 10.2pt;
    font-weight: 780;
}
QLabel#PacketBuilderGroupTitle {
    color: #f7fbff;
    font-size: 10.7pt;
    font-weight: 820;
}
QLabel#PacketBuilderCardTitle {
    color: #ffffff;
    font-size: 11pt;
    font-weight: 780;
}
QLabel#PacketBuilderCardSubtitle,
QLabel#PacketBuilderMuted,
QLabel#PacketBuilderMeta,
QLabel#PacketBuilderSummaryText {
    color: #c6d3e3;
    font-size: 9pt;
    font-weight: 520;
}
QLabel#PacketBuilderSelectedTitle {
    color: #ffffff;
    font-size: 10.6pt;
    font-weight: 820;
}
QLabel#PacketBuilderSelectedSubtitle {
    color: #c6d3e3;
    font-size: 8.9pt;
    font-weight: 540;
}
QLabel#PacketBuilderStatusTitle {
    color: #f8fbff;
    font-size: 9.2pt;
    font-weight: 760;
}
QLabel#PacketBuilderStatusValue {
    color: #ffffff;
    font-size: 10.2pt;
    font-weight: 820;
}
QLabel#PacketBuilderStatusValue[tone="good"] {
    color: #36d86a;
}
QLabel#PacketBuilderStatusValue[tone="warn"] {
    color: #ffb145;
}
QLabel#PacketBuilderStatusValue[tone="bad"] {
    color: #ff5c6c;
}
QLabel#PacketBuilderPill {
    border-radius: 9px;
    padding: 4px 10px;
    font-size: 8pt;
    font-weight: 760;
}
QLabel#PacketBuilderPill[tone="generated"] {
    color: #d9fff0;
    background: rgba(12, 101, 79, 126);
}
QLabel#PacketBuilderPill[tone="draft"] {
    color: #d9e8ff;
    background: rgba(28, 65, 116, 138);
}
QPushButton#PacketBuilderPrimaryButton {
    background-color: #1677ff;
    color: #ffffff;
    border: 1px solid rgba(103, 190, 255, 180);
    border-radius: 7px;
    min-height: 42px;
    min-width: 150px;
    padding: 0 18px;
    font-size: 9.2pt;
    font-weight: 760;
}
QPushButton#PacketBuilderPrimaryButton:hover {
    background-color: #248fff;
    border-color: rgba(145, 220, 255, 220);
}
QPushButton#PacketBuilderPrimaryButton:disabled,
QPushButton#PacketBuilderSecondaryButton:disabled,
QPushButton#PacketBuilderGhostButton:disabled,
QPushButton#PacketBuilderIconButton:disabled {
    color: rgba(190, 205, 226, 92);
    border-color: rgba(73, 111, 157, 58);
    background: rgba(6, 18, 38, 70);
}
QPushButton#PacketBuilderSecondaryButton,
QPushButton#PacketBuilderGhostButton,
QPushButton#PacketBuilderIconButton {
    background: rgba(6, 18, 38, 128);
    color: #ffffff;
    border: 1px solid rgba(73, 111, 157, 134);
    border-radius: 7px;
    min-height: 40px;
    min-width: 116px;
    padding: 0 15px;
    font-size: 9pt;
    font-weight: 700;
}
QPushButton#PacketBuilderSecondaryButton:hover,
QPushButton#PacketBuilderGhostButton:hover,
QPushButton#PacketBuilderIconButton:hover {
    background: rgba(12, 42, 88, 174);
    border-color: rgba(31, 135, 255, 196);
}
QPushButton#PacketBuilderIconButton {
    min-width: 38px;
    max-width: 38px;
    padding: 0;
}
QLabel#PacketBuilderOverlayTitle {
    color: #ffffff;
    font-size: 18pt;
    font-weight: 820;
}
QLabel#PacketBuilderOverlaySubtitle {
    color: #c7d6e8;
    font-size: 9.2pt;
    font-weight: 520;
}
QLabel#PacketBuilderOverlaySection {
    color: #83d8ff;
    font-size: 11pt;
    font-weight: 780;
}
QLabel#PacketBuilderOverlayText {
    color: #dce8f8;
    font-size: 9.8pt;
    font-weight: 520;
}
"""
)

PACKET_BUILDER_PRIMARY_ACTION_STYLE = """
QPushButton {
    background-color: #1677ff;
    color: #ffffff;
    border: 1px solid rgba(103, 190, 255, 180);
    border-radius: 7px;
    padding: 0 18px;
    font-size: 9.2pt;
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


class AtlasMinimalistPacketBuilderPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle: AtlasDataBundle | None = None
        self.setObjectName("AtlasMinimalistPacketBuilderPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.packet_content = MinimalistPacketBuilderContent(controller)
        from .shell import AtlasMinimalistShell

        self.shell = AtlasMinimalistShell(controller, self.packet_content)
        layout.addWidget(self.shell)

    def set_bundle(self, bundle) -> None:
        self.bundle = bundle
        self.packet_content.set_bundle(bundle)
        self.shell.set_bundle(bundle)

    def refresh(self) -> None:
        self.packet_content.set_bundle(self.bundle)

    def page_shown(self) -> None:
        self.shell.close_overlays(immediate=True)
        self.packet_content.close_search_overlays()
        self.shell.set_active_nav("packet_builder")
        self.shell.top_bar.set_back_visible(False, animated=False)
        self.packet_content.set_bundle(self.bundle)
        self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_search_overlay(self) -> None:
        self.packet_content.close_search_overlays()
        self.shell.open_search()

    def show_toast(self, message: str) -> None:
        self.packet_content.show_toast(message)

    def focus_search_text(self, text: str) -> None:
        self.packet_content.focus_search_text(text)

    def open_setup_packet(
        self,
        *,
        setup: PacketSetup | None = None,
        packet_type: str = PACKET_TYPE_SETUP,
        from_setup: PacketSetup | None = None,
        to_setup: PacketSetup | None = None,
    ) -> None:
        self.packet_content.apply_incoming_state(
            packet_type=packet_type,
            setup=setup,
            from_setup=from_setup,
            to_setup=to_setup,
        )

    def current_valid_packet(self) -> bool:
        return self.packet_content.current_valid_packet()

    def save_current_draft(self) -> None:
        self.packet_content.save_draft()

    def generate_current_pdf(self) -> None:
        self.packet_content.generate_pdf()


class MinimalistPacketBuilderContent(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle: AtlasDataBundle | None = None
        self.service = FitCheckService(None)
        self.packet_type = PACKET_TYPE_SETUP
        self.setup_result: FitCheckResult | None = None
        self.from_result: FitCheckResult | None = None
        self.to_result: FitCheckResult | None = None
        self.recent_packets: list[RecentPacket] = load_recent_packets()
        self.active_dropdown: str | None = None
        self.setObjectName("MinimalistPacketBuilderContent")
        self.setStyleSheet(PACKET_BUILDER_STYLES)

        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("PacketBuilderScroll")
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(False)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.body.setObjectName("PacketBuilderBody")
        self.body_scroll.setWidget(self.body)

        self.title = QLabel("Packet Builder", self.body)
        self.title.setObjectName("PacketBuilderTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle = QLabel("Create setup or changeover packets to guide your process.", self.body)
        self.subtitle.setObjectName("PacketBuilderSubtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.accent = TitleAccentBar(self.body)
        self.accent.setObjectName("PacketBuilderTitleAccent")

        self.main_card = GlassPanel(self.body, radius=8, streaks=True)
        self.main_card.set_glass(alpha=122, border_alpha=80, border_color=QColor("#1f87ff"), fill_color=QColor("#051226"))
        self._build_main_card()

        self.recent_card = GlassPanel(self.body, radius=8)
        self.recent_card.set_glass(alpha=112, border_alpha=82, border_color=QColor("#1f87ff"), fill_color=QColor("#051226"))
        self._build_recent_card()

        self.status = PacketBuilderStatusLine(self)
        self.toast = MinimalistToast(self)
        self.toast.hide()
        self.scrim = FitCheckScrim(self)
        self.scrim.clicked.connect(self.close_preview)
        self.scrim.hide()
        self.preview_overlay = PacketPreviewOverlay(self)
        self.preview_overlay.close_requested.connect(self.close_preview)
        self.preview_overlay.hide()
        self._pending_state: dict[str, Any] = {}

    def set_bundle(self, bundle: AtlasDataBundle | None) -> None:
        self.bundle = bundle
        self.service = FitCheckService(bundle)
        for group in (self.setup_group, self.from_group, self.to_group):
            group.set_bundle(bundle, self.service)
        self.status.set_status(loaded_status_text(bundle), ready=bundle is not None)
        if self._pending_state:
            state = self._pending_state
            self._pending_state = {}
            self.apply_incoming_state(**state)
        self.refresh_validation()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_content()

    def _layout_content(self) -> None:
        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return
        self.body_scroll.setGeometry(self.rect())
        content_width = min(1230, max(1080, width - 170))
        if width < 1180:
            content_width = max(320, width - 44)
        x = (width - content_width) // 2
        title_y = 116
        main_height = 616 if self.packet_type == PACKET_TYPE_SETUP else 948
        recent_height = 210 if self.recent_packets else 168
        total_body_height = max(height, title_y + 110 + main_height + 24 + recent_height + 92)
        self.body.resize(width, total_body_height)
        self.title.setGeometry((width - 520) // 2, title_y, 520, 48)
        self.accent.setGeometry((width - 78) // 2, title_y + 56, 78, 9)
        self.subtitle.setGeometry((width - 720) // 2, title_y + 68, 720, 24)
        self.main_card.setGeometry(x, title_y + 110, content_width, main_height)
        self.recent_card.setGeometry(x, title_y + 110 + main_height + 22, content_width, recent_height)
        status_width = min(340, max(220, width - 80))
        self.status.setGeometry(width - status_width - 62, height - 48, status_width, 30)
        toast_width = min(720, max(260, width - 90))
        self.toast.setGeometry((width - toast_width) // 2, height - 116, toast_width, 72)
        self.scrim.setGeometry(self.rect())
        if self.preview_overlay.isVisible():
            self.preview_overlay.setGeometry(self._preview_rect())

    def focus_search_text(self, text: str) -> None:
        group = self.setup_group if self.packet_type == PACKET_TYPE_SETUP else self.to_group
        group.focus_tool(text)

    def show_toast(self, message: str) -> None:
        self.toast.show_message(message)

    def apply_incoming_state(
        self,
        *,
        packet_type: str = PACKET_TYPE_SETUP,
        setup: PacketSetup | None = None,
        from_setup: PacketSetup | None = None,
        to_setup: PacketSetup | None = None,
    ) -> None:
        if self.bundle is None:
            self._pending_state = {
                "packet_type": packet_type,
                "setup": setup,
                "from_setup": from_setup,
                "to_setup": to_setup,
            }
            return
        self.set_packet_type(packet_type if packet_type in {PACKET_TYPE_SETUP, PACKET_TYPE_CHANGEOVER} else PACKET_TYPE_SETUP)
        if setup is not None:
            self.setup_group.apply_setup(setup)
        if from_setup is not None:
            self.from_group.apply_setup(from_setup)
        if to_setup is not None:
            self.to_group.apply_setup(to_setup)
        self.refresh_validation()

    def set_packet_type(self, packet_type: str) -> None:
        self.close_search_overlays()
        packet_type = PACKET_TYPE_CHANGEOVER if packet_type == PACKET_TYPE_CHANGEOVER else PACKET_TYPE_SETUP
        self.packet_type = packet_type
        self.setup_type_card.set_selected(packet_type == PACKET_TYPE_SETUP)
        self.changeover_type_card.set_selected(packet_type == PACKET_TYPE_CHANGEOVER)
        self.stack.setCurrentWidget(self.changeover_page if packet_type == PACKET_TYPE_CHANGEOVER else self.setup_page)
        self.refresh_validation()
        self.updateGeometry()
        QTimer.singleShot(0, self._layout_content)

    def current_valid_packet(self) -> bool:
        if self.packet_type == PACKET_TYPE_CHANGEOVER:
            return self.from_group.selected_setup().complete() and self.to_group.selected_setup().complete() and is_valid_fit_result(self.from_result) and is_valid_fit_result(self.to_result)
        return self.setup_group.selected_setup().complete() and is_valid_fit_result(self.setup_result)

    def refresh_validation(self) -> None:
        if self.bundle is None:
            self.setup_result = self.from_result = self.to_result = None
            self._sync_summary()
            return
        self.setup_result = self._run_group(self.setup_group)
        self.from_result = self._run_group(self.from_group)
        self.to_result = self._run_group(self.to_group)
        self._sync_summary()

    def preview_packet(self) -> None:
        self.close_search_overlays()
        self.preview_overlay.set_packet(
            packet_type=self.packet_type,
            setup=self.setup_group.selected_setup(),
            from_setup=self.from_group.selected_setup(),
            to_setup=self.to_group.selected_setup(),
            setup_result=self.setup_result,
            from_result=self.from_result,
            to_result=self.to_result,
            change_summary=self._change_summary(),
        )
        self.scrim.setGeometry(self.rect())
        self.scrim.show()
        self.scrim.raise_()
        self.preview_overlay.raise_()
        self.preview_overlay.animate_open(self._preview_rect())

    def close_preview(self) -> None:
        self.scrim.hide()
        self.preview_overlay.animate_close(self.preview_overlay.geometry())

    def save_draft(self) -> None:
        self.close_search_overlays()
        if self.packet_type == PACKET_TYPE_CHANGEOVER:
            if not (self.from_group.has_any_selection() or self.to_group.has_any_selection()):
                self.show_toast("Select at least one setup item before saving a draft.")
                return
            packet = make_recent_packet(
                packet_type=PACKET_TYPE_CHANGEOVER,
                status="Draft",
                from_setup=self.from_group.selected_setup(),
                to_setup=self.to_group.selected_setup(),
            )
        else:
            if not self.setup_group.has_any_selection():
                self.show_toast("Select at least one setup item before saving a draft.")
                return
            packet = make_recent_packet(packet_type=PACKET_TYPE_SETUP, status="Draft", setup=self.setup_group.selected_setup())
        self.recent_packets = upsert_recent_packet(packet)
        self._render_recent_packets()
        self.show_toast("Packet draft saved.")

    def generate_pdf(self) -> None:
        self.close_search_overlays()
        if self.bundle is None:
            self.show_toast("Atlas data is still loading.")
            return
        if not self.current_valid_packet():
            self.show_toast("A packet cannot be generated until the setup is complete and compatible.")
            return
        try:
            if self.packet_type == PACKET_TYPE_CHANGEOVER:
                path = export_changeover_packet_pdf(
                    self.bundle,
                    self.from_group.selected_setup(),
                    self.to_group.selected_setup(),
                    from_result=self.from_result,
                    to_result=self.to_result,
                )
                packet = make_recent_packet(
                    packet_type=PACKET_TYPE_CHANGEOVER,
                    status="Generated",
                    from_setup=self.from_group.selected_setup(),
                    to_setup=self.to_group.selected_setup(),
                    pdf_path=str(path),
                )
            else:
                setup = self.setup_group.selected_setup()
                include_photos = bool(_minimalist_setting(self.controller, "pdf.include_photos", True))
                context = build_setup_packet_context(
                    self.bundle,
                    setup.machine_id,
                    setup.tool_id,
                    setup.eoat_id,
                    SetupPacketOptions(
                        packet_type=PACKET_TYPE_SETUP_VERIFICATION,
                        photo_inclusion=PHOTO_KEY if include_photos else "none",
                        include_setup_summary=bool(_minimalist_setting(self.controller, "pdf.include_fit_check_summary", True)),
                        include_compatibility_result=bool(_minimalist_setting(self.controller, "pdf.include_compatibility_notes", True)),
                        include_requirements_check=bool(_minimalist_setting(self.controller, "pdf.include_required_setup_notes", True)),
                        include_warnings=bool(_minimalist_setting(self.controller, "pdf.include_reference_warnings", True)),
                        include_eoat_photo=include_photos,
                        include_setup_checklist=bool(_minimalist_setting(self.controller, "pdf.include_required_setup_notes", True)),
                    ),
                )
                output_folder = str(_minimalist_setting(self.controller, "paths.output_folder", "") or "").strip()
                result = export_setup_packet_pdf(context, output_dir=Path(output_folder).expanduser() if output_folder else None)
                path = result.path
                packet = make_recent_packet(packet_type=PACKET_TYPE_SETUP, status="Generated", setup=setup, pdf_path=str(path))
        except Exception as exc:
            self.show_toast(f"Packet PDF generation failed: {exc}")
            return
        self.recent_packets = upsert_recent_packet(packet)
        self._render_recent_packets()
        self.show_toast(f"Generated packet PDF: {path}")

    def use_current_fit_check(self, target: str) -> None:
        self.close_search_overlays()
        getter = getattr(self.controller, "current_fit_check_setup", None)
        setup = getter() if callable(getter) else None
        if not isinstance(setup, PacketSetup):
            self.show_toast("No valid Fit Check is available.")
            return
        if target == "from":
            self.from_group.apply_setup(setup)
        elif target == "to":
            self.to_group.apply_setup(setup)
        else:
            self.setup_group.apply_setup(setup)
        self.refresh_validation()

    def swap_from_to(self) -> None:
        self.close_search_overlays()
        from_setup = self.from_group.selected_setup()
        to_setup = self.to_group.selected_setup()
        self.from_group.apply_setup(to_setup)
        self.to_group.apply_setup(from_setup)
        self.refresh_validation()

    def clear_form(self) -> None:
        self.close_search_overlays()
        has_data = self.setup_group.has_any_selection() or self.from_group.has_any_selection() or self.to_group.has_any_selection()
        if has_data:
            result = QMessageBox.question(
                self,
                "Clear Packet Builder",
                "Clear the current Packet Builder selections?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,
            )
            if result != QMessageBox.StandardButton.Ok:
                return
        self.setup_group.clear()
        self.from_group.clear()
        self.to_group.clear()
        self.refresh_validation()

    def _build_main_card(self) -> None:
        layout = QVBoxLayout(self.main_card)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(18)
        section = QLabel("Packet Type")
        section.setObjectName("PacketBuilderSectionTitle")
        layout.addWidget(section)
        type_row = QHBoxLayout()
        type_row.setSpacing(20)
        self.setup_type_card = PacketTypeCard("Setup Packet", "One Tool, Machine, and EOAT", "doc")
        self.changeover_type_card = PacketTypeCard("Changeover Packet", "From current setup to new setup", "swap")
        self.setup_type_card.clicked.connect(lambda: self.set_packet_type(PACKET_TYPE_SETUP))
        self.changeover_type_card.clicked.connect(lambda: self.set_packet_type(PACKET_TYPE_CHANGEOVER))
        type_row.addWidget(self.setup_type_card, 1)
        type_row.addWidget(self.changeover_type_card, 1)
        layout.addLayout(type_row)

        self.stack = QStackedWidget()
        self.stack.setObjectName("PacketBuilderStack")
        self.setup_page = QWidget()
        self.setup_page.setObjectName("PacketBuilderSetupPage")
        self._build_setup_page()
        self.changeover_page = QWidget()
        self.changeover_page.setObjectName("PacketBuilderChangeoverPage")
        self._build_changeover_page()
        self.stack.addWidget(self.setup_page)
        self.stack.addWidget(self.changeover_page)
        layout.addWidget(self.stack, 1)

        line = QFrame()
        line.setObjectName("MinimalistDivider")
        layout.addWidget(line)
        actions = QWidget()
        actions.setObjectName("PacketBuilderActionRow")
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(16)
        action_layout.addStretch(1)
        self.preview_button = _packet_button("Preview Packet", "secondary", "target")
        self.preview_button.clicked.connect(self.preview_packet)
        self.save_button = _packet_button("Save Draft", "secondary", "save")
        self.save_button.clicked.connect(self.save_draft)
        self.generate_button = _packet_button("Generate PDF", "primary", "doc")
        self.generate_button.clicked.connect(self.generate_pdf)
        action_layout.addWidget(self.preview_button)
        action_layout.addWidget(self.save_button)
        action_layout.addWidget(self.generate_button)
        layout.addWidget(actions)
        self.set_packet_type(PACKET_TYPE_SETUP)

    def _build_setup_page(self) -> None:
        layout = QVBoxLayout(self.setup_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(22)
        details = QLabel("Setup Details")
        details.setObjectName("PacketBuilderSectionTitle")
        layout.addWidget(details)
        self.setup_group = PacketSetupGroup("", self.controller, group_id="setup", framed=False)
        self.setup_group.selection_changed.connect(self._packet_selection_changed)
        self.setup_group.dropdown_requested.connect(self._packet_dropdown_requested)
        self.setup_group.open_record_requested.connect(self._open_record)
        layout.addWidget(self.setup_group)
        layout.addSpacing(8)
        self.setup_summary = PacketValidationSummary()
        layout.addWidget(self.setup_summary)
        layout.addStretch(1)

    def _build_changeover_page(self) -> None:
        layout = QVBoxLayout(self.changeover_page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(20)
        top_widget = QWidget()
        top_widget.setObjectName("PacketBuilderHelperRow")
        top = QHBoxLayout(top_widget)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        details = QLabel("Changeover Details")
        details.setObjectName("PacketBuilderSectionTitle")
        top.addWidget(details)
        top.addStretch(1)
        self.use_current_from_button = _packet_button("Use Current Fit Check as FROM", "ghost", "status")
        self.use_current_to_button = _packet_button("Use Current Fit Check as TO", "ghost", "status")
        self.swap_button = _packet_button("Swap FROM / TO", "ghost", "swap")
        self.clear_button = _packet_button("Clear", "ghost", "minus")
        self.use_current_from_button.clicked.connect(lambda: self.use_current_fit_check("from"))
        self.use_current_to_button.clicked.connect(lambda: self.use_current_fit_check("to"))
        self.swap_button.clicked.connect(self.swap_from_to)
        self.clear_button.clicked.connect(self.clear_form)
        for button in (self.use_current_from_button, self.use_current_to_button, self.swap_button, self.clear_button):
            top.addWidget(button)
        layout.addWidget(top_widget)
        self.from_group = PacketSetupGroup("FROM / Current Setup", self.controller, group_id="from", framed=True)
        self.to_group = PacketSetupGroup("TO / New Setup", self.controller, group_id="to", framed=True)
        for group in (self.from_group, self.to_group):
            group.selection_changed.connect(self._packet_selection_changed)
            group.dropdown_requested.connect(self._packet_dropdown_requested)
            group.open_record_requested.connect(self._open_record)
            layout.addWidget(group)
        self.changeover_summary = ChangeoverValidationSummary()
        layout.addWidget(self.changeover_summary)
        layout.addStretch(1)

    def _build_recent_card(self) -> None:
        layout = QVBoxLayout(self.recent_card)
        layout.setContentsMargins(24, 18, 24, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        label = QLabel("Recent Packets")
        label.setObjectName("PacketBuilderSectionTitle")
        header.addWidget(label)
        header.addStretch(1)
        layout.addLayout(header)
        self.recent_body = QWidget()
        self.recent_body.setObjectName("PacketBuilderRecentBody")
        self.recent_layout = QVBoxLayout(self.recent_body)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(8)
        layout.addWidget(self.recent_body, 1)
        self._render_recent_packets()

    def _render_recent_packets(self) -> None:
        clear_layout(self.recent_layout)
        packets = self.recent_packets[:3]
        if not packets:
            empty = QLabel("No recent packets yet")
            empty.setObjectName("PacketBuilderMuted")
            self.recent_layout.addWidget(empty)
            self.recent_layout.addStretch(1)
            QTimer.singleShot(0, self._layout_content)
            return
        for packet in packets:
            row = RecentPacketRow(packet)
            row.reload_requested.connect(self._reload_recent_packet)
            row.generate_requested.connect(self._generate_recent_packet)
            row.open_pdf_requested.connect(self._open_recent_pdf)
            self.recent_layout.addWidget(row)
        self.recent_layout.addStretch(1)
        QTimer.singleShot(0, self._layout_content)

    def _reload_recent_packet(self, packet: RecentPacket) -> None:
        self.apply_incoming_state(
            packet_type=packet.packet_type,
            setup=packet.setup,
            from_setup=packet.from_setup,
            to_setup=packet.to_setup,
        )
        self.show_toast(f"Loaded {packet.title()}.")

    def _generate_recent_packet(self, packet: RecentPacket) -> None:
        self._reload_recent_packet(packet)
        QTimer.singleShot(80, self.generate_pdf)

    def _open_recent_pdf(self, packet: RecentPacket) -> None:
        path = Path(packet.pdf_path)
        if not packet.pdf_path or not path.exists():
            self.show_toast("PDF file missing.")
            return
        open_path(path)

    def _sync_summary(self) -> None:
        self.setup_summary.set_setup(self.setup_group.selected_setup(), self.setup_result, "Setup Packet")
        self.changeover_summary.set_changeover(
            self.from_group.selected_setup(),
            self.to_group.selected_setup(),
            self.from_result,
            self.to_result,
            self._change_summary(),
        )
        valid = self.current_valid_packet()
        self.generate_button.setEnabled(valid)
        self.preview_button.setEnabled(self.packet_type == PACKET_TYPE_CHANGEOVER or self.setup_group.has_any_selection() or self.from_group.has_any_selection() or self.to_group.has_any_selection())
        current_available = isinstance(getattr(self.controller, "current_fit_check_setup", lambda: None)(), PacketSetup)
        self.use_current_from_button.setEnabled(current_available)
        self.use_current_to_button.setEnabled(current_available)

    def _change_summary(self) -> tuple[str, ...]:
        return build_change_summary(self.bundle, self.from_group.selected_setup(), self.to_group.selected_setup(), from_result=self.from_result, to_result=self.to_result)

    def _run_group(self, group: PacketSetupGroup) -> FitCheckResult | None:
        setup = group.selected_setup()
        if setup == PacketSetup():
            return None
        return self.service.run_fit_check(setup.to_fit_request())

    def _packet_dropdown_requested(self, field_id: str) -> None:
        self.active_dropdown = field_id
        for group in self._packet_groups():
            group.sync_active_dropdown(self.active_dropdown)

    def _packet_selection_changed(self) -> None:
        self.close_search_overlays()
        self.refresh_validation()

    def close_search_overlays(self) -> None:
        self.active_dropdown = None
        for group in self._packet_groups():
            group.close_dropdowns()
        if hasattr(self, "scrim") and self.scrim.isVisible():
            self.scrim.hide()
        if hasattr(self, "preview_overlay") and self.preview_overlay.isVisible():
            self.preview_overlay.hide()

    def handle_escape(self) -> bool:
        if any(group.has_open_dropdown() for group in self._packet_groups()):
            self.close_search_overlays()
            return True
        self.active_dropdown = None
        return False

    def mousePressEvent(self, event) -> None:
        if self.active_dropdown and not self._point_inside_selector_or_dropdown(event.position().toPoint()):
            self.close_search_overlays()
        super().mousePressEvent(event)

    def _packet_groups(self) -> tuple[PacketSetupGroup, ...]:
        return tuple(
            group
            for group in (
                getattr(self, "setup_group", None),
                getattr(self, "from_group", None),
                getattr(self, "to_group", None),
            )
            if group is not None
        )

    def _point_inside_selector_or_dropdown(self, point: QPoint) -> bool:
        return any(group.contains_content_point(point, self) for group in self._packet_groups())

    def _open_record(self, kind: str, key: str) -> None:
        self.close_search_overlays()
        if kind == "tool":
            self.controller.open_tool(key)
        elif kind == "machine":
            self.controller.open_machine(key)
        elif kind == "eoat":
            self.controller.open_eoat(key)

    def _preview_rect(self) -> QRect:
        width = min(960, max(640, self.width() - 220))
        height = min(780, max(520, self.height() - 170))
        return QRect((self.width() - width) // 2, 118, width, height)


class PacketSetupGroup(GlassPanel):
    selection_changed = Signal()
    open_record_requested = Signal(str, str)
    dropdown_requested = Signal(str)

    def __init__(self, title: str, controller, *, group_id: str = "setup", framed: bool = True, parent=None):
        super().__init__(parent, radius=8)
        self.controller = controller
        self.group_id = group_id
        self.bundle: AtlasDataBundle | None = None
        self.service = FitCheckService(None)
        self.framed = framed
        if framed:
            self.set_glass(alpha=88, border_alpha=68, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        else:
            self.set_glass(alpha=0, border_alpha=0, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(218 if framed else 178)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18 if framed else 0, 14 if framed else 0, 18 if framed else 0, 14 if framed else 0)
        layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("PacketBuilderGroupTitle" if framed else "PacketBuilderSectionTitle")
            layout.addWidget(label)
        grid_host = QWidget()
        grid_host.setObjectName("PacketBuilderFieldGrid")
        grid = QHBoxLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(22)
        self.fields = {
            "tool": PacketSetupField("tool", "Tool", "Search or enter Tool #..."),
            "machine": PacketSetupField("machine", "Machine", "Search or enter Machine #..."),
            "eoat": PacketSetupField("eoat", "EOAT", "Search or enter EOAT ID..."),
        }
        self.selectors = {kind: field.selector for kind, field in self.fields.items()}
        for kind, field in self.fields.items():
            field.selection_changed.connect(self._selection_changed)
            field.dropdown_requested.connect(lambda kind=kind: self.dropdown_requested.emit(self.field_id(kind)))
            field.open_requested.connect(lambda _checked=False, kind=kind: self._open_record(kind))
            grid.addWidget(field, 1)
        layout.addWidget(grid_host)
        self.set_bundle(None)

    def set_bundle(self, bundle: AtlasDataBundle | None, service: FitCheckService | None = None) -> None:
        self.bundle = bundle
        self.service = service or FitCheckService(bundle)
        self.refresh_compatible_options()

    def selected_setup(self) -> PacketSetup:
        return PacketSetup(
            tool_id=self.fields["tool"].selected_key(),
            machine_id=self.fields["machine"].selected_key(),
            eoat_id=self.fields["eoat"].selected_key(),
        ).normalized()

    def apply_setup(self, setup: PacketSetup) -> None:
        self.close_dropdowns()
        setup = setup.normalized()
        for kind, field in self.fields.items():
            field.set_options(self._options_for_kind(kind))
        self.fields["tool"].select_key(setup.tool_id)
        self.fields["machine"].select_key(setup.machine_id)
        self.fields["eoat"].select_key(setup.eoat_id)
        self.refresh_compatible_options()
        self._sync_selected_cards()
        self.selection_changed.emit()

    def clear(self) -> None:
        self.close_dropdowns()
        for field in self.fields.values():
            field.clear_selection()
        self.refresh_compatible_options()
        self._sync_selected_cards()
        self.selection_changed.emit()

    def has_any_selection(self) -> bool:
        return any(field.has_content() for field in self.fields.values())

    def focus_tool(self, text: str) -> None:
        self.fields["tool"].set_focus_text(text)

    def field_id(self, kind: str) -> str:
        return f"{self.group_id}.{kind}"

    def sync_active_dropdown(self, active_dropdown: str | None) -> None:
        self.refresh_compatible_options()
        for kind, field in self.fields.items():
            selector = field.selector
            if active_dropdown == self.field_id(kind):
                selector.show_dropdown()
            else:
                selector.close_dropdown()

    def refresh_compatible_options(self) -> None:
        for kind, field in self.fields.items():
            context = self._selected_context(excluding_kind=kind)
            options = CompatibilityOptionFilter(self.service, self._options_for_kind).suggestions(
                current=field.selector.selected_option(),
                query=field.selector.query_text(),
                context=context,
                allowed_kinds={kind},
            )
            field.set_options(options)
            if context and not options:
                field.set_empty_results_text(f"No compatible {field.label} found for the current selections.")
            else:
                field.set_empty_results_text("")
        self._sync_selected_cards()

    def close_dropdowns(self) -> None:
        for field in self.fields.values():
            field.selector.close_dropdown()

    def has_open_dropdown(self) -> bool:
        return any(field.selector.dropdown.isVisible() for field in self.fields.values())

    def contains_content_point(self, point: QPoint, content: QWidget) -> bool:
        for field in self.fields.values():
            field_rect = QRect(field.mapTo(content, QPoint(0, 0)), field.size())
            if field_rect.contains(point):
                return True
            dropdown = field.selector.dropdown
            if dropdown.isVisible():
                dropdown_rect = QRect(dropdown.mapTo(content, QPoint(0, 0)), dropdown.size())
                if dropdown_rect.contains(point):
                    return True
        return False

    def _selection_changed(self) -> None:
        self.close_dropdowns()
        self.refresh_compatible_options()
        self._sync_selected_cards()
        self.selection_changed.emit()

    def _sync_selected_cards(self) -> None:
        for field in self.fields.values():
            field.sync_selected_card()

    def _open_record(self, kind: str) -> None:
        key = self.fields[kind].selected_key()
        if key:
            self.open_record_requested.emit(kind, key)

    def _selected_context(self, *, excluding_kind: str) -> list[SelectorOption]:
        context = []
        for kind, field in self.fields.items():
            if kind == excluding_kind:
                continue
            option = field.selector.selected_option()
            if option is not None:
                context.append(option)
        return context

    def _options_for_kind(self, kind: str) -> list[SelectorOption]:
        if self.bundle is None:
            return []
        if kind == "tool":
            return [_tool_option(record) for record in self.bundle.tools]
        if kind == "machine":
            return [_machine_option(record) for record in self.bundle.machines]
        if kind == "eoat":
            return [_eoat_option(record) for record in self.bundle.eoats]
        return []


class PacketSetupField(QWidget):
    selection_changed = Signal()
    open_requested = Signal()
    dropdown_requested = Signal()

    def __init__(self, kind: str, label: str, placeholder: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.label = label
        self.setObjectName("PacketBuilderSetupField")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.selector = FitCheckSelector(label, placeholder)
        self.selector.secondary.hide()
        self.selector.selection_changed.connect(self._selection_changed)
        self.selector.focus_requested.connect(self.dropdown_requested.emit)
        self.selector.query_changed.connect(self.dropdown_requested.emit)
        self.selected_card = PacketSelectedRecordCard(kind, label)
        self.selected_card.open_requested.connect(self.open_requested.emit)
        layout.addWidget(self.selector)
        layout.addWidget(self.selected_card)

    def set_options(self, options: list[SelectorOption]) -> None:
        self.selector.set_options(options)
        self.sync_selected_card()

    def set_empty_results_text(self, text: str) -> None:
        self.selector.set_empty_results_text(text)

    def selected_key(self) -> str:
        return self.selector.selected_key()

    def has_content(self) -> bool:
        return self.selector.has_content()

    def select_key(self, key: str) -> None:
        self.selector.select_key(key, kind=self.kind, emit=False)
        self.sync_selected_card()

    def clear_selection(self) -> None:
        self.selector.clear_selection(emit=False)
        self.sync_selected_card()

    def set_focus_text(self, text: str) -> None:
        self.selector.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.selector.set_query_text(text)

    def sync_selected_card(self) -> None:
        self.selected_card.set_option(self.selector.selected_option())

    def _selection_changed(self) -> None:
        self.sync_selected_card()
        self.selection_changed.emit()


class PacketSelectedRecordCard(GlassPanel):
    open_requested = Signal()

    def __init__(self, kind: str, label: str, parent=None):
        super().__init__(parent, radius=7)
        self.kind = kind
        self.label = label
        self.setFixedHeight(64)
        self.title = QLabel("")
        self.title.setObjectName("PacketBuilderSelectedTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("PacketBuilderSelectedSubtitle")
        self.open_button = _packet_button("", "icon", "external")
        self.open_button.setToolTip(f"Open {label} profile")
        self.open_button.clicked.connect(self.open_requested.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(10)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)
        layout.addWidget(self.open_button)
        self.set_option(None)

    def set_option(self, option: SelectorOption | None) -> None:
        has_selection = option is not None and bool(option.key)
        if has_selection:
            self.title.setText(option.display or option.key)
            self.subtitle.setText(option.secondary or option.keywords or self.label)
            self.set_glass(alpha=100, border_alpha=82, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        else:
            self.title.setText(f"No {self.label} selected")
            self.subtitle.setText(f"Select a {self.label} above")
            self.set_glass(alpha=58, border_alpha=46, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        self.open_button.setVisible(has_selection)
        self.open_button.setEnabled(has_selection)


class PacketValidationSummary(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=94, border_alpha=72, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        self.setMinimumHeight(96)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(22)
        self.compat = SummaryMetric("Compatibility", "Incomplete", "warn", "status")
        self.packet = SummaryMetric("Packet Type", "Setup Packet", "normal", "doc")
        self.generated = SummaryMetric("Generated On", "Not generated", "normal", "time")
        layout.addWidget(self.compat, 1)
        layout.addWidget(self.packet, 1)
        layout.addWidget(self.generated, 1)

    def set_setup(self, setup: PacketSetup, result: FitCheckResult | None, packet_type: str) -> None:
        if not setup.complete():
            self.compat.set_value("Incomplete", "warn", "Select Tool, Machine, and EOAT.")
        elif result is None:
            self.compat.set_value("Incomplete", "warn", "Validation has not run.")
        elif is_valid_fit_result(result):
            tone = "warn" if result.status == "warning" else "good"
            self.compat.set_value(result.headline, tone, result.message)
        else:
            self.compat.set_value(result.headline, "bad", result.message)
        self.packet.set_value(packet_type, "normal", "One Tool, Machine, and EOAT")
        self.generated.set_value(datetime.now().strftime("%b %d, %Y %I:%M %p").replace(" 0", " "), "normal", "Updated just now")


class ChangeoverValidationSummary(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.set_glass(alpha=94, border_alpha=72, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        self.setMinimumHeight(132)
        self.setMaximumHeight(148)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(10)
        title = QLabel("Changeover Summary")
        title.setObjectName("PacketBuilderSectionTitle")
        layout.addWidget(title)
        metrics = QWidget()
        metrics.setObjectName("PacketBuilderSummaryMetrics")
        metric_layout = QHBoxLayout(metrics)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(22)
        self.from_metric = SummaryMetric("FROM Setup", "Incomplete", "warn", "status")
        self.to_metric = SummaryMetric("TO Setup", "Incomplete", "warn", "status")
        self.change_metric = SummaryMetric("What Changes", "Pending", "warn", "swap")
        metric_layout.addWidget(self.from_metric, 1)
        metric_layout.addWidget(self.to_metric, 1)
        metric_layout.addWidget(self.change_metric, 2)
        layout.addWidget(metrics)

    def set_changeover(
        self,
        from_setup: PacketSetup,
        to_setup: PacketSetup,
        from_result: FitCheckResult | None,
        to_result: FitCheckResult | None,
        changes: tuple[str, ...],
    ) -> None:
        self._set_metric(self.from_metric, from_setup, from_result)
        self._set_metric(self.to_metric, to_setup, to_result)
        if not (from_setup.complete() and to_setup.complete()):
            self.change_metric.set_value("Pending", "warn", "Complete both setups to compare requirements.")
        else:
            note = _compact_change_summary(changes)
            tone = "good" if is_valid_fit_result(from_result) and is_valid_fit_result(to_result) else "warn"
            self.change_metric.set_value("Compared", tone, note)

    def _set_metric(self, metric: SummaryMetric, setup: PacketSetup, result: FitCheckResult | None) -> None:
        if not setup.complete():
            metric.set_value("Incomplete", "warn", "Select Tool, Machine, and EOAT.")
        elif is_valid_fit_result(result):
            metric.set_value(result.headline, "good" if result.status == "compatible" else "warn", result.message)
        elif result is not None:
            metric.set_value(result.headline, "bad", result.message)
        else:
            metric.set_value("Incomplete", "warn", "Validation has not run.")


class SummaryMetric(QWidget):
    def __init__(self, title: str, value: str, tone: str, glyph: str, parent=None):
        super().__init__(parent)
        self.icon = QLabel()
        self.icon.setFixedSize(40, 40)
        self.title = QLabel(title)
        self.title.setObjectName("PacketBuilderStatusTitle")
        self.value = QLabel(value)
        self.value.setObjectName("PacketBuilderStatusValue")
        self.note = QLabel("")
        self.note.setObjectName("PacketBuilderMuted")
        self.note.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.icon.setPixmap(glyph_icon(glyph if glyph != "time" else "status", QColor("#dfeeff"), 32).pixmap(32, 32))
        layout.addWidget(self.icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.title)
        text.addWidget(self.value)
        text.addWidget(self.note)
        layout.addLayout(text, 1)
        self.set_value(value, tone, "")

    def set_value(self, value: str, tone: str, note: str) -> None:
        self.value.setText(value)
        self.value.setProperty("tone", tone)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        self.note.setText(note)


class PacketTypeCard(GlassPanel):
    clicked = Signal()

    def __init__(self, title: str, subtitle: str, glyph: str, parent=None):
        super().__init__(parent, radius=8)
        self.title_text = title
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(82)
        self.icon = QLabel()
        self.icon.setFixedSize(38, 38)
        self.title = QLabel(title)
        self.title.setObjectName("PacketBuilderCardTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("PacketBuilderCardSubtitle")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(16)
        self.icon.setPixmap(glyph_icon(glyph, ACCENT_BRIGHT, 32).pixmap(32, 32))
        layout.addWidget(self.icon)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(self.title)
        text.addWidget(self.subtitle)
        layout.addLayout(text, 1)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.set_glass(
            alpha=132 if selected else 78,
            border_alpha=208 if selected else 76,
            border_color=QColor("#1f87ff" if selected else "#286fa8"),
            fill_color=QColor("#071a35" if selected else "#061329"),
            outer_glow_alpha=34 if selected else 0,
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class RecentPacketRow(GlassPanel):
    reload_requested = Signal(object)
    generate_requested = Signal(object)
    open_pdf_requested = Signal(object)

    def __init__(self, packet: RecentPacket, parent=None):
        super().__init__(parent, radius=7)
        self.packet = packet
        self.set_glass(alpha=96, border_alpha=72, border_color=QColor("#286fa8"), fill_color=QColor("#061329"))
        self.setMinimumHeight(68)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(14)
        icon = QLabel()
        icon.setFixedSize(34, 34)
        icon.setPixmap(glyph_icon("doc", QColor("#dfeeff"), 30).pixmap(30, 30))
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(packet.title())
        title.setObjectName("PacketBuilderCardTitle")
        summary = QLabel(packet.summary())
        summary.setObjectName("PacketBuilderMuted")
        text.addWidget(title)
        text.addWidget(summary)
        layout.addLayout(text, 1)
        meta = QLabel(_packet_time(packet.updated_at))
        meta.setObjectName("PacketBuilderMuted")
        layout.addWidget(meta)
        pill = QLabel(packet.status)
        pill.setObjectName("PacketBuilderPill")
        pill.setProperty("tone", "generated" if packet.status.casefold() == "generated" else "draft")
        layout.addWidget(pill)
        open_button = _packet_button("", "icon", "external")
        open_button.setToolTip("Open/reload packet")
        open_button.clicked.connect(lambda: self.reload_requested.emit(self.packet))
        layout.addWidget(open_button)
        if packet.status.casefold() == "generated":
            pdf_button = _packet_button("", "icon", "doc")
            pdf_button.setToolTip("Open generated PDF")
            pdf_button.clicked.connect(lambda: self.open_pdf_requested.emit(self.packet))
            layout.addWidget(pdf_button)
        else:
            generate_button = _packet_button("", "icon", "doc")
            generate_button.setToolTip("Generate PDF")
            generate_button.clicked.connect(lambda: self.generate_requested.emit(self.packet))
            layout.addWidget(generate_button)


class PacketPreviewOverlay(AnimatedGlassPanel):
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=16)
        self.set_glass(alpha=236, border_alpha=184, border_color=QColor("#8cc4ff"), fill_color=QColor("#020b1b"), outer_glow_alpha=78)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        self.title = QLabel("Packet Preview")
        self.title.setObjectName("PacketBuilderOverlayTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("PacketBuilderOverlaySubtitle")
        title_block.addWidget(self.title)
        title_block.addWidget(self.subtitle)
        close = CloseIconButton(size=34)
        close.clicked.connect(self.close_requested.emit)
        header.addLayout(title_block)
        header.addStretch(1)
        header.addWidget(close)
        layout.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("PacketBuilderScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("PacketBuilderOverlayBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(12)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)

    def set_packet(
        self,
        *,
        packet_type: str,
        setup: PacketSetup,
        from_setup: PacketSetup,
        to_setup: PacketSetup,
        setup_result: FitCheckResult | None,
        from_result: FitCheckResult | None,
        to_result: FitCheckResult | None,
        change_summary: tuple[str, ...],
    ) -> None:
        clear_layout(self.body_layout)
        if packet_type == PACKET_TYPE_CHANGEOVER:
            self.title.setText("Changeover Packet")
            self.subtitle.setText(f"FROM {from_setup.summary()}  |  TO {to_setup.summary()}")
            self._add_section("Validation", [_result_line("FROM", from_result), _result_line("TO", to_result)])
            self._add_section("What Changes", list(change_summary))
            for phase, items in changeover_checklist():
                self._add_section(phase, list(items))
        else:
            self.title.setText("Setup Packet")
            self.subtitle.setText(setup.summary())
            self._add_section("Validation", [_result_line("Setup", setup_result)])
            self._add_section("Setup Checklist", list(setup_checklist()))
        self.body_layout.addStretch(1)

    def _add_section(self, title: str, lines: list[str]) -> None:
        card = GlassPanel(radius=10)
        card.set_glass(alpha=118, border_alpha=88, border_color=QColor("#2b86e7"), fill_color=QColor("#061329"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("PacketBuilderOverlaySection")
        layout.addWidget(label)
        for line in lines:
            text = QLabel(str(line or "Not listed"))
            text.setObjectName("PacketBuilderOverlayText")
            text.setWordWrap(True)
            layout.addWidget(text)
        self.body_layout.addWidget(card)


class PacketBuilderStatusLine(QWidget):
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


def _tool_option(record: ToolRecord) -> SelectorOption:
    secondary = display_value(getattr(record, "part_description", "")) or display_value(getattr(record, "part_family", "")) or "Tool profile"
    keywords = " ".join(
        [
            getattr(record, "label", ""),
            getattr(record, "part_description", ""),
            getattr(record, "part_family", ""),
            " ".join(getattr(record, "molds", ()) or ()),
            " ".join(getattr(record, "parts", ()) or ()),
            " ".join(getattr(record, "compatible_eoats", ()) or ()),
            " ".join(getattr(record, "compatible_machines", ()) or ()),
        ]
    )
    return SelectorOption(key=record.tool, display=record.tool, secondary=secondary, kind="tool", keywords=keywords, raw_record=record)


def _machine_option(record: MachineRecord) -> SelectorOption:
    secondary = display_value(getattr(record, "robot_type", "")) or display_value(getattr(record, "robot_model", "")) or "Machine profile"
    keywords = " ".join([getattr(record, "label", ""), getattr(record, "current_eoat", ""), " ".join(getattr(record, "compatible_eoats", ()) or ()), " ".join(getattr(record, "compatible_tools", ()) or ())])
    return SelectorOption(key=record.machine, display=machine_label(record.machine), secondary=secondary, kind="machine", keywords=keywords, raw_record=record)


def _eoat_option(record: EOATRecord) -> SelectorOption:
    secondary = display_value(getattr(record, "eoat_type", "")) or display_value(getattr(record, "status", "")) or "EOAT profile"
    keywords = " ".join(
        [
            getattr(record, "display_id", ""),
            getattr(record, "status", ""),
            getattr(record, "part_description", ""),
            getattr(record, "part_family", ""),
            getattr(record, "connection_type", ""),
            " ".join(getattr(record, "tools", ()) or ()),
            " ".join(getattr(record, "machines", ()) or ()),
            " ".join(getattr(record, "parts", ()) or ()),
        ]
    )
    return SelectorOption(key=record.eoat_id, display=record.eoat_id, secondary=secondary, kind="eoat", keywords=keywords, raw_record=record)


def _packet_button(text: str, tone: str, glyph: str) -> QPushButton:
    button = QPushButton(text)
    if tone == "primary":
        button.setObjectName("PacketBuilderPrimaryButton")
        button.setFixedHeight(42)
        button.setMinimumWidth(156)
        button.setStyleSheet(PACKET_BUILDER_PRIMARY_ACTION_STYLE)
    elif tone == "icon":
        button.setObjectName("PacketBuilderIconButton")
        button.setFixedSize(38, 38)
    else:
        button.setObjectName("PacketBuilderSecondaryButton" if tone == "secondary" else "PacketBuilderGhostButton")
        button.setFixedHeight(40)
        button.setMinimumWidth(116)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if glyph:
        button.setIcon(glyph_icon(glyph, QColor("#ffffff"), 16))
        button.setIconSize(QSize(16, 16))
    return button


def _result_line(label: str, result: FitCheckResult | None) -> str:
    if result is None:
        return f"{label}: Incomplete"
    return f"{label}: {result.headline} - {result.message}"


def _compact_change_summary(changes: tuple[str, ...]) -> str:
    items = [str(item or "").strip() for item in changes if str(item or "").strip()]
    if not items:
        return "No major setup requirement changes detected."
    visible = items[:3]
    summary = "; ".join(visible)
    remaining = len(items) - len(visible)
    if remaining > 0:
        summary = f"{summary} (+{remaining} more)"
    return summary


def _packet_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return ""
    time_text = parsed.strftime("%I:%M %p").lstrip("0")
    if parsed.date() == datetime.now().date():
        return f"Today, {time_text}"
    return f"{parsed.strftime('%b')} {parsed.day}, {time_text}"


__all__ = ["AtlasMinimalistPacketBuilderPage", "MinimalistPacketBuilderContent"]
