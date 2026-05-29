from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.openers import open_path
from core.paths import resolve_project_paths
from core.reports import report_folders
from .feature_registry import build_feature_registry


CommandHandler = Callable[[], None]


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    display_name: str
    aliases: tuple[str, ...] = ()
    category: str = "Navigation"
    handler: CommandHandler | None = None
    safety_level: str = "safe"
    requires_confirmation: bool = False
    enabled: bool = True
    disabled_reason: str = ""
    writes_files: bool = False
    page_key: str = ""
    context_pages: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        unsafe = self.safety_level.casefold() not in {"", "safe", "read_only", "read-only"} or self.writes_files
        if unsafe and not self.requires_confirmation:
            object.__setattr__(self, "requires_confirmation", True)
        if unsafe and not self.writes_files:
            object.__setattr__(self, "writes_files", True)
        if not self.enabled and not self.disabled_reason:
            object.__setattr__(self, "disabled_reason", "Unavailable in the current context.")

    def searchable_text(self) -> str:
        return " ".join([self.command_id, self.display_name, self.category, self.description, self.page_key, self.disabled_reason, *self.aliases]).casefold()

    def is_context_command(self, current_page_key: str | None) -> bool:
        if not current_page_key:
            return False
        pages = self.context_pages or ((self.page_key,) if self.page_key else ())
        return current_page_key in pages


@dataclass
class CommandRegistry:
    commands: list[CommandSpec] = field(default_factory=list)
    recent_command_ids: list[str] = field(default_factory=list)

    def register(self, command: CommandSpec) -> None:
        if any(existing.command_id == command.command_id for existing in self.commands):
            raise ValueError(f"Duplicate command id: {command.command_id}")
        self.commands.append(command)

    def get(self, command_id: str) -> CommandSpec:
        for command in self.commands:
            if command.command_id == command_id:
                return command
        raise KeyError(command_id)

    def filter(self, query: str = "", *, category: str = "", current_page_key: str | None = None, include_recent: bool = True) -> list[CommandSpec]:
        needle = query.casefold().strip()
        rows = []
        for command in self.commands:
            if category and category != "All" and command.category != category:
                continue
            if needle and needle not in command.searchable_text():
                continue
            rows.append(command)
        recent_rank = {command_id: index for index, command_id in enumerate(self.recent_command_ids)}
        return sorted(
            rows,
            key=lambda command: (
                not command.enabled,
                not command.is_context_command(current_page_key),
                recent_rank.get(command.command_id, 9999) if include_recent else 9999,
                command.category,
                command.display_name.casefold(),
            ),
        )

    def execute(self, command_id: str) -> bool:
        command = self.get(command_id)
        if not command.enabled or command.handler is None:
            return False
        command.handler()
        self.record_recent(command_id)
        return True

    def record_recent(self, command_id: str, *, limit: int = 8) -> None:
        self.recent_command_ids = [item for item in self.recent_command_ids if item != command_id]
        self.recent_command_ids.insert(0, command_id)
        del self.recent_command_ids[limit:]

    def recent_commands(self, *, limit: int = 5) -> list[CommandSpec]:
        rows: list[CommandSpec] = []
        for command_id in self.recent_command_ids[:limit]:
            try:
                rows.append(self.get(command_id))
            except KeyError:
                continue
        return rows

    def validate(self) -> list[str]:
        warnings: list[str] = []
        ids = [command.command_id for command in self.commands]
        if len(ids) != len(set(ids)):
            warnings.append("Duplicate command IDs detected.")
        for command in self.commands:
            if command.writes_files and not command.requires_confirmation:
                warnings.append(f"File-modifying command does not require confirmation: {command.command_id}")
            if not command.enabled and not command.disabled_reason:
                warnings.append(f"Disabled command has no reason: {command.command_id}")
        return warnings

    def categories(self) -> list[str]:
        return sorted({command.category for command in self.commands})


