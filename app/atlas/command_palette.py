from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from core.atlas_exports import (
    export_compatibility_matrix,
    export_documentation_gap_report,
    export_photo_coverage_report,
)
from core.atlas_health import RelationshipHealth, machine_relationship_health
from core.atlas_reports import generate_atlas_report
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.logging import log_activity_event

LOGGER = logging.getLogger(__name__)

ITEM_ENTITY_SEARCH = "entity_search"
ITEM_COMMAND = "command"
ITEM_NAVIGATION = "navigation"
ITEM_RECENT_SEARCH = "recent_search"
ITEM_RECENT_ACTION = "recent_action"
VALID_PALETTE_ITEM_TYPES = {
    ITEM_ENTITY_SEARCH,
    ITEM_COMMAND,
    ITEM_NAVIGATION,
    ITEM_RECENT_SEARCH,
    ITEM_RECENT_ACTION,
}


@dataclass(frozen=True)
class AtlasCommand:
    command_id: str
    category: str
    title: str
    subtitle: str
    handler: Callable[[], None]
    aliases: tuple[str, ...] = ()
    result_text: str = ""
    item_type: str = ITEM_COMMAND
    route: str = ""
    action: str = ""
    search_query: str = ""
    entity_type: str = ""
    entity_id: str = ""
    route_target: dict[str, str] | None = None

    def searchable_text(self) -> str:
        return " ".join(
            (
                self.command_id,
                self.category,
                self.title,
                self.subtitle,
                self.result_text,
                self.route,
                self.action,
                self.search_query,
                self.entity_type,
                self.entity_id,
                *self.aliases,
            )
        ).casefold()

    def selection_type(self) -> str:
        return self.item_type if self.item_type in VALID_PALETTE_ITEM_TYPES else ""


class AtlasCommandPalette(QDialog):
    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self.window = window
        self.commands: list[AtlasCommand] = []
        self._command_dispatch_in_progress = False
        self.setObjectName("AtlasCommandPalette")
        self.setWindowTitle("Command Palette")
        self.setModal(True)
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("Command Palette")
        title.setObjectName("CardTitle")
        layout.addWidget(title)
        self.search = QLineEdit()
        self.search.setObjectName("ModernSearchBar")
        self.search.setPlaceholderText("Navigate, search records, run reports, or ask: machine 36, missing photos, tools with no EOAT...")
        self.search.installEventFilter(self)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.results = QListWidget()
        self.results.setObjectName("CommandPaletteResults")
        self.results.itemActivated.connect(self._run_item)
        layout.addWidget(self.results, 1)

        row = QHBoxLayout()
        run_button = QPushButton("Run")
        run_button.setObjectName("PrimaryButton")
        run_button.clicked.connect(self.run_current)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        row.addWidget(run_button)
        row.addStretch(1)
        row.addWidget(close_button)
        layout.addLayout(row)
        self.refresh()

    def open_with_query(self, query: str = "") -> None:
        self.search.setText(query)
        self.search.selectAll()
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.refresh()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            self.run_current()
            return
        if event.key() == Qt.Key.Key_Down:
            self._move_selection(1)
            return
        if event.key() == Qt.Key.Key_Up:
            self._move_selection(-1)
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self.run_current()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(watched, event)

    def refresh(self) -> None:
        self.commands = resolve_atlas_commands(self.window, self.search.text(), limit=90)
        self.results.blockSignals(True)
        self.results.clear()
        grouped: dict[str, list[AtlasCommand]] = {}
        for command in self.commands:
            grouped.setdefault(command.category, []).append(command)
        for category in ["Pages", "Records", "Actions", "Reports", "Filters / Views", "Questions", "Recent", "Pinned", "Settings"]:
            rows = grouped.get(category, [])
            if not rows:
                continue
            header = QListWidgetItem(category.upper())
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(Qt.ItemDataRole.UserRole, None)
            header.setSizeHint(QSize(0, 28))
            self.results.addItem(header)
            for command in rows:
                item = QListWidgetItem(command.title)
                item.setToolTip(command.subtitle or command.result_text)
                item.setData(Qt.ItemDataRole.UserRole, command)
                detail = command.result_text or command.subtitle
                if detail:
                    item.setText(f"{command.title}\n{detail}")
                item.setSizeHint(QSize(0, 56 if detail else 42))
                self.results.addItem(item)
        self.results.blockSignals(False)
        self._select_first_command()

    def run_current(self) -> None:
        self._run_item(self.results.currentItem())

    def _run_item(self, item: QListWidgetItem | None) -> None:
        if self._command_dispatch_in_progress:
            return
        if item is None:
            return
        command = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(command, AtlasCommand):
            return
        self._command_dispatch_in_progress = True
        query = self.search.text().strip()
        _log_palette_selection(self.window, command, query=query)
        if not command.selection_type():
            _show_status(self.window, f"Command Palette item type is not supported: {command.item_type or 'unknown'}.")
            LOGGER.warning("Unknown command palette item type: id=%s type=%s", command.command_id, command.item_type)
            self._command_dispatch_in_progress = False
            return
        self.accept()
        QTimer.singleShot(0, lambda command=command, query=query: self._dispatch_command(command, query))

    def _dispatch_command(self, command: AtlasCommand, query: str) -> None:
        try:
            navigator = getattr(self.window, "navigate_to_profile", None)
            if command.item_type in {ITEM_ENTITY_SEARCH, ITEM_RECENT_SEARCH} and command.entity_type and callable(navigator):
                navigator(command, source="global-search", raw_query=query or command.search_query)
            else:
                command.handler()
        except Exception as exc:
            LOGGER.exception("Command Palette selection failed: id=%s type=%s", command.command_id, command.item_type)
            _show_status(self.window, f"Command Palette action failed: {type(exc).__name__}: {exc}")
            return
        finally:
            self._command_dispatch_in_progress = False

    def _move_selection(self, delta: int) -> None:
        if self.results.count() == 0:
            return
        row = self.results.currentRow()
        for offset in range(1, self.results.count() + 1):
            next_row = (row + delta * offset) % self.results.count()
            item = self.results.item(next_row)
            if isinstance(item.data(Qt.ItemDataRole.UserRole), AtlasCommand):
                self.results.setCurrentRow(next_row)
                return

    def _select_first_command(self) -> None:
        for index in range(self.results.count()):
            item = self.results.item(index)
            if isinstance(item.data(Qt.ItemDataRole.UserRole), AtlasCommand):
                self.results.setCurrentRow(index)
                return


