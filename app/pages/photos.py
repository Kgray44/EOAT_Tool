from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

try:
    from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QScrollArea,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QEvent = QPoint = QTimer = Qt = QPixmap = None
    QApplication = QAbstractItemView = QCheckBox = QComboBox = QDialog = QFormLayout = QGridLayout = QGroupBox = (
        QHBoxLayout
    ) = QLabel = QLineEdit = QListWidget = QListWidgetItem = QPushButton = QScrollArea = QTabWidget = QTableWidget = (
        QTableWidgetItem
    ) = QTextEdit = QVBoxLayout = QWidget = None

if QComboBox is not None:

    class LookupComboBox(QComboBox):
        """Editable combo that keeps the QLineEdit-style API used by this page."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setEditable(True)
            self.setMinimumContentsLength(18)
            self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            completer = self.completer()
            if Qt is not None and completer is not None:
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        @property
        def editingFinished(self):
            return self.lineEdit().editingFinished

        def text(self) -> str:
            raw = self.currentText().strip()
            index = self.currentIndex()
            if index >= 0 and raw == self.itemText(index).strip():
                value = self.currentData()
                if value is not None and str(value).strip():
                    return str(value).strip()
            if " | " in raw:
                return raw.split(" | ", 1)[0].strip()
            return raw

        def setText(self, value: object) -> None:
            self.set_lookup_text(value)

        def set_lookup_text(self, value: object, *, block_signals: bool = False) -> None:
            previous_blocked = self.blockSignals(True) if block_signals else None
            try:
                text = str(value or "").strip()
                index = self.findData(text)
                if index < 0:
                    index = self.findText(text)
                if index >= 0:
                    self.setCurrentIndex(index)
                else:
                    self.setCurrentIndex(-1)
                    self.setEditText(text)
            finally:
                if previous_blocked is not None:
                    self.blockSignals(previous_blocked)

else:  # pragma: no cover
    LookupComboBox = None

from app.page_tasks import run_tool_background
from app.task_runner import TaskRequest, get_task_manager
from app.widgets.tool_run_panel import ToolRunPanel
from core.audit_constants import ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD
from core.audit_field_links import friendly_audit_field_label, parse_audit_field_link
from core.eoat_ids import (
    EOAT_ASSEMBLY_ID_FIELD,
    build_eoat_assembly_contexts,
    normalize_eoat_assembly_id,
    update_eoat_info_file,
)
from core.openers import open_path
from core.paths import get_press_capacity_file, resolve_project_paths
from core.photo_evidence import (
    audit_photo_intake_folder,
    create_audit_photo_intake_folder,
    evidence_coverage_for_audit,
    export_photo_checklist,
    indexed_photos_for_audit,
    indexed_photos_for_eoat,
    link_photo_to_audit_field,
    linked_audit_field_for_photo,
    resolve_indexed_photo_path,
)
from core.photo_indexing import (
    PHOTO_VIEW_FOLDERS,
    ensure_eoat_photo_category_folder,
    eoat_photo_root,
    intake_photos,
    list_incoming_photos,
    preview_photo_intake,
    repair_audit_photo_ties,
    repair_photo_eoat_links,
)
from core.photo_thumbnails import (
    STATUS_NOT_READY,
    STATUS_READY,
    PhotoThumbnailResult,
    ThumbnailService,
)
from core.tool_fields import TOOL_FIELD
from core.workbook_cache import row_dicts_cached

if QWidget is not None:

    class PhotoHoverPreview(QWidget):
        def __init__(self, parent=None):
            flags = Qt.WindowType.ToolTip if Qt is not None else None
            super().__init__(parent, flags) if flags is not None else super().__init__(parent)
            if Qt is not None:
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setObjectName("PhotoHoverPreview")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(6)
            self.image_label = QLabel("Generating preview...")
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setFixedSize(300, 230)
            self.info_label = QLabel("")
            self.info_label.setWordWrap(True)
            layout.addWidget(self.image_label)
            layout.addWidget(self.info_label)
            self.setStyleSheet(
                "QWidget#PhotoHoverPreview { background: #f8fafc; border: 1px solid #94a3b8; "
                "border-radius: 6px; } QLabel { color: #0f172a; }"
            )

        def show_loading(self, info_text: str, global_pos) -> None:
            self.image_label.clear()
            self.image_label.setText("Generating preview...")
            self.info_label.setText(info_text)
            self._show_near(global_pos)

        def show_result(self, result: PhotoThumbnailResult | None, info_text: str, global_pos) -> None:
            self.image_label.clear()
            if result is not None and result.ready and QPixmap is not None:
                pixmap = QPixmap(str(result.thumbnail_path))
                if not pixmap.isNull() and Qt is not None:
                    self.image_label.setPixmap(
                        pixmap.scaled(
                            self.image_label.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                else:
                    self.image_label.setText("Preview unavailable")
            elif result is not None and result.status != STATUS_NOT_READY:
                self.image_label.setText("Preview unavailable")
            else:
                self.image_label.setText("Generating preview...")
            self.info_label.setText(info_text)
            self._show_near(global_pos)

        def _show_near(self, global_pos) -> None:
            if QPoint is None or QApplication is None:
                self.show()
                return
            self.adjustSize()
            target = global_pos + QPoint(18, 18)
            screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
            if screen is not None:
                rect = screen.availableGeometry()
                target.setX(min(max(rect.left(), target.x()), max(rect.left(), rect.right() - self.width())))
                target.setY(min(max(rect.top(), target.y()), max(rect.top(), rect.bottom() - self.height())))
            self.move(target)
            self.show()


    class PhotoLightboxDialog(QDialog):
        def __init__(self, paths: list[str], start_index: int, parent=None):
            super().__init__(parent)
            self.paths = paths
            self.index = max(0, min(start_index, len(paths) - 1)) if paths else 0
            self.setWindowTitle("Photo Preview")
            self.resize(860, 720)
            layout = QVBoxLayout(self)
            self.title_label = QLabel("")
            self.title_label.setStyleSheet("font-size: 13pt; font-weight: 600;")
            self.position_label = QLabel("")
            self.position_label.setStyleSheet("color: #475569;")
            self.image_label = QLabel("Generating preview...")
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setMinimumSize(760, 500)
            self.image_label.setStyleSheet("background: #0f172a; color: #f8fafc; border-radius: 4px;")
            self.details_label = QLabel("")
            self.details_label.setWordWrap(True)
            controls = QHBoxLayout()
            self.previous_button = QPushButton("Previous")
            self.next_button = QPushButton("Next")
            self.use_button = QPushButton("Use Selected")
            close_button = QPushButton("Close")
            self.previous_button.clicked.connect(lambda: self.move_index(-1))
            self.next_button.clicked.connect(lambda: self.move_index(1))
            self.use_button.clicked.connect(self.confirm_current)
            close_button.clicked.connect(self.reject)
            controls.addWidget(self.previous_button)
            controls.addWidget(self.next_button)
            controls.addStretch(1)
            controls.addWidget(self.use_button)
            controls.addWidget(close_button)
            layout.addWidget(self.title_label)
            layout.addWidget(self.position_label)
            layout.addWidget(self.image_label, stretch=1)
            layout.addWidget(self.details_label)
            layout.addLayout(controls)

        @property
        def current_path(self) -> str:
            return self.paths[self.index] if self.paths else ""

        def set_current_pending(self, info_text: str) -> None:
            path = self.current_path
            self.title_label.setText(Path(path).name if path else "Photo Preview")
            self.position_label.setText(f"{self.index + 1} of {len(self.paths)}" if self.paths else "")
            self.details_label.setText(info_text)
            self.image_label.clear()
            self.image_label.setText("Generating preview...")
            self.previous_button.setEnabled(len(self.paths) > 1)
            self.next_button.setEnabled(len(self.paths) > 1)

        def set_thumbnail(self, path: str, result: PhotoThumbnailResult | None, info_text: str) -> None:
            if path != self.current_path:
                return
            self.details_label.setText(info_text)
            self.image_label.clear()
            if result is not None and result.ready and QPixmap is not None:
                pixmap = QPixmap(str(result.thumbnail_path))
                if not pixmap.isNull() and Qt is not None:
                    self.image_label.setPixmap(
                        pixmap.scaled(
                            self.image_label.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    return
            self.image_label.setText("Preview unavailable" if result is not None else "Generating preview...")

        def move_index(self, delta: int) -> None:
            if not self.paths:
                return
            self.index = (self.index + delta) % len(self.paths)
            parent = self.parent()
            if hasattr(parent, "_load_lightbox_current"):
                parent._load_lightbox_current()

        def confirm_current(self) -> None:
            parent = self.parent()
            if hasattr(parent, "_confirm_preview_photo"):
                parent._confirm_preview_photo(self.current_path)

        def keyPressEvent(self, event) -> None:
            if Qt is not None:
                key = event.key()
                if key == Qt.Key.Key_Escape:
                    self.reject()
                    return
                if key == Qt.Key.Key_Left:
                    self.move_index(-1)
                    return
                if key == Qt.Key.Key_Right:
                    self.move_index(1)
                    return
                if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self.confirm_current()
                    return
            super().keyPressEvent(event)


    class PhotoContactSheetDialog(QDialog):
        def __init__(self, paths: list[str], parent=None):
            super().__init__(parent)
            self.paths = paths
            self._image_labels: dict[str, QLabel] = {}
            self._detail_labels: dict[str, QLabel] = {}
            self.setWindowTitle("Selected Photo Previews")
            self.resize(900, 680)
            layout = QVBoxLayout(self)
            title = QLabel(f"Selected photos ({len(paths)})")
            title.setStyleSheet("font-size: 13pt; font-weight: 600;")
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            container = QWidget()
            grid = QGridLayout(container)
            grid.setContentsMargins(8, 8, 8, 8)
            grid.setSpacing(10)
            for index, path in enumerate(paths):
                cell = QWidget()
                cell.setStyleSheet("background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px;")
                cell_layout = QVBoxLayout(cell)
                cell_layout.setContentsMargins(8, 8, 8, 8)
                image = QLabel("Generating preview...")
                image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image.setFixedSize(190, 145)
                detail = QLabel(Path(path).name)
                detail.setWordWrap(True)
                detail.setStyleSheet("color: #0f172a;")
                cell_layout.addWidget(image)
                cell_layout.addWidget(detail)
                grid.addWidget(cell, index // 4, index % 4)
                self._image_labels[path] = image
                self._detail_labels[path] = detail
            scroll.setWidget(container)
            close_button = QPushButton("Close")
            close_button.clicked.connect(self.reject)
            layout.addWidget(title)
            layout.addWidget(scroll, stretch=1)
            layout.addWidget(close_button)

        def set_thumbnail(self, path: str, result: PhotoThumbnailResult | None, info_text: str) -> None:
            image = self._image_labels.get(path)
            detail = self._detail_labels.get(path)
            if image is None or detail is None:
                return
            detail.setText(info_text)
            image.clear()
            if result is not None and result.ready and QPixmap is not None:
                pixmap = QPixmap(str(result.thumbnail_path))
                if not pixmap.isNull() and Qt is not None:
                    image.setPixmap(
                        pixmap.scaled(
                            image.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    return
            image.setText("Preview unavailable" if result is not None else "Generating preview...")

else:  # pragma: no cover
    PhotoHoverPreview = PhotoLightboxDialog = PhotoContactSheetDialog = None


class PhotosPage(QWidget):
    BATCH_INCLUDE_COL = 0
    BATCH_SOURCE_COL = 1
    BATCH_TARGET_COL = 2
    BATCH_VIEW_COL = 3
    BATCH_DESCRIPTION_COL = 4
    BATCH_AUDIT_COL = 5
    BATCH_ISSUE_COL = 6
    BATCH_FIELD_COL = 7

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.thumbnail_service = ThumbnailService(self.config.project_root)
        self.audit_lookup_rows: list[dict[str, object]] = []
        self.issue_lookup_rows: list[dict[str, object]] = []
        self.tool_lookup_rows: list[dict[str, object]] = []
        self.eoat_contexts = {}
        self._press_machine = ""
        self._part_name = ""
        self.next_shot_type = "Front View"
        self._incoming_paths: list[str] = []
        self._incoming_generation = 0
        self._hover_pending_path = ""
        self._hover_pending_pos = QPoint(0, 0) if QPoint is not None else None
        self._hover_current_path = ""
        self._hover_preview = PhotoHoverPreview(self) if PhotoHoverPreview is not None else None
        self._hover_timer = QTimer(self) if QTimer is not None else None
        if self._hover_timer is not None:
            self._hover_timer.setSingleShot(True)
            self._hover_timer.setInterval(250)
            self._hover_timer.timeout.connect(self._show_pending_hover_preview)
        self._thumbnail_callbacks: dict[str, list[tuple[int, object]]] = {}
        self._thumbnail_task_counter = 0
        self._photo_preview_dialog = None
        self._contact_sheet_dialog = None
        layout = QVBoxLayout(self)
        heading = QLabel("EOAT Photo Intake")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        top = QHBoxLayout()
        left = QVBoxLayout()
        button_row = QHBoxLayout()
        for label, callback in [
            ("Refresh Incoming Photos", self.refresh_incoming),
            ("Preview Selected Photos", self.preview_selected_photos),
            ("Open Incoming Photos Folder", self.open_incoming),
            ("Open Cell Photos Folder", self.open_cell_photos),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        left.addLayout(button_row)
        self.incoming_list = QListWidget()
        self.incoming_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.incoming_list.setMouseTracking(True)
        self.incoming_list.itemDoubleClicked.connect(self.open_photo_preview_for_item)
        self.incoming_list.currentItemChanged.connect(lambda _current, _previous: self._autofill_date_from_selected_photo())
        self.incoming_list.itemSelectionChanged.connect(self._autofill_date_from_selected_photo)
        self.incoming_list.installEventFilter(self)
        self.incoming_list.viewport().setMouseTracking(True)
        self.incoming_list.viewport().installEventFilter(self)
        if QAbstractItemView is not None:
            self.incoming_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        incoming_label = QLabel("Incoming photos")
        incoming_label.setStyleSheet("font-weight: 600;")
        left.addWidget(incoming_label)
        self.empty_hint = QLabel("")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setStyleSheet("color: #627d98;")
        left.addWidget(self.empty_hint)
        left.addWidget(self.incoming_list)
        top.addLayout(left, stretch=2)

        form_container = QWidget()
        form = QFormLayout(form_container)
        self.plant_combo = QComboBox()
        self.plant_combo.addItems(["Whiteroom", "Cleanroom"])
        self.eoat_combo = QComboBox()
        self.eoat_combo.setEditable(True)
        self.eoat_combo.setMinimumContentsLength(28)
        self.eoat_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        eoat_completer = self.eoat_combo.completer()
        if Qt is not None and eoat_completer is not None:
            eoat_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.eoat_combo.currentIndexChanged.connect(self.apply_selected_eoat)
        self.eoat_combo.editTextChanged.connect(lambda _text: self._update_eoat_context())
        self.tool_combo = QComboBox()
        self.tool_combo.setEditable(True)
        self.tool_combo.setMinimumContentsLength(26)
        self.tool_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        tool_completer = self.tool_combo.completer()
        if Qt is not None and tool_completer is not None:
            tool_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tool_combo.currentIndexChanged.connect(self.apply_selected_tool)
        self.tool_combo.editTextChanged.connect(self._manual_tool_text_changed)
        self.date_edit = QLineEdit(date.today().isoformat())
        self.date_edit.setPlaceholderText("Autofills from the selected photo")
        self.view_combo = QComboBox()
        self.view_combo.addItems(list(PHOTO_VIEW_FOLDERS.keys()))
        self.audit_context_label = QLabel("")
        self.audit_context_label.setWordWrap(True)
        self.audit_context_label.setStyleSheet("color: #475569;")
        self.eoat_context_label = QLabel("")
        self.eoat_context_label.setWordWrap(True)
        self.eoat_context_label.setStyleSheet("color: #475569;")
        self.audit_id_edit = LookupComboBox()
        self.issue_id_edit = LookupComboBox()
        self.audit_field_link_edit = QLineEdit()
        self.audit_field_link_edit.setPlaceholderText("audit_id=...;field_key=...;field_label=...")
        self.audit_field_link_edit.textChanged.connect(lambda _text: self._update_go_to_link_button())
        self.go_to_link_button = QPushButton("Go to Link")
        self.go_to_link_button.setToolTip("Return to the audit field linked to this photo.")
        self.go_to_link_button.clicked.connect(self.go_to_audit_field_link)
        self.link_display_label = QLabel("")
        self.link_display_label.setWordWrap(True)
        self.link_display_label.setStyleSheet("color: #475569;")
        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(70)
        self.notes_edit = QTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.copy_check = QCheckBox("Copy photos instead of moving originals")
        self.copy_check.setChecked(False)
        for label, widget in [
            ("Plant/Area", self.plant_combo),
            ("EOAT Assembly ID", self.eoat_combo),
            ("EOAT Context", self.eoat_context_label),
            ("Date Taken", self.date_edit),
            ("EOAT Area Shown", self.view_combo),
            ("Related Audit ID", self.audit_id_edit),
        ]:
            form.addRow(label, widget)
        form.addRow("Legacy Tool # Context", self.tool_combo)
        for label, widget in [
            ("Description", self.description_edit),
            ("Notes", self.notes_edit),
            ("", self.copy_check),
        ]:
            form.addRow(label, widget)

        advanced_toggle = QPushButton("Advanced Linking")
        advanced_toggle.setCheckable(True)
        form.addRow(advanced_toggle)
        advanced_group = QGroupBox("Advanced Linking")
        advanced_container = QWidget()
        advanced_form = QFormLayout(advanced_container)
        advanced_form.addRow("Related Issue ID", self.issue_id_edit)
        advanced_form.addRow("Audit Context", self.audit_context_label)
        link_row = QHBoxLayout()
        link_row.addWidget(self.audit_field_link_edit, stretch=1)
        link_row.addWidget(self.go_to_link_button)
        advanced_form.addRow("Link to Audit Field", link_row)
        advanced_form.addRow("Linked Target", self.link_display_label)
        advanced_layout = QVBoxLayout(advanced_group)
        advanced_layout.addWidget(advanced_container)
        advanced_container.setVisible(False)
        advanced_toggle.toggled.connect(advanced_container.setVisible)
        advanced_toggle.toggled.connect(advanced_group.setVisible)
        advanced_group.setVisible(False)
        form.addRow(advanced_group)
        preview_button = QPushButton("Preview Intake")
        preview_button.clicked.connect(self.preview_plan)
        confirm_button = QPushButton("Save Photos to EOAT Folder")
        confirm_button.clicked.connect(self.confirm_intake)
        form.addRow(preview_button, confirm_button)
        top.addWidget(form_container, stretch=1)
        layout.addLayout(top, stretch=2)

        lower_tabs = QTabWidget()

        evidence_tab = QWidget()
        evidence_layout = QVBoxLayout(evidence_tab)
        evidence_actions = QHBoxLayout()
        for label, callback in [
            ("Refresh Coverage", self.refresh_evidence_coverage),
            ("Use Next Missing Shot Type", self.use_next_missing_shot_type),
            ("Create EOAT Photo Folder", self.create_eoat_photo_folder),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            evidence_actions.addWidget(button)
        evidence_layout.addLayout(evidence_actions)
        self.missing_shots_label = QLabel("")
        self.missing_shots_label.setWordWrap(True)
        self.missing_shots_label.setStyleSheet("color: #9f1239; font-weight: 600;")
        evidence_layout.addWidget(self.missing_shots_label)
        self.evidence_table = QTableWidget(0, 5)
        self.evidence_table.setHorizontalHeaderLabels(["Shot Type", "Required", "Present", "Photos", "Status"])
        evidence_layout.addWidget(self.evidence_table, stretch=1)
        lower_tabs.addTab(evidence_tab, "Evidence Coverage")

        indexed_tab = QWidget()
        indexed_layout = QVBoxLayout(indexed_tab)
        indexed_actions = QHBoxLayout()
        for label, callback in [
            ("Open Photo", self.open_selected_indexed_photo),
            ("Open EOAT Folder", self.open_eoat_photo_folder),
            ("Link Photo to Audit Field", self.link_selected_photo_to_field),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            indexed_actions.addWidget(button)
        indexed_layout.addLayout(indexed_actions)
        self.indexed_photos_table = QTableWidget(0, 5)
        self.indexed_photos_table.setHorizontalHeaderLabels(
            ["Area", "Filename", "Date Taken", "Description", "Linked Audit Field"]
        )
        self.indexed_photos_table.itemSelectionChanged.connect(self._update_go_to_link_button)
        indexed_layout.addWidget(self.indexed_photos_table, stretch=1)
        lower_tabs.addTab(indexed_tab, "Indexed Photos")

        batch_tab = QWidget()
        batch_layout = QVBoxLayout(batch_tab)
        batch_actions = QHBoxLayout()
        for label, callback in [
            ("Build Batch Review", self.build_batch_review),
            ("Refresh Batch Preview", self.refresh_batch_preview),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            batch_actions.addWidget(button)
        batch_layout.addLayout(batch_actions)
        self.batch_table = QTableWidget(0, 8)
        self.batch_table.setHorizontalHeaderLabels(
            [
                "Include?",
                "Source filename",
                "Preview target filename",
                "EOAT Area Shown",
                "Description",
                "Related Audit ID",
                "Related Issue ID",
                "Linked Audit Field",
            ]
        )
        batch_layout.addWidget(self.batch_table, stretch=1)
        lower_tabs.addTab(batch_tab, "Batch Review")

        advanced_tools_tab = QWidget()
        advanced_tools_layout = QVBoxLayout(advanced_tools_tab)
        advanced_tools_actions = QGridLayout()
        for label, callback in [
            ("Repair Audit Photo Ties", self.repair_audit_photo_ties),
            ("Repair Photo EOAT Links", self.repair_photo_eoat_links),
            ("Export Photo Checklist", self.export_audit_photo_checklist),
            ("Copy Intake Path", self.copy_audit_intake_path),
            ("Open Cell Photos Folder", self.open_cell_photos),
            ("Refresh Indexed Photos", self.refresh_indexed_photos),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            index = advanced_tools_actions.count()
            advanced_tools_actions.addWidget(button, index // 3, index % 3)
        advanced_tools_layout.addLayout(advanced_tools_actions)
        advanced_tools_layout.addStretch(1)
        lower_tabs.addTab(advanced_tools_tab, "Advanced Tools")
        layout.addWidget(lower_tabs, stretch=2)

        self.result_panel = ToolRunPanel()
        layout.addWidget(self.result_panel, stretch=1)
        self.audit_id_edit.activated.connect(lambda _index: self.refresh_audit_context())
        self.audit_id_edit.editingFinished.connect(self.refresh_audit_context)
        self.view_combo.currentTextChanged.connect(lambda _text: self.refresh_batch_preview(show_result=False))
        self.refresh_audit_lookup()
        self.refresh_incoming()
        self._update_go_to_link_button()

    def refresh(self) -> None:
        self.refresh_audit_lookup()
        self.refresh_incoming()

    def refresh_incoming(self) -> None:
        self._cancel_preview_state(close_dialogs=True)
        self.incoming_list.clear()
        photos = list_incoming_photos(self.config.project_root)
        self._incoming_paths = [str(photo) for photo in photos]
        paths = resolve_project_paths(self.config.project_root)
        for photo in photos:
            item = QListWidgetItem(photo.name)
            item.setToolTip(str(photo))
            if Qt is not None:
                item.setData(Qt.ItemDataRole.UserRole, str(photo))
            self.incoming_list.addItem(item)
        if photos:
            self.incoming_list.setCurrentRow(0)
            self._autofill_date_from_selected_photo()
        if not photos:
            self.empty_hint.setText(
                "No incoming photos found.\n"
                "1. Click Open Incoming Photos Folder.\n"
                "2. Drop JPG, JPEG, PNG, HEIC, or HEIF images there.\n"
                "3. Click Refresh Incoming Photos.\n"
                "4. Fill metadata and confirm intake."
            )
            self.result_panel.show_text(f"Incoming folder:\n{paths.incoming_photos}")
        else:
            self.empty_hint.setText(f"{len(photos)} supported photo(s) ready for intake.")

    def selected_photos(self) -> list[str]:
        return [self._incoming_item_path(item) for item in self.incoming_list.selectedItems()]

    def _current_photo_path_for_metadata(self) -> str:
        item = self._current_or_first_selected_incoming_item()
        return self._incoming_item_path(item)

    def _autofill_date_from_selected_photo(self) -> None:
        path = self._current_photo_path_for_metadata()
        if not path:
            return
        generation = self._incoming_generation
        cached = self.thumbnail_service.cached_thumbnail(path)
        date_text = self._date_text_for_photo(path, cached)
        if date_text:
            self.date_edit.setText(date_text)
        if cached.status == STATUS_NOT_READY:
            self._queue_thumbnail(
                path,
                generation,
                lambda finished_path, result: self._apply_photo_date_if_current(
                    finished_path, result, generation
                ),
            )

    def _apply_photo_date_if_current(
        self, path: str, result: PhotoThumbnailResult, generation: int
    ) -> None:
        if generation != self._incoming_generation or path != self._current_photo_path_for_metadata():
            return
        date_text = self._date_text_for_photo(path, result)
        if date_text:
            self.date_edit.setText(date_text)

    def _date_text_for_photo(self, path: str, result: PhotoThumbnailResult | None = None) -> str:
        if result is not None and result.captured_at:
            captured = result.captured_at.strip()
            if len(captured) >= 10:
                return captured[:10]
            return captured
        source = Path(path)
        try:
            return datetime.fromtimestamp(source.stat().st_mtime).date().isoformat()
        except OSError:
            return ""

    def _incoming_item_path(self, item: QListWidgetItem | None) -> str:
        if item is None:
            return ""
        if Qt is not None:
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                return str(value)
        return item.toolTip() or item.text()

    def _current_or_first_selected_incoming_item(self) -> QListWidgetItem | None:
        current = self.incoming_list.currentItem()
        if current is not None:
            return current
        selected = self.incoming_list.selectedItems()
        return selected[0] if selected else None

    def _cancel_preview_state(self, *, close_dialogs: bool = False) -> None:
        self._incoming_generation += 1
        if self._hover_timer is not None:
            self._hover_timer.stop()
        self._hover_pending_path = ""
        self._hover_current_path = ""
        self._hide_hover_preview()
        if close_dialogs:
            for attr in ("_photo_preview_dialog", "_contact_sheet_dialog"):
                dialog = getattr(self, attr, None)
                if dialog is not None:
                    dialog.reject()
                    setattr(self, attr, None)

    def _hide_hover_preview(self) -> None:
        if self._hover_preview is not None:
            self._hover_preview.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.incoming_list and QEvent is not None and event.type() == QEvent.Type.KeyPress:
            return self._handle_incoming_key(event)
        if watched is self.incoming_list.viewport() and QEvent is not None:
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                item = self.incoming_list.itemAt(event.pos())
                self._schedule_hover_preview(item, self._event_global_pos(event))
            elif event_type in {QEvent.Type.Leave, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel}:
                self._hover_pending_path = ""
                if self._hover_timer is not None:
                    self._hover_timer.stop()
                self._hide_hover_preview()
        return super().eventFilter(watched, event)

    def _handle_incoming_key(self, event) -> bool:
        if Qt is None:
            return False
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.open_selected_photo_preview()
            return True
        if key == Qt.Key.Key_Left:
            self._move_incoming_selection(-1)
            return True
        if key == Qt.Key.Key_Right:
            self._move_incoming_selection(1)
            return True
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            item = self._current_or_first_selected_incoming_item()
            if item is not None:
                item.setSelected(True)
                self.result_panel.show_text(f"Selected {Path(self._incoming_item_path(item)).name} for photo intake.")
                return True
        return False

    def _move_incoming_selection(self, delta: int) -> None:
        count = self.incoming_list.count()
        if count <= 0:
            return
        row = self.incoming_list.currentRow()
        if row < 0:
            row = 0
        else:
            row = (row + delta) % count
        self.incoming_list.setCurrentRow(row)
        item = self.incoming_list.item(row)
        if item is not None:
            item.setSelected(True)

    def _event_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        return QPoint(0, 0) if QPoint is not None else None

    def _schedule_hover_preview(self, item: QListWidgetItem | None, global_pos) -> None:
        if item is None or global_pos is None:
            self._hover_pending_path = ""
            if self._hover_timer is not None:
                self._hover_timer.stop()
            self._hide_hover_preview()
            return
        path = self._incoming_item_path(item)
        self._hover_pending_path = path
        self._hover_pending_pos = global_pos
        if self._hover_current_path == path and self._hover_preview is not None and self._hover_preview.isVisible():
            self._render_hover_preview(path, self.thumbnail_service.cached_thumbnail(path), global_pos)
            return
        if self._hover_timer is not None:
            self._hover_timer.start()

    def _show_pending_hover_preview(self) -> None:
        path = self._hover_pending_path
        if not path or path not in self._incoming_paths:
            return
        self._hover_current_path = path
        generation = self._incoming_generation
        cached = self.thumbnail_service.cached_thumbnail(path)
        self._render_hover_preview(path, cached, self._hover_pending_pos)
        if cached.status == STATUS_NOT_READY:
            self._queue_thumbnail(
                path,
                generation,
                lambda finished_path, result: self._render_hover_if_current(finished_path, result, generation),
            )

    def _render_hover_if_current(self, path: str, result: PhotoThumbnailResult, generation: int) -> None:
        if generation != self._incoming_generation or path != self._hover_current_path:
            return
        if path not in self._incoming_paths:
            return
        self._render_hover_preview(path, result, self._hover_pending_pos)

    def _render_hover_preview(self, path: str, result: PhotoThumbnailResult | None, global_pos) -> None:
        if self._hover_preview is None or global_pos is None:
            return
        info_text = self._preview_info_text(path, result)
        if result is None or result.status == STATUS_NOT_READY:
            self._hover_preview.show_loading(info_text, global_pos)
        else:
            self._hover_preview.show_result(result, info_text, global_pos)

    def preview_selected_photos(self) -> None:
        selected = self.selected_photos()
        if len(selected) > 1:
            self._open_contact_sheet(selected)
            return
        self.open_selected_photo_preview()

    def open_photo_preview_for_item(self, item: QListWidgetItem) -> None:
        path = self._incoming_item_path(item)
        if not path:
            return
        start = self._incoming_paths.index(path) if path in self._incoming_paths else self.incoming_list.row(item)
        self._open_lightbox(start)

    def open_selected_photo_preview(self) -> None:
        item = self._current_or_first_selected_incoming_item()
        if item is None:
            self.result_panel.show_text("Select an incoming photo first.")
            return
        path = self._incoming_item_path(item)
        start = self._incoming_paths.index(path) if path in self._incoming_paths else self.incoming_list.row(item)
        self._open_lightbox(start)

    def _open_lightbox(self, start_index: int) -> None:
        if not self._incoming_paths:
            self.result_panel.show_text("No incoming photos are available to preview.")
            return
        if self._photo_preview_dialog is not None:
            self._photo_preview_dialog.reject()
        dialog = PhotoLightboxDialog(self._incoming_paths[:], start_index, self)
        self._photo_preview_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "_photo_preview_dialog", None))
        self._load_lightbox_current()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _load_lightbox_current(self) -> None:
        dialog = self._photo_preview_dialog
        if dialog is None:
            return
        path = dialog.current_path
        generation = self._incoming_generation
        cached = self.thumbnail_service.cached_thumbnail(path)
        dialog.set_current_pending(self._preview_info_text(path, cached))
        if cached.status == STATUS_NOT_READY:
            self._queue_thumbnail(
                path,
                generation,
                lambda finished_path, result: self._update_lightbox_thumbnail(finished_path, result, generation),
            )
        else:
            dialog.set_thumbnail(path, cached, self._preview_info_text(path, cached))

    def _update_lightbox_thumbnail(self, path: str, result: PhotoThumbnailResult, generation: int) -> None:
        dialog = self._photo_preview_dialog
        if dialog is None or generation != self._incoming_generation:
            return
        dialog.set_thumbnail(path, result, self._preview_info_text(path, result))

    def _open_contact_sheet(self, paths: list[str]) -> None:
        if self._contact_sheet_dialog is not None:
            self._contact_sheet_dialog.reject()
        dialog = PhotoContactSheetDialog(paths, self)
        self._contact_sheet_dialog = dialog
        generation = self._incoming_generation
        dialog.finished.connect(lambda _result: setattr(self, "_contact_sheet_dialog", None))
        for path in paths:
            cached = self.thumbnail_service.cached_thumbnail(path)
            dialog.set_thumbnail(path, cached if cached.status != STATUS_NOT_READY else None, self._preview_info_text(path, cached))
            if cached.status == STATUS_NOT_READY:
                self._queue_thumbnail(
                    path,
                    generation,
                    lambda finished_path, result: self._update_contact_sheet_thumbnail(
                        finished_path, result, generation
                    ),
                )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _update_contact_sheet_thumbnail(self, path: str, result: PhotoThumbnailResult, generation: int) -> None:
        dialog = self._contact_sheet_dialog
        if dialog is None or generation != self._incoming_generation:
            return
        dialog.set_thumbnail(path, result, self._preview_info_text(path, result))

    def _confirm_preview_photo(self, path: str) -> None:
        if self._select_incoming_path(path, exclusive=True):
            self.result_panel.show_text(f"Selected {Path(path).name} for photo intake.")
        if self._photo_preview_dialog is not None:
            self._photo_preview_dialog.accept()

    def _select_incoming_path(self, path: str, *, exclusive: bool = False) -> bool:
        matched = False
        if exclusive:
            self.incoming_list.clearSelection()
        for row in range(self.incoming_list.count()):
            item = self.incoming_list.item(row)
            if self._incoming_item_path(item) != path:
                continue
            self.incoming_list.setCurrentItem(item)
            item.setSelected(True)
            matched = True
            break
        return matched

    def _queue_thumbnail(self, path: str, generation: int, callback) -> None:
        callbacks = self._thumbnail_callbacks.setdefault(path, [])
        callbacks.append((generation, callback))
        if len(callbacks) > 1:
            return
        self._thumbnail_task_counter += 1
        task_id = f"photo_thumbnail_preview_{self._thumbnail_task_counter}"

        def _finished(task_result) -> None:
            callbacks_for_path = self._thumbnail_callbacks.pop(path, [])
            if isinstance(task_result.result_data, PhotoThumbnailResult):
                result = task_result.result_data
            else:
                result = PhotoThumbnailResult(Path(path), "error", error=task_result.error or task_result.message)
            for callback_generation, queued_callback in callbacks_for_path:
                if callback_generation == self._incoming_generation:
                    queued_callback(path, result)

        get_task_manager().run_task(
            TaskRequest(
                id=task_id,
                name="Photo Preview Thumbnail",
                category="photo-preview",
                callable=lambda: self.thumbnail_service.get_thumbnail(path),
            ),
            on_finished=_finished,
        )

    def _preview_info_text(self, path: str, result: PhotoThumbnailResult | None = None) -> str:
        source = Path(path)
        captured = result.captured_at if result is not None and result.captured_at else ""
        dimensions = ""
        if result is not None and result.width and result.height:
            dimensions = f"{result.width} x {result.height}"
        status = self._incoming_status_text(path)
        lines = [
            f"Filename: {source.name}",
            f"Captured: {captured or 'not available'}",
            f"Dimensions: {dimensions or 'not available'}",
            f"Status/tags: {status}",
        ]
        if result is not None and result.status == STATUS_NOT_READY:
            lines.append("Generating preview...")
        elif result is not None and result.status != STATUS_READY and result.error:
            lines.append(result.error)
        elif not captured:
            lines.append(f"File modified: {self._file_modified_text(source)}")
        return "\n".join(lines)

    def _incoming_status_text(self, path: str) -> str:
        tags: list[str] = []
        if path in self.selected_photos():
            tags.append("selected")
        data = self.metadata()
        if data["view_type"]:
            tags.append(f"area {data['view_type']}")
        if data["related_audit_id"]:
            tags.append(f"audit {data['related_audit_id']}")
        if data["related_issue_id"]:
            tags.append(f"issue {data['related_issue_id']}")
        label = friendly_audit_field_label(data["audit_field_link"])
        if label:
            tags.append(label)
        return "; ".join(tags) if tags else "ready for intake"

    def _file_modified_text(self, path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            return "not available"

    def hideEvent(self, event) -> None:
        self._cancel_preview_state(close_dialogs=True)
        super().hideEvent(event)

    def refresh_audit_lookup(self) -> None:
        self.audit_lookup_rows = self._load_audit_rows()
        self.issue_lookup_rows = self._load_issue_rows()
        self.eoat_contexts = build_eoat_assembly_contexts(
            self.audit_lookup_rows,
            press_capacity_path=get_press_capacity_file(self.config.project_root),
        )
        self._populate_eoat_options()
        self._populate_related_audit_options()
        self._populate_related_issue_options()
        self._populate_tool_options()

    def _load_audit_rows(self) -> list[dict[str, object]]:
        paths = resolve_project_paths(self.config.project_root)
        if not paths.master_workbook.exists():
            return []
        try:
            return [
                dict(row)
                for row in row_dicts_cached(paths.master_workbook, "EOAT Inventory")
                if str(row.get("Audit ID") or "").strip()
            ]
        except Exception:
            return []

    def _load_issue_rows(self) -> list[dict[str, object]]:
        paths = resolve_project_paths(self.config.project_root)
        if not paths.master_workbook.exists():
            return []
        try:
            return [
                dict(row)
                for row in row_dicts_cached(paths.master_workbook, "Issue Log")
                if str(row.get("Issue ID") or "").strip()
            ]
        except Exception:
            return []

    def _audit_lookup_label(self, row: dict[str, object]) -> str:
        machine = self._machine_context(row)
        parts = [
            str(row.get("Audit ID") or "").strip(),
            f"Machine {machine}" if machine else "",
            f"Tool {row.get(TOOL_FIELD)}" if str(row.get(TOOL_FIELD) or "").strip() else "",
            str(row.get("Part Family") or "").strip(),
            str(row.get("Part Name/Description") or "").strip(),
        ]
        return " | ".join(part for part in parts if part)

    def _issue_lookup_label(self, row: dict[str, object]) -> str:
        parts = [
            str(row.get("Issue ID") or "").strip(),
            str(row.get("Press/Machine #") or "").strip(),
            str(row.get("Issue Category") or "").strip(),
            str(row.get("Status") or "").strip(),
        ]
        return " | ".join(part for part in parts if part)

    def _tool_lookup_label(self, row: dict[str, object]) -> str:
        parts = [
            str(row.get(TOOL_FIELD) or "").strip(),
            str(row.get("Press/Machine #") or "").strip(),
            str(row.get("Audit ID") or "").strip(),
            str(row.get("Part Family") or "").strip(),
            str(row.get("Part Name/Description") or "").strip(),
            str(row.get("Status") or "").strip(),
        ]
        return " | ".join(part for part in parts if part)

    def _tool_option_label(self, row: dict[str, object]) -> str:
        tool = str(row.get(TOOL_FIELD) or "").strip()
        machine = self._machine_context(row)
        return f"{tool} ({machine})" if tool and machine else tool

    def _populate_eoat_options(self) -> None:
        current = self._current_eoat_id()
        self.eoat_combo.blockSignals(True)
        self.eoat_combo.clear()
        self.eoat_combo.addItem("Select EOAT Assembly ID", "")
        for context in sorted(self.eoat_contexts.values(), key=lambda item: item.eoat_assembly_id.casefold()):
            self.eoat_combo.addItem(self._eoat_option_label(context), context.eoat_assembly_id)
            if Qt is not None:
                self.eoat_combo.setItemData(
                    self.eoat_combo.count() - 1,
                    "\n".join(
                        [
                            context.eoat_assembly_id,
                            "Tools: " + ", ".join(context.tools),
                            "Known machines: " + ", ".join(context.known_machines),
                            "Audit machines: " + ", ".join(context.machines),
                            "Press Capacity machines: " + ", ".join(context.capacity_machines),
                        ]
                    ),
                    Qt.ItemDataRole.ToolTipRole,
                )
        self.eoat_combo.blockSignals(False)
        if current:
            self._set_eoat_combo_value(current)
        self._update_eoat_context()

    def _eoat_option_label(self, context) -> str:
        parts = [context.eoat_assembly_id]
        if context.known_machines:
            parts.append("Machines " + ", ".join(context.known_machines))
        if context.tools:
            parts.append("Tools: " + ", ".join(context.tools))
        return " | ".join(parts)

    def _current_eoat_id(self) -> str:
        index = self.eoat_combo.currentIndex()
        value = self.eoat_combo.itemData(index) if index >= 0 else ""
        text = self.eoat_combo.currentText().strip()
        if value and (text == self.eoat_combo.itemText(index).strip() or text == str(value).strip()):
            return normalize_eoat_assembly_id(value)
        if text == "Select EOAT Assembly ID":
            return ""
        if " | " in text:
            text = text.split(" | ", 1)[0]
        return normalize_eoat_assembly_id(text)

    def _set_eoat_combo_value(self, eoat_id: str) -> None:
        eoat_id = normalize_eoat_assembly_id(eoat_id)
        if not eoat_id:
            self.eoat_combo.setCurrentIndex(0)
            return
        index = self.eoat_combo.findData(eoat_id)
        if index >= 0:
            self.eoat_combo.setCurrentIndex(index)
        else:
            self.eoat_combo.setCurrentIndex(-1)
            self.eoat_combo.setEditText(eoat_id)

    def apply_selected_eoat(self) -> None:
        eoat_id = self._current_eoat_id()
        self._update_eoat_context()
        self._populate_related_audit_options()
        rows = self._audit_rows_for_eoat(eoat_id)
        if len(rows) == 1:
            audit_id = str(rows[0].get("Audit ID") or "").strip()
            if audit_id:
                self.audit_id_edit.set_lookup_text(audit_id, block_signals=True)
                self._apply_audit_row(rows[0], preserve_description=True)
        self.refresh_indexed_photos(show_empty=False)

    def _audit_rows_for_eoat(self, eoat_id: str) -> list[dict[str, object]]:
        target = normalize_eoat_assembly_id(eoat_id).casefold()
        if not target:
            return []
        return [
            row
            for row in self.audit_lookup_rows
            if normalize_eoat_assembly_id(row.get(EOAT_ASSEMBLY_ID_FIELD)).casefold() == target
        ]

    def _update_eoat_context(self) -> None:
        eoat_id = self._current_eoat_id()
        context = self.eoat_contexts.get(eoat_id)
        if not eoat_id:
            self.eoat_context_label.setText("")
            return
        if context is None:
            self.eoat_context_label.setText(f"EOAT Assembly ID: {eoat_id}")
            return
        self.eoat_context_label.setText(
            "\n".join(
                [
                    f"Known Tool #s: {', '.join(context.tools) if context.tools else 'None'}",
                    f"Known Machines: {', '.join(context.known_machines) if context.known_machines else 'None'}",
                    f"Audit Machines: {', '.join(context.machines) if context.machines else 'None'}",
                    "Press Capacity Machines: "
                    + (", ".join(context.capacity_machines) if context.capacity_machines else "None"),
                    f"Known Audit IDs: {', '.join(context.audit_ids) if context.audit_ids else 'None'}",
                    f"Part Names: {', '.join(context.part_names) if context.part_names else 'None'}",
                ]
            )
        )

    def _machine_context(self, row: dict[str, object]) -> str:
        machine = str(row.get("Press/Machine #") or "").strip()
        if machine.casefold() in {
            "n/a",
            "na",
            "none",
            "unknown",
            "unknown / not checked",
            "not installed",
            "eoat not installed",
            "bench",
            "bench audit",
            "off machine",
            "off-machine",
            "uninstalled",
        }:
            return ""
        return machine

    def _is_completed_physical_audit_row(self, row: dict[str, object]) -> bool:
        entry_type = str(row.get(ENTRY_TYPE_FIELD) or "").strip().casefold()
        if entry_type == ENTRY_TYPE_COMPATIBLE.casefold():
            return False
        if entry_type in {"audited", "physical", "physical audit"}:
            return True
        status = str(row.get("Status") or "").strip().casefold()
        return status in {"audited", "complete", "completed", "needs follow-up", "candidate for pilot"}

    def _has_real_tool_number(self, row: dict[str, object]) -> bool:
        tool = str(row.get(TOOL_FIELD) or "").strip().casefold()
        return bool(tool) and tool not in {"n/a", "na", "none", "unknown", "unknown / not checked"}

    def _populate_tool_options(self) -> None:
        current = self._current_tool_number()
        current_machine = self._press_machine
        seen: set[tuple[str, str, str]] = set()
        rows: list[dict[str, object]] = []
        for row in self.audit_lookup_rows:
            if not self._is_completed_physical_audit_row(row):
                continue
            if not self._has_real_tool_number(row):
                continue
            tool = str(row.get(TOOL_FIELD) or "").strip()
            machine = self._machine_context(row)
            audit_id = str(row.get("Audit ID") or "").strip()
            key = (tool.casefold(), machine.casefold(), audit_id.casefold())
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        rows.sort(key=lambda row: (str(row.get(TOOL_FIELD) or ""), str(row.get("Press/Machine #") or "")))
        self.tool_lookup_rows = rows
        self.tool_combo.blockSignals(True)
        self.tool_combo.clear()
        self.tool_combo.addItem("Select tool", None)
        for row in rows:
            self.tool_combo.addItem(self._tool_option_label(row), row)
            if Qt is not None:
                self.tool_combo.setItemData(
                    self.tool_combo.count() - 1, self._tool_lookup_label(row), Qt.ItemDataRole.ToolTipRole
                )
        self.tool_combo.blockSignals(False)
        if current:
            self._select_tool_number(current, machine=current_machine, apply_row=False)

    def _current_tool_row(self) -> dict[str, object] | None:
        row = self.tool_combo.currentData()
        if not isinstance(row, dict):
            return None
        index = self.tool_combo.currentIndex()
        current_text = self.tool_combo.currentText().strip()
        selected_label = self.tool_combo.itemText(index).strip() if index >= 0 else ""
        row_tool = str(row.get(TOOL_FIELD) or "").strip()
        if current_text and current_text not in {selected_label, row_tool}:
            return None
        return row

    def _current_tool_number(self) -> str:
        row = self._current_tool_row()
        if row is not None:
            return str(row.get(TOOL_FIELD) or "").strip()
        text = self.tool_combo.currentText().strip()
        if " | " in text:
            return text.split(" | ", 1)[0].strip()
        if text == "Select tool":
            return ""
        return text

    def _select_tool_number(
        self,
        tool_number: str,
        *,
        machine: str = "",
        audit_id: str = "",
        apply_row: bool = True,
    ) -> dict[str, object] | None:
        target_tool = tool_number.strip().casefold()
        target_machine = machine.strip().casefold()
        target_audit = audit_id.strip().casefold()
        if not target_tool:
            self.tool_combo.setCurrentIndex(0)
            self._part_name = ""
            return None
        fallback_index = -1
        for index in range(self.tool_combo.count()):
            row = self.tool_combo.itemData(index)
            if not isinstance(row, dict):
                continue
            row_tool = str(row.get(TOOL_FIELD) or "").strip().casefold()
            row_machine = self._machine_context(row).casefold()
            row_audit = str(row.get("Audit ID") or "").strip().casefold()
            if row_tool != target_tool:
                continue
            if fallback_index < 0:
                fallback_index = index
            if target_machine and row_machine != target_machine:
                continue
            if target_audit and row_audit != target_audit:
                continue
            self.tool_combo.setCurrentIndex(index)
            self._show_selected_tool_number_only(row)
            if apply_row:
                self._apply_tool_row(row)
            return row
        if fallback_index >= 0:
            row = self.tool_combo.itemData(fallback_index)
            self.tool_combo.setCurrentIndex(fallback_index)
            if isinstance(row, dict):
                self._show_selected_tool_number_only(row)
                if apply_row:
                    self._apply_tool_row(row)
                return row
        if self.tool_combo.isEditable():
            self._press_machine = ""
            self._part_name = ""
            self.tool_combo.setEditText(tool_number.strip())
        return None

    def apply_selected_tool(self) -> None:
        row = self._current_tool_row()
        if row is not None:
            self._apply_tool_row(row)
        else:
            self._press_machine = ""
            self._part_name = ""

    def _manual_tool_text_changed(self, _text: str) -> None:
        if self._current_tool_row() is None:
            self._press_machine = ""
            self._part_name = ""

    def _apply_tool_row(self, row: dict[str, object]) -> None:
        self._press_machine = self._machine_context(row)
        self._part_name = str(row.get("Part Name/Description") or row.get("Part Family") or "").strip()
        eoat_id = normalize_eoat_assembly_id(row.get(EOAT_ASSEMBLY_ID_FIELD))
        if eoat_id:
            self._set_eoat_combo_value(eoat_id)
            self._update_eoat_context()
        self._show_selected_tool_number_only(row)
        audit_id = str(row.get("Audit ID") or "").strip()
        if audit_id:
            self.audit_id_edit.set_lookup_text(audit_id, block_signals=True)
        self._set_plant_from_row(row)
        if not self.description_edit.toPlainText().strip():
            self.description_edit.setPlainText(self._default_description(row))
        self.audit_context_label.setText(
            " | ".join(
                part
                for part in [
                    f"Machine: {row.get('Press/Machine #') or 'N/A'}",
                    f"Tool #: {row.get(TOOL_FIELD) or 'N/A'}",
                    f"EOAT Type: {row.get('EOAT Type') or 'N/A'}",
                    f"Part: {row.get('Part Name/Description') or 'N/A'}",
                    f"Status: {row.get('Status') or 'N/A'}",
                ]
                if part
            )
        )
        self.refresh_batch_defaults()
        self.refresh_evidence_coverage()

    def _show_selected_tool_number_only(self, row: dict[str, object]) -> None:
        tool = str(row.get(TOOL_FIELD) or "").strip()
        if not tool or not self.tool_combo.isEditable() or self.tool_combo.currentText().strip() == tool:
            return
        blocked = self.tool_combo.blockSignals(True)
        try:
            self.tool_combo.setEditText(tool)
        finally:
            self.tool_combo.blockSignals(blocked)

    def _set_plant_from_row(self, row: dict[str, object]) -> None:
        raw = str(row.get("Plant/Area") or "").strip()
        if raw in {"Whiteroom", "Cleanroom"}:
            self.plant_combo.setCurrentText(raw)
            return
        cleanroom = str(row.get("Cleanroom/Non-Cleanroom") or "").strip().casefold()
        if cleanroom == "cleanroom":
            self.plant_combo.setCurrentText("Cleanroom")
        elif cleanroom in {"whiteroom", "non-cleanroom", "non cleanroom", "noncleanroom", "no"}:
            self.plant_combo.setCurrentText("Whiteroom")

    def _populate_related_audit_options(self) -> None:
        current = self.audit_id_edit.text()
        eoat_id = self._current_eoat_id() if hasattr(self, "eoat_combo") else ""
        source_rows = self._audit_rows_for_eoat(eoat_id) if eoat_id else self.audit_lookup_rows
        options = [
            (self._audit_lookup_label(row), str(row.get("Audit ID") or "").strip())
            for row in source_rows
            if str(row.get("Audit ID") or "").strip()
        ]
        self._populate_lookup_options(self.audit_id_edit, options, current)

    def _populate_related_issue_options(self) -> None:
        current = self.issue_id_edit.text()
        options = [
            (self._issue_lookup_label(row), str(row.get("Issue ID") or "").strip())
            for row in self.issue_lookup_rows
            if str(row.get("Issue ID") or "").strip()
        ]
        self._populate_lookup_options(self.issue_id_edit, options, current)

    def _populate_lookup_options(
        self, combo: LookupComboBox, options: list[tuple[str, str]], current: str = ""
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", "")
        for label, value in options:
            if not value:
                continue
            combo.addItem(label or value, value)
            if Qt is not None:
                combo.setItemData(combo.count() - 1, label or value, Qt.ItemDataRole.ToolTipRole)
        combo.set_lookup_text(current, block_signals=True)
        combo.blockSignals(False)

    def _make_lookup_combo(self, options: list[tuple[str, str]], current: str = "") -> LookupComboBox:
        combo = LookupComboBox()
        self._populate_lookup_options(combo, options, current)
        return combo

    def _make_audit_id_combo(self, current: str = "") -> LookupComboBox:
        eoat_id = self._current_eoat_id() if hasattr(self, "eoat_combo") else ""
        source_rows = self._audit_rows_for_eoat(eoat_id) if eoat_id else self.audit_lookup_rows
        options = [
            (self._audit_lookup_label(row), str(row.get("Audit ID") or "").strip())
            for row in source_rows
            if str(row.get("Audit ID") or "").strip()
        ]
        return self._make_lookup_combo(options, current)

    def _make_issue_id_combo(self, current: str = "") -> LookupComboBox:
        options = [
            (self._issue_lookup_label(row), str(row.get("Issue ID") or "").strip())
            for row in self.issue_lookup_rows
            if str(row.get("Issue ID") or "").strip()
        ]
        return self._make_lookup_combo(options, current)

    def refresh_audit_context(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        if not audit_id:
            self.audit_context_label.setText("")
            return
        row = self._find_audit_row(audit_id)
        if row is None:
            self.audit_context_label.setText("No matching audit row found.")
            return
        self._apply_audit_row(row, preserve_description=True)

    def _find_audit_row(self, query: str) -> dict[str, object] | None:
        folded = query.strip().casefold()
        if not folded:
            return None
        for row in self.audit_lookup_rows or self._load_audit_rows():
            candidates = [
                row.get("Audit ID"),
                row.get("Press/Machine #"),
                row.get(TOOL_FIELD),
                row.get("Part Family"),
                row.get("Part Name/Description"),
            ]
            if any(str(candidate or "").strip().casefold() == folded for candidate in candidates):
                return row
        for row in self.audit_lookup_rows or self._load_audit_rows():
            haystack = self._audit_lookup_label(row).casefold()
            if folded in haystack:
                return row
        return None

    def _apply_audit_row(self, row: dict[str, object], *, preserve_description: bool = False) -> None:
        audit_id = str(row.get("Audit ID") or "").strip()
        press = self._machine_context(row)
        if audit_id:
            self.audit_id_edit.set_lookup_text(audit_id, block_signals=True)
        self._press_machine = press
        self._part_name = str(row.get("Part Name/Description") or row.get("Part Family") or "").strip()
        self._set_plant_from_row(row)
        selected = self._select_tool_number(
            str(row.get(TOOL_FIELD) or "").strip(), machine=press, audit_id=audit_id, apply_row=False
        )
        if selected is None:
            self._press_machine = press
            self._part_name = str(row.get("Part Name/Description") or row.get("Part Family") or "").strip()
        eoat_id = normalize_eoat_assembly_id(row.get(EOAT_ASSEMBLY_ID_FIELD))
        if eoat_id:
            self._set_eoat_combo_value(eoat_id)
            self._update_eoat_context()
        if not preserve_description or not self.description_edit.toPlainText().strip():
            self.description_edit.setPlainText(self._default_description(row))
        self.audit_context_label.setText(
            " | ".join(
                part
                for part in [
                    f"EOAT Type: {row.get('EOAT Type') or 'N/A'}",
                    f"Tool #: {row.get(TOOL_FIELD) or 'N/A'}",
                    f"Part Family: {row.get('Part Family') or 'N/A'}",
                    f"Part: {row.get('Part Name/Description') or 'N/A'}",
                    f"Status: {row.get('Status') or 'N/A'}",
                    f"Photos Taken?: {row.get('Photos Taken?') or 'N/A'}",
                ]
                if part
            )
        )
        self.refresh_batch_defaults()
        self.refresh_evidence_coverage()

    def _default_description(self, row: dict[str, object]) -> str:
        audit_id = str(row.get("Audit ID") or "").strip()
        machine = str(row.get("Press/Machine #") or "").strip()
        tool = self._current_tool_number() or str(row.get(TOOL_FIELD) or "").strip()
        eoat_id = self._current_eoat_id() or normalize_eoat_assembly_id(row.get(EOAT_ASSEMBLY_ID_FIELD))
        pieces = [f"Photo evidence for {audit_id}" if audit_id else "Photo evidence"]
        if eoat_id:
            pieces.append(eoat_id)
        if machine:
            pieces.append(f"Machine {machine}")
        if tool:
            pieces.append(f"Tool {tool}")
        return ", ".join(pieces)

    def metadata(self) -> dict[str, str]:
        return {
            "plant_area": self.plant_combo.currentText().strip(),
            "press_machine": self._press_machine.strip(),
            "eoat_assembly_id": self._current_eoat_id(),
            "tool_number": self._current_tool_number(),
            "part_name": self._part_name.strip(),
            "date_taken": self.date_edit.text().strip(),
            "view_type": self.view_combo.currentText(),
            "related_audit_id": self.audit_id_edit.text().strip(),
            "related_issue_id": self.issue_id_edit.text().strip(),
            "audit_field_link": self.audit_field_link_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
        }

    def apply_pending_audit_field_link(self, link_text: str) -> None:
        self.audit_field_link_edit.setText(str(link_text or "").strip())
        label = friendly_audit_field_label(link_text)
        if label:
            self.link_display_label.setText(label)
            parsed = parse_audit_field_link(link_text)
            if parsed is not None:
                self.audit_id_edit.setText(parsed.audit_id)
                if parsed.machine_number and not self._press_machine:
                    self._press_machine = parsed.machine_number
                if parsed.tool_number and not self._current_tool_number():
                    selected = self._select_tool_number(parsed.tool_number, machine=parsed.machine_number)
                    if selected is None and parsed.machine_number:
                        self._press_machine = parsed.machine_number
                self.refresh_audit_context()
            self.result_panel.show_text(f"Ready to attach photo to: {label}")
        else:
            self.link_display_label.setText("")
        self._update_go_to_link_button()

    def build_batch_review(self) -> None:
        photos = self.selected_photos()
        self.batch_table.setRowCount(0)
        for photo in photos:
            row_index = self.batch_table.rowCount()
            self.batch_table.insertRow(row_index)

            include = QCheckBox()
            include.setChecked(True)
            self.batch_table.setCellWidget(row_index, self.BATCH_INCLUDE_COL, include)

            source_item = QTableWidgetItem(Path(photo).name)
            source_item.setToolTip(photo)
            if Qt is not None:
                source_item.setData(Qt.ItemDataRole.UserRole, photo)
            self.batch_table.setItem(row_index, self.BATCH_SOURCE_COL, source_item)
            self.batch_table.setItem(row_index, self.BATCH_TARGET_COL, QTableWidgetItem(""))

            view = QComboBox()
            view.addItems(list(PHOTO_VIEW_FOLDERS.keys()))
            view.setCurrentText(self.view_combo.currentText())
            view.currentTextChanged.connect(lambda _text: self.refresh_batch_preview(show_result=False))
            self.batch_table.setCellWidget(row_index, self.BATCH_VIEW_COL, view)

            self.batch_table.setItem(
                row_index, self.BATCH_DESCRIPTION_COL, QTableWidgetItem(self.description_edit.toPlainText().strip())
            )
            self.batch_table.setCellWidget(
                row_index, self.BATCH_AUDIT_COL, self._make_audit_id_combo(self.audit_id_edit.text().strip())
            )
            self.batch_table.setCellWidget(
                row_index, self.BATCH_ISSUE_COL, self._make_issue_id_combo(self.issue_id_edit.text().strip())
            )
            self.batch_table.setItem(
                row_index, self.BATCH_FIELD_COL, QTableWidgetItem(self.audit_field_link_edit.text().strip())
            )
        self.refresh_batch_preview(show_result=False)

    def refresh_batch_defaults(self) -> None:
        if self.batch_table.rowCount() == 0:
            return
        for row_index in range(self.batch_table.rowCount()):
            self._set_batch_lookup_text(row_index, self.BATCH_AUDIT_COL, self.audit_id_edit.text().strip())
            self._set_batch_lookup_text(row_index, self.BATCH_ISSUE_COL, self.issue_id_edit.text().strip())
            description_item = self.batch_table.item(row_index, self.BATCH_DESCRIPTION_COL)
            if description_item is not None and not description_item.text().strip():
                description_item.setText(self.description_edit.toPlainText().strip())
        self.refresh_batch_preview(show_result=False)

    def _set_batch_lookup_text(self, row_index: int, column: int, value: str) -> None:
        widget = self.batch_table.cellWidget(row_index, column)
        if isinstance(widget, LookupComboBox) and not widget.text().strip():
            widget.set_lookup_text(value, block_signals=True)
            return
        item = self.batch_table.item(row_index, column)
        if item is not None and not item.text().strip():
            item.setText(value)

    def refresh_batch_preview(self, show_result: bool = True) -> None:
        if self.batch_table.rowCount() == 0:
            return
        photos, metadata = self.selected_batch_metadata()
        if not photos:
            if show_result:
                self.result_panel.show_text("No batch rows are included.")
            return
        data = self.metadata()
        plan = preview_photo_intake(
            self.config.project_root,
            photos,
            data["plant_area"],
            data["press_machine"],
            data["date_taken"],
            data["view_type"],
            tool_number=data["tool_number"],
            part_name=data["part_name"],
            eoat_assembly_id=data["eoat_assembly_id"],
            per_photo_metadata=metadata,
        )
        included_rows = self._included_batch_rows()
        for row_index, item in zip(included_rows, plan):
            self.batch_table.setItem(row_index, self.BATCH_TARGET_COL, QTableWidgetItem(item.target.name))
        if show_result:
            self.result_panel.show_text("\n".join(f"{item.source} -> {item.target}" for item in plan))

    def selected_batch_metadata(self) -> tuple[list[str], list[dict[str, str]]]:
        photos: list[str] = []
        metadata: list[dict[str, str]] = []
        for row_index in self._included_batch_rows():
            source = self._batch_source(row_index)
            if not source:
                continue
            photos.append(source)
            metadata.append(
                {
                    "source": source,
                    "view_type": self._batch_view_type(row_index),
                    "description": self._batch_item_text(row_index, self.BATCH_DESCRIPTION_COL),
                    "related_audit_id": self._batch_item_text(row_index, self.BATCH_AUDIT_COL),
                    "related_issue_id": self._batch_item_text(row_index, self.BATCH_ISSUE_COL),
                    "linked_audit_field": self._batch_item_text(row_index, self.BATCH_FIELD_COL),
                }
            )
        return photos, metadata

    def _included_batch_rows(self) -> list[int]:
        rows: list[int] = []
        for row_index in range(self.batch_table.rowCount()):
            include = self.batch_table.cellWidget(row_index, self.BATCH_INCLUDE_COL)
            if isinstance(include, QCheckBox) and not include.isChecked():
                continue
            rows.append(row_index)
        return rows

    def _batch_source(self, row_index: int) -> str:
        item = self.batch_table.item(row_index, self.BATCH_SOURCE_COL)
        if item is None:
            return ""
        if Qt is not None:
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                return str(value)
        return item.toolTip() or item.text()

    def _batch_view_type(self, row_index: int) -> str:
        widget = self.batch_table.cellWidget(row_index, self.BATCH_VIEW_COL)
        if isinstance(widget, QComboBox):
            return widget.currentText()
        return self.view_combo.currentText()

    def _batch_item_text(self, row_index: int, column: int) -> str:
        widget = self.batch_table.cellWidget(row_index, column)
        if isinstance(widget, LookupComboBox):
            return widget.text().strip()
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        item = self.batch_table.item(row_index, column)
        return item.text().strip() if item is not None else ""

    def _current_audit_field_link_text(self) -> str:
        text = self.audit_field_link_edit.text().strip()
        if text:
            return text
        row_index = self.indexed_photos_table.currentRow()
        if row_index < 0:
            return ""
        item = self.indexed_photos_table.item(row_index, 4)
        return item.text().strip() if item is not None else ""

    def _update_go_to_link_button(self) -> None:
        if not hasattr(self, "go_to_link_button"):
            return
        text = self._current_audit_field_link_text()
        label = friendly_audit_field_label(text)
        self.go_to_link_button.setEnabled(bool(label))
        if label:
            self.link_display_label.setText(label)
        elif text:
            self.link_display_label.setText("Go to Link unavailable for this older/manual link.")
        else:
            self.link_display_label.setText("")

    def go_to_audit_field_link(self) -> None:
        link_text = self._current_audit_field_link_text()
        if not link_text:
            self.result_panel.show_text("Enter or select a linked audit field first.")
            return
        if parse_audit_field_link(link_text) is None:
            self.result_panel.show_text("Go to Link unavailable for this older/manual link.")
            return
        window = self.window()
        if hasattr(window, "navigate_to_audit_field_link") and window.navigate_to_audit_field_link(link_text):
            return
        self.result_panel.show_text("Could not open the linked audit field from this window.")

    def preview_plan(self) -> None:
        data = self.metadata()
        if self.batch_table.rowCount() > 0:
            self.refresh_batch_preview()
            return
        plan = preview_photo_intake(
            self.config.project_root,
            self.selected_photos(),
            data["plant_area"],
            data["press_machine"],
            data["date_taken"],
            data["view_type"],
            tool_number=data["tool_number"],
            part_name=data["part_name"],
            eoat_assembly_id=data["eoat_assembly_id"],
        )
        if not plan:
            self.result_panel.show_text("No selected supported photos to preview.")
            return
        self.result_panel.show_text("\n".join(f"{item.source} -> {item.target}" for item in plan))

    def confirm_intake(self) -> None:
        data = self.metadata()
        if self.batch_table.rowCount() > 0:
            photos, per_photo_metadata = self.selected_batch_metadata()
        else:
            photos = self.selected_photos()
            per_photo_metadata = None
        run_tool_background(
            self.result_panel,
            "photo_intake_confirm",
            "Photo Intake",
            lambda: intake_photos(
                self.config.project_root,
                photos,
                data["plant_area"],
                data["press_machine"],
                data["date_taken"],
                data["view_type"],
                eoat_assembly_id=data["eoat_assembly_id"],
                tool_number=data["tool_number"],
                part_name=data["part_name"],
                related_audit_id=data["related_audit_id"],
                related_issue_id=data["related_issue_id"],
                description=data["description"],
                notes=data["notes"],
                linked_audit_field=data["audit_field_link"],
                per_photo_metadata=per_photo_metadata,
                copy_mode=self.copy_check.isChecked(),
            ),
            self._intake_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _intake_finished(self, result) -> None:
        if result.success:
            self.refresh_audit_lookup()
            self.refresh_audit_context()
            self.refresh_incoming()
            self.refresh_evidence_coverage()
            self.refresh_indexed_photos(show_empty=False)
            self.result_panel.show_result(result)

    def repair_audit_photo_ties(self) -> None:
        run_tool_background(
            self.result_panel,
            "photo_repair_audit_ties",
            "Repair Audit Photo Ties",
            lambda: repair_audit_photo_ties(self.config.project_root),
            self._repair_audit_photo_ties_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _repair_audit_photo_ties_finished(self, result) -> None:
        if result.success:
            self.refresh_audit_lookup()
            self.refresh_audit_context()
            self.refresh_evidence_coverage()
            self.refresh_indexed_photos(show_empty=False)
            self.result_panel.show_result(result)

    def repair_photo_eoat_links(self) -> None:
        run_tool_background(
            self.result_panel,
            "repair_photo_eoat_links",
            "Repair Photo EOAT Links",
            lambda: repair_photo_eoat_links(self.config.project_root),
            self._photo_eoat_action_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _photo_eoat_action_finished(self, result) -> None:
        if result.success:
            self.refresh_audit_lookup()
            self.refresh_evidence_coverage()
            self.refresh_indexed_photos(show_empty=False)
        self.result_panel.show_result(result)

    def open_incoming(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).incoming_photos)
        if not result.success:
            self.result_panel.show_result(result)

    def open_cell_photos(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).cell_photos)
        if not result.success:
            self.result_panel.show_result(result)

    def create_eoat_photo_folder(self) -> None:
        eoat_id = self._current_eoat_id()
        if not eoat_id:
            self.result_panel.show_text("Select an EOAT Assembly ID before creating its photo folder.")
            return
        folder = ensure_eoat_photo_category_folder(self.config.project_root, eoat_id, self.view_combo.currentText())
        warning = ""
        try:
            metadata_path = update_eoat_info_file(self.config.project_root, eoat_id)
        except Exception as exc:
            metadata_path = None
            warning = f"\nCould not update eoat_info.json: {exc}"
        self.result_panel.show_text(
            f"EOAT photo folder ready:\n{folder}"
            + (f"\nMetadata: {metadata_path}" if metadata_path is not None else "")
            + warning
        )

    def open_eoat_photo_folder(self) -> None:
        eoat_id = self._current_eoat_id()
        if not eoat_id:
            self.result_panel.show_text("Select an EOAT Assembly ID before opening its folder.")
            return
        result = open_path(eoat_photo_root(self.config.project_root, eoat_id))
        if not result.success:
            self.result_panel.show_result(result)

    def refresh_evidence_coverage(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        self.evidence_table.setRowCount(0)
        self.missing_shots_label.setText("")
        self.next_shot_type = "Front View"
        self.refresh_indexed_photos(show_empty=False)
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID to review photo evidence coverage.")
            return
        coverage = evidence_coverage_for_audit(self.config.project_root, audit_id)
        if coverage is None:
            self.result_panel.show_text(
                f"No audit row found for {audit_id}. You can still create an intake folder for phone photos."
            )
            return
        self.evidence_table.setRowCount(len(coverage.statuses))
        for row_index, status in enumerate(coverage.statuses):
            values = [
                status.label,
                "Yes" if status.required else "No",
                "Yes" if status.present else "No",
                str(status.photo_count),
                " - ".join(part for part in [status.status, status.warning] if part),
            ]
            for column, value in enumerate(values):
                self.evidence_table.setItem(row_index, column, QTableWidgetItem(value))
        missing = [status.label for status in coverage.statuses if status.required and not status.present]
        recommended = [
            status.label
            for status in coverage.statuses
            if status.applies and not status.required and not status.present
        ]
        if missing:
            self.next_shot_type = missing[0]
        elif recommended:
            self.next_shot_type = recommended[0]
        else:
            self.next_shot_type = "Front View"
        if missing:
            self.missing_shots_label.setText(
                "Missing shot types: " + ", ".join(missing) + f". Next: {self.next_shot_type}"
            )
        elif recommended:
            self.missing_shots_label.setText(
                "Recommended shot types: " + ", ".join(recommended) + f". Next: {self.next_shot_type}"
            )
        else:
            self.missing_shots_label.setText("Missing shot types: none")
        self.result_panel.show_text(
            f"Evidence coverage for {coverage.audit_id}: "
            f"{coverage.complete_count} complete, {coverage.missing_required_count} required missing."
        )

    def use_next_missing_shot_type(self) -> None:
        shot_type = self.next_shot_type or "Front View"
        self.view_combo.setCurrentText(shot_type)
        for row_index in range(self.batch_table.rowCount()):
            widget = self.batch_table.cellWidget(row_index, self.BATCH_VIEW_COL)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(shot_type)
        self.refresh_batch_preview(show_result=False)
        self.result_panel.show_text(f"EOAT Area Shown set to {shot_type}.")

    def refresh_indexed_photos(self, show_empty: bool = True) -> None:
        audit_id = self.audit_id_edit.text().strip()
        eoat_id = self._current_eoat_id()
        self.indexed_photos_table.setRowCount(0)
        if not eoat_id and not audit_id:
            if show_empty:
                self.result_panel.show_text("Select an EOAT Assembly ID or Related Audit ID to review indexed photos.")
            return
        rows = (
            indexed_photos_for_eoat(self.config.project_root, eoat_id)
            if eoat_id
            else indexed_photos_for_audit(self.config.project_root, audit_id)
        )
        self.indexed_photos_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            linked_field = linked_audit_field_for_photo(row)
            path = resolve_indexed_photo_path(self.config.project_root, row)
            values = [
                str(row.get("EOAT Area Shown") or ""),
                str(row.get("Photo Filename") or ""),
                str(row.get("Date Taken") or ""),
                str(row.get("Description") or ""),
                linked_field,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if Qt is not None:
                    item.setData(Qt.ItemDataRole.UserRole, str(path))
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole + 1, str(row.get("Photo ID") or ""))
                self.indexed_photos_table.setItem(row_index, column, item)
        if show_empty:
            target = eoat_id or audit_id
            self.result_panel.show_text(f"Indexed photos for {target}: {len(rows)}")

    def open_selected_indexed_photo(self) -> None:
        row_index = self.indexed_photos_table.currentRow()
        if row_index < 0:
            self.result_panel.show_text("Select an indexed photo first.")
            return
        path_item = self.indexed_photos_table.item(row_index, 1) or self.indexed_photos_table.item(row_index, 0)
        if path_item is None:
            self.result_panel.show_text("Selected photo has no path.")
            return
        path = path_item.data(Qt.ItemDataRole.UserRole) if Qt is not None else ""
        result = open_path(path or path_item.text())
        if not result.success:
            self.result_panel.show_result(result)

    def link_selected_photo_to_field(self) -> None:
        row_index = self.indexed_photos_table.currentRow()
        if row_index < 0:
            self.result_panel.show_text("Select an indexed photo first.")
            return
        photo_item = self.indexed_photos_table.item(row_index, 0)
        photo_id = ""
        if photo_item is not None:
            photo_id = (
                str(photo_item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
                if Qt is not None
                else photo_item.text().strip()
            )
        audit_field = self.audit_field_link_edit.text().strip()
        if not audit_field:
            self.result_panel.show_text("Enter an audit field to link this photo to.")
            return
        run_tool_background(
            self.result_panel,
            "photo_evidence_link_field",
            "Photo Evidence Field Link",
            lambda: link_photo_to_audit_field(self.config.project_root, photo_id, audit_field),
            self._field_link_finished,
            modifies_files=True,
            workbook_lock=True,
        )

    def _field_link_finished(self, result) -> None:
        if result.success:
            self.refresh_indexed_photos(show_empty=False)
            self.refresh_evidence_coverage()

    def _notes_with_field_link(self, notes: str, audit_field: str) -> str:
        audit_field = audit_field.strip()
        if not audit_field:
            return notes
        link_note = f"Linked audit field: {audit_field}"
        if link_note in notes:
            return notes
        return "\n".join(part for part in (notes, link_note) if part)

    def _linked_field_from_notes(self, notes: str) -> str:
        for line in notes.splitlines():
            if line.casefold().startswith("linked audit field:"):
                return line.split(":", 1)[1].strip()
        return ""

    def create_audit_intake_folder(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        result = create_audit_photo_intake_folder(self.config.project_root, audit_id)
        self.result_panel.show_result(result)

    def export_audit_photo_checklist(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        result = export_photo_checklist(self.config.project_root, audit_id)
        self.result_panel.show_result(result)

    def copy_audit_intake_path(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID before copying the intake path.")
            return
        path = audit_photo_intake_folder(self.config.project_root, audit_id)
        app = QApplication.instance() if QApplication is not None else None
        if app is None:
            self.result_panel.show_text(str(path))
            return
        app.clipboard().setText(str(path))
        self.result_panel.show_text(f"Copied intake path:\n{path}")

    def open_audit_intake_folder(self) -> None:
        audit_id = self.audit_id_edit.text().strip()
        if not audit_id:
            self.result_panel.show_text("Enter a Related Audit ID before opening the intake folder.")
            return
        result = open_path(audit_photo_intake_folder(self.config.project_root, audit_id))
        if not result.success:
            self.result_panel.show_result(result)
