from __future__ import annotations

import argparse
import gc
import os
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.command_registry import build_dashboard_command_registry
from app.feature_registry import build_feature_registry
from app.page_registry import PAGE_SPECS, load_page_factory
from core.config import UserConfig
from core.constants import DEFAULT_PROJECT_ROOT, TOOLKIT_ROOT
from core.project_root_status import validate_project_root
from core.tool_registry import ToolRegistry
from scripts.repo_safety_audit import audit_repo


@dataclass
class _Config:
    project_root: str


class _SmokeWindow:
    def __init__(self, project_root: str | Path):
        self.config = _Config(str(project_root))
        self.pages = {}
        self.navigated: list[str] = []

    def navigate_to_page(self, page_key: str) -> None:
        self.navigated.append(page_key)


def run_registry_checks(project_root: str | Path = REPO_ROOT) -> list[str]:
    feature_registry = build_feature_registry()
    command_registry = build_dashboard_command_registry(_SmokeWindow(project_root))
    command_ids = [command.command_id for command in command_registry.commands]
    findings = feature_registry.validate(command_ids=command_ids)
    findings.extend(command_registry.validate())
    page_keys = [spec.key for spec in PAGE_SPECS]
    if len(page_keys) != len(set(page_keys)):
        findings.append("Duplicate page registry keys detected.")
    for spec in PAGE_SPECS:
        if not spec.factory_path or ":" not in spec.factory_path:
            findings.append(f"Invalid page factory path: {spec.key}")
        try:
            load_page_factory(spec)
        except Exception as exc:
            findings.append(f"Page factory import failed for {spec.key}: {exc}")
    for required in ["home", "audit", "reports", "settings"]:
        if feature_registry.get(required) is None:
            findings.append(f"Required feature is missing: {required}")
    return findings


def run_tool_registry_checks() -> list[str]:
    findings: list[str] = []
    try:
        registry = ToolRegistry.load()
    except Exception as exc:
        return [f"Tool registry could not be loaded: {exc}"]
    tools = registry.list_tools()
    ids = [tool.id for tool in tools]
    if not tools:
        findings.append("Tool registry is empty.")
    if len(ids) != len(set(ids)):
        findings.append("Duplicate tool registry IDs detected.")
    for tool in registry.implemented_tools():
        if tool.cli_module and tool.cli_module.startswith("tools/") and not (TOOLKIT_ROOT / tool.cli_module).exists():
            findings.append(f"Implemented tool CLI module is missing: {tool.id} -> {tool.cli_module}")
    return findings


def run_demo_project_checks() -> list[str]:
    status = validate_project_root(DEFAULT_PROJECT_ROOT)
    findings: list[str] = []
    if status.mode != "demo":
        findings.append(f"Default project root is not in demo mode: {status.mode_label} - {status.message}")
    if not status.master_workbook.exists():
        findings.append(f"Demo master workbook is missing: {status.master_workbook}")
    return findings


def run_dashboard_smoke(project_root: str | Path = DEFAULT_PROJECT_ROOT) -> list[str]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    smoke_env_value = os.environ.get("EOAT_COMMAND_CENTER_DASHBOARD_SMOKE")
    os.environ["EOAT_COMMAND_CENTER_DASHBOARD_SMOKE"] = "1"
    temp_root: Path | None = None
    try:
        try:
            from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
            from PySide6.QtWidgets import QApplication

            from app.dashboard_ui import DashboardWindow
        except Exception as exc:
            return [f"Dashboard smoke could not import PySide/dashboard modules: {exc}"]

        app = QApplication.instance() or QApplication([])
        temp_root = Path(tempfile.mkdtemp(prefix="eoat_dashboard_smoke_"))
        try:
            temp_project = temp_root / "demo_project"
            shutil.copytree(project_root, temp_project, ignore=_demo_runtime_ignore)
            window = None
            try:
                config = UserConfig(project_root=str(temp_project), theme="light")
                window = DashboardWindow(config)
                if "home" not in window.pages:
                    return ["Dashboard smoke did not create the Home page."]
                if not window._show_page("audit"):
                    return ["Dashboard smoke could not show the Audit page."]
                return []
            except Exception as exc:
                return [f"Dashboard smoke failed: {exc}"]
            finally:
                if window is not None:
                    window.close()
                    window.deleteLater()
                    window = None
                _drain_qt_work(app, QThreadPool, QCoreApplication, QEvent)
        finally:
            gc.collect()
            if temp_root is not None:
                _remove_dashboard_smoke_temp(temp_root)
    finally:
        if smoke_env_value is None:
            os.environ.pop("EOAT_COMMAND_CENTER_DASHBOARD_SMOKE", None)
        else:
            os.environ["EOAT_COMMAND_CENTER_DASHBOARD_SMOKE"] = smoke_env_value


def _drain_qt_work(app, qthread_pool, qcore_application, qevent) -> None:
    for _ in range(3):
        app.processEvents()
        qthread_pool.globalInstance().waitForDone(10000)
        app.processEvents()
        qcore_application.sendPostedEvents(None, qevent.Type.DeferredDelete)
        app.processEvents()


def _remove_dashboard_smoke_temp(temp_root: Path) -> None:
    if not temp_root.exists():
        return
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            shutil.rmtree(temp_root, onerror=_rmtree_retry_readonly)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            time.sleep(min(0.2 * (attempt + 1), 1.0))
    print(
        f"WARNING: Dashboard smoke could not remove temp folder after retries: {temp_root}: {last_error}",
        file=sys.stderr,
    )


def _rmtree_retry_readonly(function, path: str, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _demo_runtime_ignore(_directory: str, names: list[str]) -> set[str]:
    runtime_names = {
        "Activity_Logs",
        "Backups",
        "Daily_Status_Reports",
        "Validation_Reports",
        "_backups",
        "cache",
        "logs",
        "open_items",
        "project_data",
    }
    return {name for name in names if name in runtime_names}


def run_safety_checks(repo_root: str | Path = REPO_ROOT) -> list[str]:
    root = Path(repo_root).resolve()
    return [finding.format(root) for finding in audit_repo(root)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local CI smoke checks for registries and repository safety.")
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root to inspect.")
    parser.add_argument("--registry-only", action="store_true", help="Skip repository safety audit.")
    parser.add_argument(
        "--dashboard-smoke",
        action="store_true",
        help="Launch the dashboard offscreen against the sanitized demo project.",
    )
    parser.add_argument(
        "--skip-dashboard-smoke",
        action="store_true",
        help="Do not launch the dashboard, even if --dashboard-smoke was set by a wrapper.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    findings = run_registry_checks(root)
    findings.extend(run_tool_registry_checks())
    findings.extend(run_demo_project_checks())
    if args.dashboard_smoke and not args.skip_dashboard_smoke:
        findings.extend(run_dashboard_smoke(DEFAULT_PROJECT_ROOT))
    if not args.registry_only:
        findings.extend(run_safety_checks(root))
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}")
        return 1
    print("CI smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