def resolve_atlas_commands(window, query: str = "", *, limit: int = 80, include_entity_records: bool = True) -> list[AtlasCommand]:
    query = str(query or "").strip()
    commands = [*build_atlas_commands(window, include_entity_records=include_entity_records)]
    if include_entity_records:
        commands.extend(_dynamic_query_commands(window, query))
    scored = [
        (score, command)
        for command in commands
        if (score := _command_score(command, query, window, include_entity_records=include_entity_records)) > 0
    ]
    scored.sort(key=lambda item: (-item[0], item[1].category, item[1].title.casefold()))
    return [command for _score, command in scored[:limit]]


def build_atlas_commands(window, *, include_entity_records: bool = True) -> list[AtlasCommand]:
    bundle = getattr(window, "bundle", None)
    commands: list[AtlasCommand] = []
    page_labels = {
        "home": "Home",
        "fit_check": "Fit Check",
        "library": "Library",
        "settings": "Settings",
    }
    for key, label in page_labels.items():
        command_id = "open_library" if key == "library" else f"nav.{key}"
        title = "Library" if key == "library" else f"Open {label}"
        commands.append(
            AtlasCommand(
                command_id,
                "Pages",
                title,
                "Navigate to Atlas page.",
                lambda key=key: window.show_page(key),
                (key, label, label.replace("/", " ")),
                item_type=ITEM_NAVIGATION,
                route=key,
            )
        )
    commands.extend(_action_commands(window))
    commands.extend(_recent_and_pinned_commands(window))
    if bundle is None or not include_entity_records:
        return commands
    commands.extend(_entity_commands(window, bundle))
    commands.extend(_filter_view_commands(window, bundle))
    commands.extend(_question_commands(window, bundle))
    return commands


