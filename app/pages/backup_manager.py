from __future__ import annotations

import json
import time

try:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QVBoxLayout, QWidget
except ImportError:  # pragma: no cover
    QGridLayout = QHBoxLayout = QLabel = QMessageBox = QPushButton = QTableWidget = QVBoxLayout = QWidget = None

from app.page_async import AsyncRefreshMixin, log_page_performance
from app.page_tasks import run_tool_background
from app.pages.analysis_widgets import populate_table
from app.widgets.status_card import StatusCard
from app.widgets.tool_run_panel import ToolRunPanel
from core.backup_manager import cleanup_old_backups, preview_backup_cleanup, summarize_backups
from core.openers import open_path
from core.paths import resolve_project_paths


class BackupManagerPage(AsyncRefreshMixin, QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._init_async_refresh("backup_manager")
        self.cards: dict[str, StatusCard] = {}
        self._summary_data: dict | None = None

        layout = QVBoxLayout(self)
        heading = QLabel("Backup Manager")
        heading.setStyleSheet("font-size: 18pt; font-weight: 600;")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        preview = QPushButton("Preview Cleanup")
        preview.clicked.connect(self.preview_cleanup)
        clean = QPushButton("Clean Safe Old Backups")
        clean.clicked.connect(self.clean_backups)
        open_folder = QPushButton("Open Backup Folder")
        open_folder.clicked.connect(self.open_backup_folder)
        for button in [self.refresh_button, preview, clean, open_folder]:
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        grid = QGridLayout()
        for index, label in enumerate(["Backup Count", "Total Size", "Oldest Backup", "Newest Backup", "Cleanup Candidates", "Validation Blockers"]):
            card = StatusCard(label)
            self.cards[label] = card
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        policy = QLabel("Retention policy: keep all backups from the last 7 days, keep the newest 25 per workbook, keep milestone backups, and refuse cleanup when validation has blockers.")
        policy.setWordWrap(True)
        layout.addWidget(policy)

        layout.addWidget(QLabel("Cleanup Candidates"))
        self.table = QTableWidget()
        layout.addWidget(self.table, stretch=2)

        self.result_panel = ToolRunPanel()
        self.result_panel.setMaximumHeight(220)
        layout.addWidget(self.result_panel)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.on_show()

    def refresh(self, *_args, force: bool = False) -> bool:
        return self._begin_background_refresh(
            task_id="backup_manager_refresh",
            name="Backup Manager Refresh",
            load=lambda: summarize_backups(self.config.project_root),
            apply_result=self._apply_refresh_result,
            button=self.refresh_button,
            force=force,
            loading_text="Scanning backup folders in background...",
        )

    def refresh_data(self) -> None:
        self.refresh()

    def on_show(self) -> None:
        self._show_cached_summary()
        self.refresh()
        return True

    def preview_cleanup(self) -> None:
        run_tool_background(self.result_panel, "backup_preview_cleanup", "Preview Backup Cleanup", lambda: preview_backup_cleanup(self.config.project_root), self._after_tool)

    def clean_backups(self) -> None:
        summary = self._summary_data or {}
        blockers = list(summary.get("validation_blockers", []))
        candidates = list(summary.get("cleanup_candidates", []))
        if blockers:
            self.result_panel.show_text("Cleanup is disabled because validation has blockers.")
            self._show_summary_data(summary)
            return
        if not candidates:
            self.result_panel.show_text("No safe old backup cleanup candidates found. Refresh or preview cleanup before cleaning.")
            self._show_summary_data(summary)
            return
        answer = QMessageBox.question(
            self,
            "Confirm Backup Cleanup",
            f"Delete {len(candidates)} old backup file(s)? This cannot be undone.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.result_panel.show_text("Backup cleanup canceled.")
            self._show_summary_data(summary)
            return
        run_tool_background(
            self.result_panel,
            "backup_clean_old",
            "Clean Old Backups",
            lambda: cleanup_old_backups(self.config.project_root, confirm=True, dry_run=False),
            self._after_tool,
            modifies_files=True,
        )

    def open_backup_folder(self) -> None:
        result = open_path(resolve_project_paths(self.config.project_root).project_admin / "Backups")
        if not result.success:
            self.result_panel.show_result(result)

    def _after_tool(self, result) -> None:
        data = result.structured_data or {}
        if data:
            self._summary_data = data
            _write_cache(self.config.project_root, data)
            candidates = data.get("cleanup_candidates", [])
            self._populate_candidate_rows(candidates)
            self.cards["Backup Count"].set_value(str(data.get("backup_count", 0)))
            self.cards["Cleanup Candidates"].set_value(str(len(candidates)))
            self.cards["Validation Blockers"].set_value(str(len(data.get("validation_blockers", []))))
        else:
            self.refresh(force=True)

    def _show_cached_summary(self) -> None:
        data, generated_at, warning = _read_cache(self.config.project_root)
        if not data:
            self.result_panel.show_text(f"{warning or 'No cached backup summary yet.'} Scanning in background...")
            return
        self._summary_data = data
        self._show_summary_data(data)
        self.result_panel.show_text(f"Showing cached backup summary from {_time_label(generated_at)}. Scanning in background...")

    def _apply_refresh_result(self, summary, data_load_seconds: float) -> None:
        render_started = time.perf_counter()
        self._show_summary(summary)
        render_seconds = time.perf_counter() - render_started
        data = summary.to_dict()
        self._summary_data = data
        _write_cache(self.config.project_root, data)
        log_page_performance(
            self.config.project_root,
            "backup_manager",
            "data_load",
            data_load_seconds,
            details={
                "row_count": len(summary.cleanup_candidates),
                "source_counts": {"backups": summary.backup_count, "validation_blockers": len(summary.validation_blockers)},
            },
        )
        log_page_performance(
            self.config.project_root,
            "backup_manager",
            "table_render",
            render_seconds,
            details={"row_count": len(summary.cleanup_candidates)},
        )
        lines = [f"Loaded {summary.backup_count} backup(s) in {data_load_seconds:.1f}s.", "Backup cleanup always requires preview and confirmation."]
        lines.extend(summary.warnings)
        self.result_panel.show_text("\n".join(lines))

    def _show_summary(self, summary) -> None:
        self.cards["Backup Count"].set_value(str(summary.backup_count))
        self.cards["Total Size"].set_value(_format_bytes(summary.total_size_bytes))
        self.cards["Oldest Backup"].set_value(summary.oldest_backup[:10] if summary.oldest_backup else "None")
        self.cards["Newest Backup"].set_value(summary.newest_backup[:10] if summary.newest_backup else "None")
        self.cards["Cleanup Candidates"].set_value(str(len(summary.cleanup_candidates)))
        self.cards["Validation Blockers"].set_value(str(len(summary.validation_blockers)))
        self._populate_candidate_rows([item.to_dict() for item in summary.cleanup_candidates])

    def _show_summary_data(self, data: dict) -> None:
        self.cards["Backup Count"].set_value(str(data.get("backup_count", 0)))
        self.cards["Total Size"].set_value(_format_bytes(int(data.get("total_size_bytes") or 0)))
        self.cards["Oldest Backup"].set_value(str(data.get("oldest_backup") or "None")[:10])
        self.cards["Newest Backup"].set_value(str(data.get("newest_backup") or "None")[:10])
        self.cards["Cleanup Candidates"].set_value(str(len(data.get("cleanup_candidates", []))))
        self.cards["Validation Blockers"].set_value(str(len(data.get("validation_blockers", []))))
        self._populate_candidate_rows(list(data.get("cleanup_candidates", [])))

    def _populate_candidate_rows(self, rows: list[dict]) -> None:
        populate_table(self.table, rows, ["source_workbook", "age_days", "size_bytes", "milestone", "keep_reason", "path"])


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


def _cache_path(project_root):
    return resolve_project_paths(project_root).cache / "backup_manager_summary.json"


def _read_cache(project_root) -> tuple[dict | None, str | None, str | None]:
    path = _cache_path(project_root)
    if not path.exists():
        return None, None, "No cached backup summary found."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, None, f"Could not read cached backup summary: {exc}"
    if not isinstance(payload, dict):
        return None, None, "Cached backup summary was invalid."
    return dict(payload.get("summary") or {}), str(payload.get("generated_at") or ""), None


def _write_cache(project_root, summary: dict) -> None:
    path = _cache_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime

    path.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "summary": summary}, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def _time_label(value: str | None) -> str:
    if not value:
        return "last cache"
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value)).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return str(value)
