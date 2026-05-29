from __future__ import annotations

import json
import time

try:
    from PySide6.QtWidgets import (
        QApplication,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover
    QApplication = QGridLayout = QHBoxLayout = QLabel = QPushButton = QTableWidget = QTextEdit = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import populate_table
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.constants import TOOLKIT_ROOT
from core.openers import open_path
from core.release_readiness import (
    collect_release_readiness,
    commit_checklist_markdown,
    install_pre_commit_hook,
    run_release_tests,
    run_repo_safety_audit,
    show_staged_files,
)


class ReleaseReadinessPage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("release_readiness")
        self.cards: dict[str, StatusCard] = {}

        layout = QVBoxLayout(self)
        heading = QLabel("Release Readiness")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self.refresh_button = None
        for label, callback in [
            ("Refresh", lambda: self.refresh(force=True)),
            ("Run Tests", self.run_tests),
            ("Run Repo Safety Audit", self.run_safety_audit),
            ("Show Staged Files", self.show_staged_files),
            ("Open Sanitization Report", self.open_sanitization_report),
            ("Copy Commit Checklist", self.copy_commit_checklist),
            ("Install Pre-Commit Hook", self.install_hook),
        ]:
            button = QPushButton(label)
            if label == "Refresh":
                self.refresh_button = button
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        grid = QGridLayout()
        for index, label in enumerate(["Ready", "Branch", "Staged Files", "Failed Checks", "Warnings", "Git Status"]):
            card = StatusCard(label)
            self.cards[label] = card
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        self.table = QTableWidget()
        layout.addWidget(self.table, stretch=2)

        self.staged_preview = QTextEdit()
        self.staged_preview.setReadOnly(True)
        self.staged_preview.setMaximumHeight(120)
        layout.addWidget(self.staged_preview)

        self.result_panel = ToolRunPanel()
        self.result_panel.setMaximumHeight(220)
        layout.addWidget(self.result_panel)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        return self._begin_background_refresh(
            task_id="release_readiness_refresh",
            name="Release Readiness Refresh",
            load=lambda: collect_release_readiness(TOOLKIT_ROOT, git_executable=self.config.git_executable, include_staged_safety_scan=False),
            apply_result=self._apply_refresh_result,
            button=self.refresh_button,
            force=force,
            loading_text="Checking release readiness in background...",
        )

    def refresh_data(self) -> None:
        self.refresh()

    def on_show(self) -> None:
        self._show_cached_summary()
        self.refresh()
        return True

    def run_tests(self) -> None:
        run_tool_background(self.result_panel, "release_run_tests", "Release Tests", lambda: run_release_tests(TOOLKIT_ROOT), lambda _result: self.refresh(force=True))

    def run_safety_audit(self) -> None:
        run_tool_background(
            self.result_panel,
            "release_repo_safety_audit",
            "Repo Safety Audit",
            lambda: run_repo_safety_audit(TOOLKIT_ROOT, staged_only=False, git_executable=self.config.git_executable),
            lambda _result: self.refresh(force=True),
        )

    def show_staged_files(self) -> None:
        run_tool_background(
            self.result_panel,
            "release_show_staged",
            "Show Staged Files",
            lambda: show_staged_files(TOOLKIT_ROOT, git_executable=self.config.git_executable),
            lambda result: self.staged_preview.setPlainText("\n".join(result.details or result.errors or ["No staged files."])),
        )

    def open_sanitization_report(self) -> None:
        result = open_path(TOOLKIT_ROOT / "docs" / "repo_sanitization_report.md")
        if not result.success:
            self.result_panel.show_result(result)

    def copy_commit_checklist(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(commit_checklist_markdown())
        self.result_panel.show_text("Commit checklist copied to clipboard.")

    def install_hook(self) -> None:
        run_tool_background(
            self.result_panel,
            "release_install_pre_commit_hook",
            "Install Pre-Commit Hook",
            lambda: install_pre_commit_hook(TOOLKIT_ROOT, git_executable=self.config.git_executable, force=False),
            modifies_files=True,
        )

    def _show_cached_summary(self) -> None:
        data, generated_at, warning = _read_cache(self.config.project_root)
        if not data:
            self.result_panel.show_text(f"{warning or 'No cached release readiness yet.'} Checking in background...")
            return
        self._show_summary_data(data)
        self.result_panel.show_text(f"Showing cached release readiness from {_time_label(generated_at)}. Checking in background...")

    def _apply_refresh_result(self, summary, data_load_seconds: float) -> None:
        render_started = time.perf_counter()
        self._show_summary(summary)
        render_seconds = time.perf_counter() - render_started
        data = summary.to_dict()
        _write_cache(self.config.project_root, data)
        log_page_performance(
            self.config.project_root,
            "release_readiness",
            "data_load",
            data_load_seconds,
            details={"row_count": len(summary.checks), "source_counts": {"staged_files": len(summary.staged_files), "git_status": len(summary.git_status)}},
        )
        log_page_performance(
            self.config.project_root,
            "release_readiness",
            "table_render",
            render_seconds,
            details={"row_count": len(summary.checks)},
        )
        self.result_panel.show_text(
            f"Release readiness loaded in {data_load_seconds:.1f}s. Run tests and the full repo safety audit before committing."
        )

    def _show_summary(self, summary) -> None:
        failed = [check for check in summary.checks if check.status == "fail"]
        warnings = [check for check in summary.checks if check.status in {"warning", "unknown"}]
        self.cards["Ready"].set_value("Yes" if summary.ready else "No")
        self.cards["Branch"].set_value(summary.branch or "Unknown")
        self.cards["Staged Files"].set_value(str(len(summary.staged_files)))
        self.cards["Failed Checks"].set_value(str(len(failed)))
        self.cards["Warnings"].set_value(str(len(warnings)))
        self.cards["Git Status"].set_value(f"{len(summary.git_status)} line(s)" if not summary.git_warning else "Warning")
        populate_table(
            self.table,
            [check.to_dict() for check in summary.checks],
            ["label", "status", "details", "severity"],
        )
        self.staged_preview.setPlainText("\n".join(summary.staged_files) or "No staged files.")

    def _show_summary_data(self, data: dict) -> None:
        checks = list(data.get("checks", []))
        failed = [check for check in checks if check.get("status") == "fail"]
        warnings = [check for check in checks if check.get("status") in {"warning", "unknown"}]
        staged = list(data.get("staged_files", []))
        git_status = list(data.get("git_status", []))
        self.cards["Ready"].set_value("Yes" if data.get("ready") else "No")
        self.cards["Branch"].set_value(str(data.get("branch") or "Unknown"))
        self.cards["Staged Files"].set_value(str(len(staged)))
        self.cards["Failed Checks"].set_value(str(len(failed)))
        self.cards["Warnings"].set_value(str(len(warnings)))
        self.cards["Git Status"].set_value(f"{len(git_status)} line(s)" if not data.get("git_warning") else "Warning")
        populate_table(self.table, checks, ["label", "status", "details", "severity"])
        self.staged_preview.setPlainText("\n".join(staged) or "No staged files.")


def _cache_path(project_root):
    from core.paths import resolve_project_paths

    return resolve_project_paths(project_root).cache / "release_readiness_summary.json"


def _read_cache(project_root) -> tuple[dict | None, str | None, str | None]:
    path = _cache_path(project_root)
    if not path.exists():
        return None, None, "No cached release readiness found."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"Could not read cached release readiness: {exc}"
    if not isinstance(payload, dict):
        return None, None, "Cached release readiness was invalid."
    return dict(payload.get("summary") or {}), str(payload.get("generated_at") or ""), None


def _write_cache(project_root, summary: dict) -> None:
    from datetime import datetime

    path = _cache_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "summary": summary}, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def _time_label(value: str | None) -> str:
    if not value:
        return "last cache"
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value)).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return str(value)
