from __future__ import annotations

import json
import logging
import os
import platform
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from core.config import UserConfig, load_config
from core.constants import DEFAULT_PROJECT_ROOT
from core.globalization.config import load_or_create_global_config
from core.versioning import configure_release_logging, get_version_info

from .assets import ATLAS_LOGO_PATH
from .settings import AtlasSettings, load_atlas_settings
from .styles import atlas_stylesheet


def main() -> int:
    configure_release_logging()
    backend = os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold()
    if backend not in {"mysql_api", "legacy"}:
        raise SystemExit(f"Invalid EOAT_ATLAS_DATA_BACKEND: {backend}")
    _extract_ui_mode(sys.argv, default="minimalist")
    smoke_receipt = _extract_smoke_receipt(sys.argv)
    smoke_test_arg = "--smoke-test" in sys.argv
    if smoke_test_arg:
        sys.argv.remove("--smoke-test")
    smoke_test = smoke_test_arg or os.environ.get("EOAT_ATLAS_SMOKE_TEST") == "1"
    if smoke_test and backend == "legacy":
        _initialize_smoke_runtime()
    if smoke_test:
        watchdog = threading.Timer(15.0, lambda: os._exit(124))
        watchdog.daemon = True
        watchdog.start()
    app = QApplication(sys.argv)
    app.setApplicationName("EOAT Atlas")
    app.setApplicationDisplayName(f"EOAT Atlas {get_version_info().application_version} [{backend}]")
    app.setFont(QFont("Segoe UI", 10))
    if ATLAS_LOGO_PATH.exists():
        app.setWindowIcon(QIcon(str(ATLAS_LOGO_PATH)))
    settings = AtlasSettings() if smoke_test else load_atlas_settings()
    app.setStyleSheet(atlas_stylesheet(settings.effective_theme, settings.color_scheme))
    config = UserConfig(project_root=str(DEFAULT_PROJECT_ROOT)) if smoke_test else _load_globalized_user_config()
    from .minimalist import MinimalistAtlasWindow
    from .minimalist.settings_store import load_settings as load_minimalist_settings
    from .minimalist.settings_store import save_settings as save_minimalist_settings

    minimalist_settings = load_minimalist_settings()
    if not smoke_test:
        from datetime import datetime

        minimalist_settings.setdefault("diagnostics", {})["last_app_launch"] = datetime.now().isoformat(timespec="seconds")
        save_minimalist_settings(minimalist_settings)
    refresh_on_launch = bool(minimalist_settings.get("data_loading", {}).get("refresh_on_launch", True))
    window = MinimalistAtlasWindow(
        config,
        auto_refresh=(not smoke_test and settings.auto_refresh_on_startup and refresh_on_launch),
        settings=settings,
    )
    window.show()
    if not smoke_test and backend == "mysql_api":
        _register_application_instance_in_background()
    if (not settings.auto_refresh_on_startup or not refresh_on_launch) and not smoke_test:
        cache_label = "disposable API cache" if backend == "mysql_api" else "existing local cache"
        window.show_status(f"Auto-refresh is off. EOAT Atlas opened from the {cache_label}.")
    if smoke_test:
        QTimer.singleShot(700, window.close)
        QTimer.singleShot(900, app.quit)
        QTimer.singleShot(6000, lambda: os._exit(124))
    exit_code = app.exec()
    if smoke_test and exit_code == 0 and smoke_receipt is not None:
        smoke_receipt.parent.mkdir(parents=True, exist_ok=True)
        smoke_receipt.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "application_version": get_version_info().application_version,
                    "release_id": get_version_info().release_id,
                    "build_id": get_version_info().build_id,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return exit_code


def _extract_ui_mode(argv: list[str], *, default: str = "minimalist") -> str:
    index = 0
    while index < len(argv):
        arg = argv[index]
        lowered = arg.casefold()
        if lowered in {"--ui", "-ui"} and index + 1 < len(argv):
            del argv[index : index + 2]
            continue
        if lowered.startswith("--ui=") or lowered.startswith("-ui="):
            del argv[index]
            continue
        index += 1
    return "minimalist"


def _extract_smoke_receipt(argv: list[str]) -> Path | None:
    """Remove the packaged-smoke receipt argument before Qt sees it."""

    for index, arg in enumerate(argv):
        if arg == "--smoke-receipt" and index + 1 < len(argv):
            value = Path(argv[index + 1])
            del argv[index : index + 2]
            return value
        if arg.startswith("--smoke-receipt="):
            value = Path(arg.split("=", 1)[1])
            del argv[index]
            return value
    return None


def _load_globalized_user_config() -> UserConfig:
    config = load_config()
    try:
        global_config = load_or_create_global_config()
    except Exception:
        return config
    if str(global_config.network_root or "").strip():
        config.project_root = str(global_config.network_root)
    return config


def _initialize_smoke_runtime() -> None:
    try:
        from core.globalization.app_metadata import load_app_metadata
        from core.globalization.config import load_or_create_global_config
        from core.globalization.install_identity import load_or_create_install_identity
        from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths
        from core.globalization.sqlite_store import connect_cache_db

        runtime = ensure_runtime_layout(get_runtime_paths())
        load_app_metadata()
        identity = load_or_create_install_identity(runtime)
        config = load_or_create_global_config(runtime)
        with connect_cache_db(runtime.db_path):
            pass
        if os.environ.get("EOAT_ATLAS_SMOKE_RUNTIME_PROBE") == "1":
            from core.globalization.events import EventOutbox
            from core.globalization.pending_updates import PendingUpdateStore

            update = PendingUpdateStore(runtime, config).create_update(
                entity_type="eoat",
                entity_id="SMOKE-PROBE",
                field_name="status",
                expected_original_value="",
                proposed_value="Smoke Probe",
                source_view="smoke",
                source_action="smoke_runtime_probe",
            )
            EventOutbox(runtime, config).create_event(
                event_type="smoke_runtime_probe",
                action="smoke_runtime_probe",
                entity_type="eoat",
                entity_id="SMOKE-PROBE",
                payload={
                    "pending_update_ids": [update["pending_update_id"]],
                    "field_changes": [{"field_name": "status", "expected_original_value": "", "proposed_value": "Smoke Probe"}],
                    "validation_result": {"status": "valid"},
                    "conflict_result": {"status": "none"},
                    "write_result": {"status": "not_written"},
                    "source_view": "smoke",
                    "source_action": "smoke_runtime_probe",
                    "install_id": identity.install_id,
                },
            )
    except Exception:
        return


def _register_application_instance_in_background() -> None:
    """Register this stable installation and its release without delaying the UI."""

    def register() -> None:
        gateway = None
        try:
            from core.data_gateway.configuration import GatewayConfiguration
            from core.data_gateway.gateway import AtlasDataGateway
            from core.globalization.install_identity import load_or_create_install_identity

            identity = load_or_create_install_identity()
            os.environ.setdefault("EOAT_ATLAS_INSTANCE_ID", identity.app_instance_id)
            gateway = AtlasDataGateway(GatewayConfiguration.from_environment())
            gateway.register_application_instance(
                {
                    "instance_uuid": identity.app_instance_id,
                    "computer_name": identity.machine_name,
                    "operating_system": platform.platform(),
                }
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "EOAT Atlas application-release registration failed; startup will continue.",
                exc_info=True,
            )
        finally:
            if gateway is not None:
                gateway.close()

    threading.Thread(
        target=register,
        name="eoat-release-registration",
        daemon=True,
    ).start()


if __name__ == "__main__":
    raise SystemExit(main())
