from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.task_runner import BackgroundTaskManager, TaskResult
from core.audit_entries import CURRENT_WORKBOOK_SCHEMA_VERSION, WORKBOOK_METADATA_SHEET
from core.config import UserConfig
from core.constants import EXPECTED_NUMBERED_FOLDERS
from core.result import ToolResult
from core.workbook_schema import get_expected_headers, get_expected_sheets
from tests.fixtures.fake_config import create_fake_config
from tests.fixtures.fake_project import create_fake_eoat_project, create_minimal_fake_project

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def cleanup_qt_widgets():
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


@pytest.fixture(autouse=True)
def deterministic_ui_task_manager(monkeypatch):
    import app.task_runner as task_runner

    manager = BackgroundTaskManager()

    def run_task_immediately(request, on_finished=None, button=None):
        allowed, reason = manager.guard.try_start(request)
        if not allowed:
            result = TaskResult(id=request.id, name=request.name, ok=False, message=reason, error=reason)
            manager.task_rejected.emit(result)
            if on_finished:
                on_finished(result)
            return False
        if button is not None:
            button.setEnabled(False)
        manager.task_started.emit(request)
        try:
            value = request.callable(*request.args, **request.kwargs)
            if isinstance(value, ToolResult):
                result = TaskResult(
                    id=request.id,
                    name=request.name,
                    ok=value.success,
                    message=value.summary,
                    result_data=value,
                    files_created=value.files_created[:],
                    files_modified=value.files_modified[:],
                    warnings=value.warnings[:],
                    error="; ".join(value.errors),
                    duration_seconds=value.duration_seconds or 0.0,
                )
            else:
                result = TaskResult(
                    id=request.id, name=request.name, ok=True, message=f"{request.name} completed.", result_data=value
                )
        except Exception as exc:
            result = TaskResult(
                id=request.id,
                name=request.name,
                ok=False,
                message=f"{request.name} failed.",
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            manager.guard.finish(request)
            if button is not None:
                button.setEnabled(True)
        manager.task_finished.emit(result)
        if on_finished:
            on_finished(result)
        return True

    manager.run_task = run_task_immediately
    monkeypatch.setattr(task_runner, "_manager", manager)
    yield manager


@pytest.fixture
def fake_project(tmp_path) -> Path:
    for folder in EXPECTED_NUMBERED_FOLDERS:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    (tmp_path / "00_Project_Admin" / "Daily_Status_Reports").mkdir(exist_ok=True)
    (tmp_path / "00_Project_Admin" / "Weekly_Status_Reports").mkdir(exist_ok=True)
    (tmp_path / "00_Project_Admin" / "Activity_Logs").mkdir(exist_ok=True)
    workbook_dir = tmp_path / "01_EOAT_Audit" / "EOAT_Audit_Database"
    workbook_dir.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in get_expected_sheets():
        ws = workbook.create_sheet(sheet_name)
        ws.append(get_expected_headers(sheet_name))
    metadata = workbook.create_sheet(WORKBOOK_METADATA_SHEET)
    metadata.sheet_state = "hidden"
    metadata.append(["key", "value"])
    metadata.append(["schema_version", CURRENT_WORKBOOK_SCHEMA_VERSION])
    metadata.append(["app_name", "EOAT Command Center"])
    workbook.save(workbook_dir / "EOAT_Master_Tracker.xlsx")
    workbook.close()
    return tmp_path


@pytest.fixture
def usability_fake_project(tmp_path) -> Path:
    return create_fake_eoat_project(tmp_path)


@pytest.fixture
def minimal_fake_project(tmp_path) -> Path:
    return create_minimal_fake_project(tmp_path)


@pytest.fixture
def fake_config(fake_project: Path) -> UserConfig:
    return create_fake_config(fake_project)


@pytest.fixture
def usability_fake_config(usability_fake_project: Path) -> UserConfig:
    return create_fake_config(usability_fake_project)


@pytest.fixture
def captured_open_requests(monkeypatch):
    from core.result import ToolResult

    requests: list[Path] = []

    def fake_open(path):
        target = Path(path)
        requests.append(target)
        if not target.exists():
            return ToolResult.fail("open_path", "Open File or Folder", "Path does not exist.", errors=[str(target)])
        return ToolResult.ok("open_path", "Open File or Folder", f"Stubbed open: {target}", metrics={"stubbed": True})

    modules = [
        "app.pages.audit",
        "app.pages.audit_progress",
        "app.pages.bom_spares",
        "app.pages.fmea",
        "app.pages.handoff",
        "app.pages.home",
        "app.pages.issue_analysis",
        "app.pages.kpi_dashboard",
        "app.pages.photos",
        "app.pages.pilot_candidates",
        "app.pages.pm_checklists",
        "app.pages.reports",
        "app.pages.settings",
        "app.pages.standards_docs",
        "app.pages.workbook_health",
        "core.openers",
    ]
    for module_name in modules:
        module = __import__(module_name, fromlist=["open_path"])
        if hasattr(module, "open_path"):
            monkeypatch.setattr(module, "open_path", fake_open)
    return requests


@pytest.fixture
def frozen_project_date(monkeypatch):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 5, 19)

    for module_name in [
        "core.morning_planner",
        "core.schedule",
        "app.pages.audit",
        "app.pages.photos",
        "app.pages.reports",
    ]:
        module = __import__(module_name, fromlist=["date"])
        if hasattr(module, "date"):
            monkeypatch.setattr(module, "date", FrozenDate)
    return FrozenDate(2026, 5, 19)