def build_dashboard_command_registry(window) -> CommandRegistry:
    registry = CommandRegistry()

    def navigate(page_key: str) -> Callable[[], None]:
        return lambda: window.navigate_to_page(page_key) if hasattr(window, "navigate_to_page") else window._navigate_to_page(page_key)

    def call_page(page_key: str, method_name: str) -> Callable[[], None]:
        def _handler() -> None:
            if hasattr(window, "navigate_to_page"):
                window.navigate_to_page(page_key)
            else:
                window._navigate_to_page(page_key)
            page = getattr(window, "pages", {}).get(page_key)
            method = getattr(page, method_name, None)
            if callable(method):
                method()

        return _handler

    for feature in build_feature_registry().list_features():
        if not feature.route.startswith("page:"):
            continue
        page_key = feature.route.split(":", 1)[1]
        registry.register(
            CommandSpec(
                command_id=f"nav.{page_key}",
                display_name=f"Open {feature.label}",
                aliases=(page_key.replace("_", " "), feature.label, *feature.tool_ids),
                category="Navigation",
                handler=navigate(page_key),
                page_key=page_key,
                context_pages=(page_key,),
                description=feature.description,
            )
        )

    registry.register(
        CommandSpec(
            "validation.run_foundation",
            "Run Workbook Validation",
            aliases=("validate", "foundation validation", "workbook health"),
            category="Validation",
            handler=call_page("workbook_health", "run_validation"),
            safety_level="modifies_files",
            requires_confirmation=True,
            writes_files=True,
            page_key="workbook_health",
            context_pages=("workbook_health",),
            description="Runs workbook validation and writes a validation report.",
        )
    )
    registry.register(
        CommandSpec(
            "dashboard.deep_refresh",
            "Deep Refresh Dashboard",
            aliases=("refresh dashboard", "recompute home"),
            category="Navigation",
            handler=call_page("home", "deep_refresh_status"),
            safety_level="modifies_files",
            requires_confirmation=True,
            writes_files=True,
            page_key="home",
            context_pages=("home",),
            description="Recomputes dashboard data and refreshes the local cache.",
        )
    )
    registry.register(
        CommandSpec(
            "scheduled_reports.generate_daily",
            "Generate Daily Summary",
            aliases=("daily report", "daily summary now"),
            category="Scheduled Reports",
            handler=call_page("scheduled_reports", "run_daily_now"),
            safety_level="modifies_files",
            requires_confirmation=True,
            writes_files=True,
            page_key="scheduled_reports",
            context_pages=("scheduled_reports",),
            description="Generates today's daily summary without overwriting an existing report.",
        )
    )
    registry.register(
        CommandSpec(
            "scheduled_reports.generate_weekly",
            "Generate Weekly Summary",
            aliases=("weekly report", "weekly summary now"),
            category="Scheduled Reports",
            handler=call_page("scheduled_reports", "run_weekly_now"),
            safety_level="modifies_files",
            requires_confirmation=True,
            writes_files=True,
            page_key="scheduled_reports",
            context_pages=("scheduled_reports",),
            description="Generates the current weekly summary without overwriting an existing report.",
        )
    )
    registry.register(
        CommandSpec(
            "reports.open_latest",
            "Open Latest Report",
            aliases=("latest report", "recent report"),
            category="Reports",
            page_key="reports",
            context_pages=("reports",),
            handler=lambda: _open_latest_report(window),
        )
    )
    registry.register(
        CommandSpec(
            "project.open_folder",
            "Open Project Folder",
            aliases=("project root", "folder"),
            category="Settings",
            page_key="settings",
            context_pages=("settings", "app_health"),
            handler=lambda: open_path(resolve_project_paths(window.config.project_root).project_root),
        )
    )
    registry.register(
        CommandSpec(
            "open_items.refresh",
            "Refresh Open Items",
            aliases=("action board", "follow ups"),
            category="Open Items",
            page_key="open_items",
            context_pages=("open_items",),
            handler=call_page("open_items", "refresh"),
        )
    )
    return registry


def _open_latest_report(window) -> None:
    latest = None
    for folder in report_folders(window.config.project_root, limit=10):
        for path in folder.recent_files:
            if latest is None or path.stat().st_mtime > latest.stat().st_mtime:
                latest = path
    if latest is not None:
        open_path(latest)
        return
    if hasattr(window, "statusBar"):
        window.statusBar().showMessage("No reports were found to open.", 9000)