def _dynamic_query_commands(window, query: str) -> list[AtlasCommand]:
    folded = str(query or "").strip().casefold().rstrip("?")
    bundle = getattr(window, "bundle", None)
    commands: list[AtlasCommand] = []
    machine_match = re.search(r"build\s+packet\s+machine\s+([1-9]\d*)", folded)
    if machine_match:
        machine = machine_match.group(1)
        commands.append(
            AtlasCommand(
                f"dynamic.build_packet.machine.{machine}",
                "Actions",
                f"Build packet for Machine {machine}",
                "Open setup packet flow with machine prefilled.",
                lambda machine=machine: window.open_setup_packet(machine=machine, context_label="Command Palette"),
                (query,),
                item_type=ITEM_COMMAND,
                action="build_packet",
            )
        )
    photo_match = re.search(r"photos?\s+([a-z0-9\-\s]+)$", folded)
    if photo_match and bundle is not None:
        value = photo_match.group(1).strip()
        eoat = _find_eoat_for_query(bundle, value)
        if eoat:
            commands.append(
                AtlasCommand(
                    f"photos.{normalized_eoat_key(eoat.eoat_id)}",
                    "Records",
                    f"Open photos for {eoat.eoat_id}",
                    f"{eoat.photo_count} linked photo(s)",
                    lambda eoat_id=eoat.eoat_id: window.open_photos(eoat_id),
                    (query,),
                    item_type=ITEM_NAVIGATION,
                    route="photos",
                    search_query=eoat.eoat_id,
                )
            )
    warning_match = re.search(r"why\s+warning\s+([a-z0-9\-\s]+)$", folded)
    if warning_match and bundle is not None:
        eoat = _find_eoat_for_query(bundle, warning_match.group(1).strip())
        if eoat:
            warning_text = "; ".join(f"{warning.title}: {warning.message}" for warning in eoat.warnings[:6]) or "No EOAT warnings indexed."
            commands.append(
                AtlasCommand(
                    f"dynamic.warning.{normalized_eoat_key(eoat.eoat_id)}",
                    "Questions",
                    f"Why is {eoat.eoat_id} warning?",
                    warning_text,
                    lambda text=warning_text: _show_result(window, text),
                    (query,),
                    warning_text,
                )
            )
    standards_match = re.search(r"(?:what\s+)?standards?\s+(?:apply\s+)?(?:to|for)?\s*([a-z0-9\-\s]+)$", folded)
    if standards_match and bundle is not None:
        eoat = _find_eoat_for_query_or_current(window, bundle, standards_match.group(1).strip())
        if eoat:
            standards_text = "; ".join(f"{standard.title} ({standard.category or 'Standard'})" for standard in eoat.standards[:8])
            standards_text = standards_text or "No applicable standards are indexed for this EOAT."
            commands.append(
                AtlasCommand(
                    f"dynamic.standards.{normalized_eoat_key(eoat.eoat_id)}",
                    "Questions",
                    f"What standards apply to {eoat.eoat_id}?",
                    standards_text,
                    lambda text=standards_text: _show_result(window, text),
                    (query, "applicable standards"),
                    standards_text,
                )
            )
    machines_match = re.search(r"what\s+machines\s+can\s+run\s+(?:eoat\s+)?([a-z0-9\-\s]+)$", folded)
    if machines_match and bundle is not None:
        eoat = _find_eoat_for_query(bundle, machines_match.group(1).strip())
        if eoat:
            result = ", ".join(eoat.machines) or "No compatible machines are indexed."
            commands.append(
                AtlasCommand(
                    f"dynamic.eoat_machines.{normalized_eoat_key(eoat.eoat_id)}",
                    "Questions",
                    f"What machines can run {eoat.eoat_id}?",
                    result,
                    lambda text=result: _show_result(window, text),
                    (query,),
                    result,
                )
            )
    eoats_for_tool_match = re.search(r"what\s+eoats\s+can\s+run\s+(?:tool\s+)?([a-z0-9\-\s]+)$", folded)
    if eoats_for_tool_match and bundle is not None:
        tool = _find_tool_for_query(bundle, eoats_for_tool_match.group(1).strip())
        if tool:
            result = ", ".join(tool.compatible_eoats) or "No validated EOATs are indexed for this tool."
            commands.append(
                AtlasCommand(
                    f"dynamic.tool_eoats.{normalized_tool_key(tool.tool)}",
                    "Questions",
                    f"What EOATs can run Tool {tool.tool}?",
                    result,
                    lambda text=result: _show_result(window, text),
                    (query,),
                    result,
                )
            )
    tools_for_machine_match = re.search(r"what\s+tools\s+can\s+run\s+on\s+(?:machine\s+)?([a-z0-9\-\s]+)$", folded)
    if tools_for_machine_match and bundle is not None:
        machine = _find_machine_for_query(bundle, tools_for_machine_match.group(1).strip())
        if machine:
            result = ", ".join(machine.compatible_tools) or "No compatible tools are indexed for this machine."
            commands.append(
                AtlasCommand(
                    f"dynamic.machine_tools.{normalized_machine_key(machine.machine)}",
                    "Questions",
                    f"What tools can run on Machine {machine.machine}?",
                    result,
                    lambda text=result: _show_result(window, text),
                    (query,),
                    result,
                )
            )
    return commands


