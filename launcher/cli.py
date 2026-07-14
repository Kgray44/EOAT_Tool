from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import LAUNCHER_NAME, LAUNCHER_VERSION
from .config import ConfigLoader, default_config_path, default_log_dir
from .core import (
    AppLauncher,
    PathResolver,
    ResourceChecker,
    SingleInstanceGuard,
    UpdateChecker,
    VersionReader,
    is_app_process_running,
)
from .diagnostics import DiagnosticsWriter
from .repair import RepairService
from .ui import Notifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely start EOAT Atlas.")
    parser.add_argument("--version", action="version", version=f"{LAUNCHER_NAME} {LAUNCHER_VERSION}")
    parser.add_argument("--diagnostics", action="store_true", help="Run checks and write a diagnostic report.")
    parser.add_argument("--open-logs", action="store_true", help="Open the launcher log folder.")
    parser.add_argument("--repair", action="store_true", help="Repair launcher config and user folders.")
    parser.add_argument("--check-only", action="store_true", help="Run startup checks without opening EOAT Atlas.")
    parser.add_argument("--app-path", default="", help="Override the EOAT Atlas install folder or executable path.")
    parser.add_argument("--no-update-check", action="store_true", help="Skip configured update manifest checks.")
    parser.add_argument("--verbose", action="store_true", help="Write extra diagnostics to the launcher log.")
    parser.add_argument("--config", default="", help="Use a specific launcher config file.")
    parser.add_argument("--no-ui", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    diagnostics = DiagnosticsWriter(default_log_dir(), verbose=bool(args.verbose))
    notifier = Notifier(no_ui=bool(args.no_ui or args.diagnostics or args.check_only))
    loader = ConfigLoader(config_path)

    if args.open_logs:
        ok = diagnostics.open_logs()
        if not ok:
            notifier.error("Unable to open launcher logs", f"Log folder: {diagnostics.log_dir}")
        return 0 if ok else 1

    if args.repair:
        result = RepairService(loader, diagnostics).repair(app_path=args.app_path or None)
        message = "\n".join(result.messages + [f"Config: {result.configPath}", f"Logs: {diagnostics.log_dir}"])
        if result.ok:
            notifier.info("EOAT Atlas Launcher repair complete", message)
            return 0
        notifier.warning("EOAT Atlas Launcher repair needs attention", message)
        return 1

    return _run_launch_flow(args, loader, diagnostics, notifier)


def _run_launch_flow(
    args: argparse.Namespace,
    loader: ConfigLoader,
    diagnostics: DiagnosticsWriter,
    notifier: Notifier,
) -> int:
    load_result = loader.load(create_if_missing=True)
    config = load_result.config
    diagnostics.log_event(
        "launch_attempt_started",
        configPath=str(load_result.path),
        configCreated=load_result.created,
        configCorrupt=load_result.corrupt,
        configError=load_result.error,
        logLevel=config.logLevel,
    )

    resolver = PathResolver(config, loader)
    resolved = resolver.resolve(override_app_path=args.app_path or None)
    version = VersionReader().read(resolved.install_path) if resolved.found else None
    resources = ResourceChecker(config).check()
    update_result = (
        UpdateChecker(config).check(version, install_path=resolved.install_path)
        if not args.no_update_check
        else None
    )

    diagnostics.log_event(
        "preflight_completed",
        installMode=resolved.install_mode,
        resolvedApp=resolved.to_dict(),
        appVersion=version.to_dict() if version else None,
        resources=resources.to_dict(),
        updateCheck=update_result.to_dict() if update_result else {"status": "skipped"},
    )

    if args.diagnostics:
        report = diagnostics.write_report(
            "EOAT Atlas Launcher Diagnostics",
            _diagnostic_sections(load_result, resolved, version, resources, update_result),
        )
        notifier.info("EOAT Atlas diagnostics written", f"Diagnostics file: {report}")
        return 0 if resolved.found and not resources.blocking else 1

    if args.check_only:
        if resolved.found and not resources.blocking:
            notifier.info("EOAT Atlas Launcher check complete", "EOAT Atlas is ready to launch.")
            return 0
        notifier.error("EOAT Atlas Launcher check failed", _failure_summary(resolved, resources))
        return 1

    if load_result.corrupt:
        diagnostics.log_event("config_corrupt_using_defaults", error=load_result.error)
    if not resolved.found:
        return _show_error_with_retry(
            args,
            loader,
            diagnostics,
            notifier,
            "Unable to start EOAT Atlas",
            (
                "EOAT Atlas could not be found.\n\n"
                "Ask IT or engineering to repair the launcher configuration, or run the launcher with "
                "--repair --app-path pointing to the installed EOAT Atlas folder.\n\n"
                f"Diagnostics: {diagnostics.log_path}"
            ),
        )
    if resources.blocking:
        names = "\n".join(f"- {item.label}: {item.path}" for item in resources.blocking)
        notifier.error(
            "Unable to start EOAT Atlas",
            "A required shared resource could not be reached:\n\n"
            f"{names}\n\nCheck the network connection or contact engineering/IT.",
        )
        diagnostics.log_event("launch_blocked_by_resources", resources=resources.to_dict())
        return 1
    if resources.unavailable:
        names = "\n".join(f"- {item.label}: {item.path}" for item in resources.unavailable)
        notifier.warning(
            "EOAT Atlas shared resources unavailable",
            "EOAT Atlas can open, but one or more shared resources could not be reached.\n\n"
            f"{names}\n\nSome photos, tracker data, or updates may be unavailable until the connection is restored.",
        )
    if update_result and update_result.update_available:
        notifier.warning(
            "EOAT Atlas update available",
            (
                f"Installed version: {update_result.installedVersion or 'unknown'}\n"
                f"Available version: {update_result.availableVersion}\n\n"
                "EOAT Atlas will open now. Ask IT or engineering to update this PC when practical."
            ),
        )

    guard = None
    if config.singleInstance.enabled:
        guard = SingleInstanceGuard(config.singleInstance.lockName, lock_dir=loader.path.parent)
        if not guard.acquire():
            notifier.info(
                "EOAT Atlas is already starting",
                "EOAT Atlas is already being opened. Use the existing window instead of starting another copy.",
            )
            diagnostics.log_event("launch_skipped_launcher_lock_held")
            return 0
        if is_app_process_running(config.singleInstance.appProcessNames):
            guard.release()
            notifier.info(
                "EOAT Atlas is already open",
                "EOAT Atlas is already running. Use the existing window instead of opening another copy.",
            )
            diagnostics.log_event("launch_skipped_app_already_running")
            return 0

    launch_result = AppLauncher().start(resolved, config)
    if guard is not None:
        guard.release()
    diagnostics.log_event(
        "process_start_completed",
        processPath=str(resolved.executable_path),
        arguments=config.launchArguments,
        result=launch_result.to_dict(),
    )
    if not launch_result.started:
        return _show_error_with_retry(
            args,
            loader,
            diagnostics,
            notifier,
            "Unable to start EOAT Atlas",
            (
                "EOAT Atlas was found, but Windows could not start it.\n\n"
                "Close any partial Atlas windows, then try again. If this keeps happening, send the launcher "
                f"logs to engineering/IT.\n\nDiagnostics: {diagnostics.log_path}"
            ),
        )
    return 0


def _show_error_with_retry(
    args: argparse.Namespace,
    loader: ConfigLoader,
    diagnostics: DiagnosticsWriter,
    notifier: Notifier,
    title: str,
    message: str,
) -> int:
    diagnostics.log_event("user_facing_error", title=title, message=message)
    if notifier.ask_retry(title, message):
        return _run_launch_flow(args, loader, diagnostics, notifier)
    notifier.error(title, message)
    return 1


def _diagnostic_sections(load_result: Any, resolved: Any, version: Any, resources: Any, update_result: Any) -> dict[str, Any]:
    return {
        "Config": {
            "path": str(load_result.path),
            "created": load_result.created,
            "corrupt": load_result.corrupt,
            "error": load_result.error,
        },
        "Resolved App": resolved.to_dict(),
        "Version": version.to_dict() if version else "No installed version metadata found.",
        "Resources": resources.to_dict(),
        "Update Check": update_result.to_dict() if update_result else {"status": "skipped"},
    }


def _failure_summary(resolved: Any, resources: Any) -> str:
    if not resolved.found:
        return resolved.message
    if resources.blocking:
        return "Required resources are unavailable: " + ", ".join(item.label for item in resources.blocking)
    return "Unknown launcher check failure."


if __name__ == "__main__":
    raise SystemExit(main())
