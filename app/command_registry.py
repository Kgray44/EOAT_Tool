from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.openers import open_path
from core.paths import resolve_project_paths
from core.reports import report_folders


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
    description: str = ""

    def searchable_text(self) -> str:
        return " ".join([self.display_name, self.category, self.description, *self.aliases]).casefold()


@dataclass
class CommandRegistry:
    commands: list[CommandSpec] = field(default_factory=list)

    def register(self, command: CommandSpec) -> None:
        if any(existing.command_id == command.command_id for existing in self.commands):
            raise ValueError(f"Duplicate command id: {command.command_id}")
        self.commands.append(command)

    def get(self, command_id: str) -> CommandSpec:
        for command in self.commands:
            if command.command_id == command_id:
                return command
        raise KeyError(command_id)

    def filter(self, query: str = "", *, category: str = "") -> list[CommandSpec]:
        needle = query.casefold().strip()
        rows = []
        for command in self.commands:
            if category and category != "All" and command.category != category:
                continue
            if needle and needle not in command.searchable_text():
                continue
            rows.append(command)
        return sorted(rows, key=lambda command: (not command.enabled, command.category, command.display_name.casefold()))

    def execute(self, command_id: str) -> bool:
        command = self.get(command_id)
        if not command.enabled or command.handler is None:
            return False
        command.handler()
        return True

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

    for page_key, label in [
        ("home", "Open Home"),
        ("audit", "Open EOAT Audit"),
        ("press_view", "Open Press View"),
        ("open_items", "Open Open Items"),
        ("workbook_health", "Open Workbook Health"),
        ("scheduled_reports", "Open Scheduled Reports"),
        ("reports", "Open Reports"),
        ("backup_manager", "Open Backup Manager"),
        ("release_readiness", "Open Release Readiness"),
        ("settings", "Open Settings"),
    ]:
        registry.register(
            CommandSpec(
                command_id=f"nav.{page_key}",
                display_name=label,
                aliases=(page_key.replace("_", " "), label.replace("Open ", "")),
                category="Navigation",
                handler=navigate(page_key),
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
            description="Generates the current weekly summary without overwriting an existing report.",
        )
    )
    registry.register(
        CommandSpec(
            "reports.open_latest",
            "Open Latest Report",
            aliases=("latest report", "recent report"),
            category="Reports",
            handler=lambda: _open_latest_report(window),
        )
    )
    registry.register(
        CommandSpec(
            "project.open_folder",
            "Open Project Folder",
            aliases=("project root", "folder"),
            category="Settings",
            handler=lambda: open_path(resolve_project_paths(window.config.project_root).project_root),
        )
    )
    registry.register(
        CommandSpec(
            "open_items.refresh",
            "Refresh Open Items",
            aliases=("action board", "follow ups"),
            category="Open Items",
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