def _action_commands(window) -> list[AtlasCommand]:
    commands = [
        AtlasCommand(
            "action.refresh",
            "Actions",
            "Refresh",
            "Reload EOAT Atlas from the existing local cache.",
            lambda: window.refresh_data(force=False),
            ("refresh", "refresh data", "reload", "reload data", "refresh view"),
            item_type=ITEM_COMMAND,
            action="refresh",
        ),
        AtlasCommand(
            "action.deep_refresh",
            "Actions",
            "Deep Refresh",
            "Rebuild the local SQLite cache from staged workbook data.",
            lambda: window.deep_refresh_data(),
            ("deep refresh", "rebuild cache", "refresh from workbook", "sync from workbook", "reload from workbook"),
            item_type=ITEM_COMMAND,
            action="deep_refresh",
        ),
        AtlasCommand(
            "action.queue_status_review",
            "Actions",
            "Queue EOAT Status Review",
            "Create a local pending status update for the current EOAT profile.",
            lambda: window.queue_current_eoat_status_review(),
            ("queue status review", "mark needs review", "pending status update"),
            item_type=ITEM_COMMAND,
            action="queue_status_review",
        ),
        AtlasCommand("action.copy_eoat_id", "Actions", "Copy EOAT ID", "Copy the current EOAT profile ID.", lambda: _copy_current_eoat(window), ("copy current eoat",)),
        AtlasCommand("action.export_profile", "Actions", "Export current profile summary", "Run the export action for the current EOAT, machine, or tool profile.", lambda: _export_current_profile(window), ("export summary",)),
        AtlasCommand("report.documentation_gaps", "Reports", "Generate Documentation Gap Report", "Export missing data and warning rows.", lambda: _run_export(window, export_documentation_gap_report), ("export documentation gaps", "documentation gaps")),
        AtlasCommand("report.photo_coverage", "Reports", "Generate Photo Coverage Report", "Export photo counts and missing categories.", lambda: _run_export(window, export_photo_coverage_report), ("missing photos", "photo coverage")),
        AtlasCommand("report.compatibility_csv", "Reports", "Generate Fit Check CSV", "Export Fit Check data table rows.", lambda: _run_export(window, export_compatibility_matrix), ("fit check csv", "fit check table", "export fit check")),
        AtlasCommand("report.pm_package", "Reports", "Generate PM Checklist Package", "Generate the PM checklist package report.", lambda: _run_catalog_report(window, "pm.package"), ("pm checklist",)),
        AtlasCommand("report.final_handoff", "Reports", "Build Final Handoff Package", "Generate a final handoff package index/report.", lambda: _run_catalog_report(window, "handoff.package"), ("final handoff",)),
        AtlasCommand(
            "settings.open",
            "Settings",
            "Open Settings",
            "Open app settings and basic diagnostics.",
            lambda: window.show_page("settings"),
            ("settings", "diagnostics"),
            item_type=ITEM_NAVIGATION,
            route="settings",
        ),
        AtlasCommand("settings.dark_mode", "Settings", "Toggle Dark Mode", "Switch between light and dark theme.", window.toggle_dark_mode, ("theme", "dark")),
    ]
    current_fit_setup = getattr(window, "current_fit_check_setup", lambda: None)()
    if current_fit_setup is not None:
        commands.append(
            AtlasCommand(
                "action.current_fit_packet",
                "Actions",
                "Create setup packet from current Fit Check",
                "Use the current valid Fit Check setup.",
                window.generate_install_packet_current_context,
                ("create packet", "setup packet", "create setup packet", "packet from fit check", "current fit check packet", "fit to packet", "create setup packet from current fit check"),
            )
        )
    return commands


def _entity_commands(window, bundle) -> list[AtlasCommand]:
    commands: list[AtlasCommand] = []
    for eoat in bundle.eoats[:300]:
        commands.append(
            AtlasCommand(
                f"eoat.{normalized_eoat_key(eoat.eoat_id)}",
                "Records",
                f"Open EOAT {eoat.eoat_id}",
                f"{eoat.eoat_type or 'EOAT'} | Tools: {', '.join(eoat.tools[:2]) or 'No tool'}",
                lambda eoat_id=eoat.eoat_id: window.open_eoat(eoat_id),
                (eoat.eoat_id, eoat.eoat_id.split("-")[-1], eoat.status, eoat.part_description, "why warning", "applicable standards"),
                item_type=ITEM_ENTITY_SEARCH,
                search_query=eoat.eoat_id,
                entity_type="eoat",
                entity_id=eoat.eoat_id,
                route_target=_entity_route_target("eoat", eoat.eoat_id),
            )
        )
    for machine in bundle.machines[:300]:
        commands.append(
            AtlasCommand(
                f"machine.{normalized_machine_key(machine.machine)}",
                "Records",
                f"Open Machine {machine.machine}",
                machine.robot_type or machine.robot_model or "Robot info missing",
                lambda machine_id=machine.machine: window.open_machine(machine_id),
                (f"machine {machine.machine}", f"open machine {machine.machine}", *machine.compatible_eoats[:8], *machine.compatible_tools[:8]),
                item_type=ITEM_ENTITY_SEARCH,
                search_query=machine.machine,
                entity_type="machine",
                entity_id=machine.machine,
                route_target=_entity_route_target("machine", machine.machine),
            )
        )
    for tool in bundle.tools[:350]:
        commands.append(
            AtlasCommand(
                f"tool.{normalized_tool_key(tool.tool)}",
                "Records",
                f"Open Tool {tool.tool}",
                tool.part_description or tool.part_family or "Tool Fit Check profile",
                lambda tool_id=tool.tool: window.open_tool(tool_id),
                (f"tool {tool.tool}", f"mold {tool.tool}", *tool.compatible_eoats[:8], *tool.compatible_machines[:8]),
                item_type=ITEM_ENTITY_SEARCH,
                search_query=tool.tool,
                entity_type="tool",
                entity_id=tool.tool,
                route_target=_entity_route_target("tool", tool.tool),
            )
        )
    return commands


def _question_commands(window, bundle) -> list[AtlasCommand]:
    missing_photos = [eoat.eoat_id for eoat in bundle.eoats if eoat.photo_count <= 0]
    tools_no_eoat = [tool.tool for tool in bundle.tools if not tool.compatible_eoats]
    machines_review = [machine.machine for machine in bundle.machines if machine_relationship_health(machine) != RelationshipHealth.VERIFIED]
    top_warnings = _top_warning_labels(bundle)
    return [
        _question(window, "question.missing_photos", "Which EOATs have zero photos?", missing_photos, ("missing photos", "zero photos", "show top photo gaps")),
        _question(window, "question.tools_no_eoat", "Which tools have no validated EOAT?", tools_no_eoat, ("tools with no eoat", "tools no EOAT", "missing validated eoat")),
        _question(window, "question.machines_review", "Which machines need review?", machines_review, ("machines need review", "highest-warning machines")),
        _question(window, "question.top_warnings", "Show top documentation gaps.", top_warnings, ("top documentation gaps", "top warnings", "incomplete eoat profiles")),
        AtlasCommand("question.changed", "Questions", "What changed after last refresh?", "Atlas tracks the current loaded timestamp in the status bar.", lambda: _show_result(window, f"Last refresh: {getattr(bundle, 'loaded_at', 'unknown')}"), ("changed", "last refresh")),
    ]


def _filter_view_commands(window, bundle) -> list[AtlasCommand]:
    missing_photos = sum(1 for eoat in bundle.eoats if eoat.photo_count <= 0)
    machines_missing_current = sum(1 for machine in bundle.machines if not str(getattr(machine, "current_eoat", "") or "").strip())
    tools_without_eoat = sum(1 for tool in bundle.tools if not getattr(tool, "compatible_eoats", ()))
    return [
        AtlasCommand(
            "filter.cleanroom_eoats",
            "Filters / Views",
            "Show cleanroom EOATs",
            "Open Library filtered to Cleanroom EOAT profiles.",
            lambda: _open_library_filtered(window, record_type="eoat", location="Cleanroom"),
            ("cleanroom eoats", "cl eoats", "cleanroom"),
            item_type=ITEM_NAVIGATION,
            route="library",
        ),
        AtlasCommand(
            "filter.plant4_eoats",
            "Filters / Views",
            "Show Plant 4 EOATs",
            "Open Library filtered to Plant 4 EOAT profiles.",
            lambda: _open_library_filtered(window, record_type="eoat", location="Plant 4"),
            ("plant 4 eoats", "p4 eoats", "plant4"),
            item_type=ITEM_NAVIGATION,
            route="library",
        ),
        AtlasCommand(
            "filter.missing_photos",
            "Filters / Views",
            "Show EOATs missing photos",
            f"{missing_photos} EOAT record(s) currently have no linked photo.",
            lambda: _open_library_filtered(window, record_type="eoat", lenses={"Missing Photos"}),
            ("eoats missing photos", "zero photos"),
            item_type=ITEM_NAVIGATION,
            route="library",
        ),
        AtlasCommand(
            "filter.machines_missing_current_eoat",
            "Filters / Views",
            "Show machines missing current EOAT",
            f"{machines_missing_current} machine record(s) may need current EOAT review.",
            lambda: _open_library_filtered(window, record_type="machine"),
            ("machines missing current eoat", "machines without current eoat"),
            item_type=ITEM_NAVIGATION,
            route="library",
        ),
        AtlasCommand(
            "filter.tools_without_eoat",
            "Filters / Views",
            "Show tools without assigned EOAT",
            f"{tools_without_eoat} tool record(s) have no validated EOAT link.",
            lambda: _open_library_filtered(window, record_type="tool"),
            ("tools without assigned eoat", "no validated eoat"),
            item_type=ITEM_NAVIGATION,
            route="library",
        ),
    ]


def _question(window, command_id: str, title: str, values: list[str], aliases: tuple[str, ...]) -> AtlasCommand:
    result = ", ".join(values[:12]) + (f" (+{len(values) - 12} more)" if len(values) > 12 else "")
    result = result or "No matching records."
    return AtlasCommand(command_id, "Questions", title, f"{len(values)} matching record(s).", lambda text=result: _show_result(window, text), aliases, result)


def _recent_and_pinned_commands(window) -> list[AtlasCommand]:
    settings = window.settings
    commands: list[AtlasCommand] = []
    for label, keys, opener in [
        ("Pinned EOAT", settings.pinned_eoats, window.open_eoat),
        ("Pinned Machine", settings.pinned_machines, window.open_machine),
        ("Pinned Tool", settings.pinned_tools, window.open_tool),
    ]:
        entity_type = _label_entity_type(label)
        for key in keys:
            commands.append(
                AtlasCommand(
                    f"pinned.{label}.{key}",
                    "Pinned",
                    f"Open {label} {key}",
                    "Pinned Atlas item.",
                    lambda key=key, opener=opener: opener(key),
                    (key,),
                    item_type=ITEM_ENTITY_SEARCH,
                    search_query=key,
                    entity_type=entity_type,
                    entity_id=key,
                    route_target=_entity_route_target(entity_type, key),
                )
            )
    for label, keys, opener in [
        ("Recent EOAT", settings.recent_eoats, window.open_eoat),
        ("Recent Machine", settings.recent_machines, window.open_machine),
        ("Recent Tool", settings.recent_tools, window.open_tool),
    ]:
        entity_type = _label_entity_type(label)
        for key in keys:
            commands.append(
                AtlasCommand(
                    f"recent.{label}.{key}",
                    "Recent",
                    f"Open {label} {key}",
                    "Recently viewed Atlas item.",
                    lambda key=key, opener=opener: opener(key),
                    (key,),
                    item_type=ITEM_RECENT_SEARCH,
                    search_query=key,
                    entity_type=entity_type,
                    entity_id=key,
                    route_target=_entity_route_target(entity_type, key),
                )
            )
    return commands


def _label_entity_type(label: str) -> str:
    folded = str(label or "").casefold()
    if "eoat" in folded:
        return "eoat"
    if "machine" in folded:
        return "machine"
    if "tool" in folded:
        return "tool"
    return ""


def _entity_route_target(entity_type: str, entity_id: str) -> dict[str, str]:
    return {"page": "library", "entity_type": str(entity_type or ""), "entity_id": str(entity_id or "")}


def _command_score(command: AtlasCommand, query: str, window, *, include_entity_records: bool = True) -> int:
    if not query:
        return 10
    text = command.searchable_text()
    folded = query.casefold().strip().rstrip("?")
    if include_entity_records:
        machine_key = _machine_query_key(folded)
        if machine_key and command.command_id == f"machine.{machine_key}":
            return 1000
        photo_key = _photo_query_key(folded, window)
        if photo_key and command.command_id in {f"photos.{photo_key}", f"dynamic.photos.{photo_key}"}:
            return 980
        tool_key = _tool_query_key(folded) or _exact_tool_query_key(folded, window)
        if tool_key and command.command_id == f"tool.{tool_key}":
            return 940
        eoat_key = _eoat_query_key(folded, window)
        if eoat_key and command.command_id == f"eoat.{eoat_key}":
            return 960
    if folded == command.title.casefold():
        return 900
    if folded in {str(alias or "").casefold() for alias in command.aliases}:
        return 880
    if folded in text:
        return 650
    terms = [term for term in re.split(r"\s+", folded) if term]
    hits = sum(term in text for term in terms)
    return hits * 80 if hits and hits == len(terms) else 0


def _machine_query_key(query: str) -> str:
    match = re.fullmatch(r"(?:open\s+)?(?:machine|press|m|p)?\s*[-#:]*\s*([1-9]\d*)", query)
    return normalized_machine_key(match.group(1)) if match else ""


def _tool_query_key(query: str) -> str:
    match = re.fullmatch(r"(?:open\s+)?(?:tool|mold|part)\s*[-#:]*\s*(\S+)", query)
    return normalized_tool_key(match.group(1)) if match else ""


def _exact_tool_query_key(query: str, window) -> str:
    if not re.fullmatch(r"\S+", query):
        return ""
    query_key = normalized_tool_key(query)
    if not query_key:
        return ""
    bundle = getattr(window, "bundle", None)
    if bundle is None:
        return ""
    for tool in bundle.tools:
        identifiers = (tool.tool, *getattr(tool, "molds", ()), *getattr(tool, "parts", ()))
        if any(normalized_tool_key(value) == query_key for value in identifiers):
            return query_key
    return ""


def _eoat_query_key(query: str, window) -> str:
    match = re.fullmatch(r"(?:open\s+)?(?:eoat|photos)?\s*[-#:]*\s*(p4[-\s]?eoat[-\s]?\d{1,4}|\d{1,4})", query)
    if not match:
        return ""
    value = match.group(1)
    if value.isdigit():
        suffix = f"{int(value):04d}"
        bundle = getattr(window, "bundle", None)
        if bundle is None:
            return ""
        for eoat in bundle.eoats:
            if eoat.eoat_id.split("-")[-1] == suffix:
                return normalized_eoat_key(eoat.eoat_id)
    return normalized_eoat_key(value)


def _photo_query_key(query: str, window) -> str:
    match = re.fullmatch(r"photos?\s+([a-z0-9\-\s]+)", query)
    if not match:
        return ""
    bundle = getattr(window, "bundle", None)
    if bundle is None:
        return ""
    eoat = _find_eoat_for_query(bundle, match.group(1).strip())
    return normalized_eoat_key(eoat.eoat_id) if eoat else ""


def _find_eoat_for_query(bundle, value: str):
    text = str(value or "").strip()
    key = normalized_eoat_key(text)
    suffix = f"{int(text):04d}" if text.isdigit() else ""
    for eoat in bundle.eoats:
        if normalized_eoat_key(eoat.eoat_id) == key or (suffix and eoat.eoat_id.split("-")[-1] == suffix):
            return eoat
    return None


def _find_eoat_for_query_or_current(window, bundle, value: str):
    folded = str(value or "").strip().casefold()
    if folded in {"this eoat", "current eoat", "eoat"}:
        current = getattr(getattr(window, "pages", {}).get("eoats"), "current", None)
        if current is not None:
            return current
    return _find_eoat_for_query(bundle, value)


def _find_machine_for_query(bundle, value: str):
    key = normalized_machine_key(value)
    for machine in bundle.machines:
        if normalized_machine_key(machine.machine) == key:
            return machine
    return None


def _find_tool_for_query(bundle, value: str):
    key = normalized_tool_key(value)
    for tool in bundle.tools:
        if normalized_tool_key(tool.tool) == key:
            return tool
    return None


def _run_export(window, exporter) -> None:
    bundle = getattr(window, "bundle", None)
    if bundle is None:
        window.show_status("Atlas data is still loading.")
        return
    path = exporter(bundle)
    window.show_status(f"Generated: {path}")


def _run_catalog_report(window, report_id: str) -> None:
    bundle = getattr(window, "bundle", None)
    if bundle is None:
        window.show_status("Atlas data is still loading.")
        return
    path = generate_atlas_report(bundle, report_id)
    window.show_status(f"Generated: {path}")


def _open_library_filtered(window, *, record_type: str = "all", location: str = "", lenses: set[str] | None = None) -> None:
    window.show_page("library")
    page = getattr(window, "library_page", None)
    opener = getattr(page, "open_filtered_view", None)
    if callable(opener):
        opener(record_type=record_type, location=location, lenses=lenses or set())


def _copy_current_eoat(window) -> None:
    page = getattr(window, "pages", {}).get("eoats")
    current = getattr(page, "current", None)
    if current is not None:
        QApplication.clipboard().setText(current.eoat_id)
        window.show_status(f"Copied {current.eoat_id}.")
    else:
        window.show_status("Open an EOAT profile before copying an EOAT ID.")


def _export_current_profile(window) -> None:
    page = getattr(window, "pages", {}).get(getattr(window, "current_page_key", ""))
    for name in ("export_current", "export_current_tool"):
        handler = getattr(page, name, None)
        if callable(handler):
            handler()
            return
    window.show_status("Open an EOAT, machine, or tool profile before exporting a profile summary.")


def _show_result(window, text: str) -> None:
    _show_status(window, text)


def _show_status(window, text: str) -> None:
    handler = getattr(window, "show_status", None)
    if callable(handler):
        handler(text)


def _log_palette_selection(window, command: AtlasCommand, *, query: str = "") -> None:
    payload = {
        "selected_item_id": command.command_id,
        "selected_item_label": command.title,
        "selected_item_type": command.item_type,
        "selected_route": command.route,
        "selected_action": command.action,
        "selected_search_query": command.search_query,
        "typed_query": str(query or ""),
        "category": command.category,
    }
    try:
        LOGGER.info("Command Palette selection: %s", payload)
        config = getattr(window, "config", None)
        project_root = str(getattr(config, "project_root", "") or "")
        if project_root:
            warning = log_activity_event(project_root, "command_palette_selection", payload)
            if warning:
                _report_palette_logging_failure(warning)
    except Exception as exc:
        _report_palette_logging_failure(f"Command Palette selection logging failed: {type(exc).__name__}: {exc}")


def _report_palette_logging_failure(message: object) -> None:
    """Report telemetry failures without creating another logging record."""
    try:
        stream = sys.__stderr__
        if stream is not None:
            stream.write(f"{message}\n")
            stream.flush()
    except Exception:
        pass


def _top_warning_labels(bundle) -> list[str]:
    rows: list[tuple[int, str]] = []
    rows.extend((eoat.warning_count, eoat.eoat_id) for eoat in bundle.eoats if eoat.warning_count)
    rows.extend((machine.warning_count, f"Machine {machine.machine}") for machine in bundle.machines if machine.warning_count)
    rows.extend((tool.warning_count, f"Tool {tool.tool}") for tool in bundle.tools if tool.warning_count)
    return [label for _count, label in sorted(rows, key=lambda item: (-item[0], item[1].casefold()))[:12]]


__all__ = [
    "ITEM_COMMAND",
    "ITEM_ENTITY_SEARCH",
    "ITEM_NAVIGATION",
    "ITEM_RECENT_ACTION",
    "ITEM_RECENT_SEARCH",
    "VALID_PALETTE_ITEM_TYPES",
    "AtlasCommand",
    "AtlasCommandPalette",
    "build_atlas_commands",
    "resolve_atlas_commands",
    "_log_palette_selection",
]
