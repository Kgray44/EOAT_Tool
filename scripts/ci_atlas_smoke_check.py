from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TIMEOUT_EXIT_CODE = 124


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic offscreen smoke test for Minimalist EOAT Atlas.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--log", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = args.root.resolve()
    from core.versioning import get_release_info

    metadata = get_release_info(root).to_dict()
    state = {
        "last_completed_step": "release_metadata_loaded",
        "active_backend": os.getenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api").strip().casefold(),
        "release_id": metadata.get("release_id", ""),
        "build_id": metadata.get("build_id", ""),
        "current_page": "not_created",
        "timeout_seconds": args.timeout,
    }

    def emit(message: str) -> None:
        print(message, flush=True)
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            with args.log.open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")

    def timeout() -> None:
        emit("TIMEOUT " + json.dumps(state, sort_keys=True))
        os._exit(TIMEOUT_EXIT_CODE)

    watchdog = threading.Timer(args.timeout, timeout)
    watchdog.daemon = True
    watchdog.start()
    window = None
    try:
        if state["active_backend"] != "mysql_api":
            raise RuntimeError("Atlas smoke requires mysql_api unless a separate legacy-mode test is explicitly used.")
        version_payload = json.loads((root / "app" / "atlas" / "version.json").read_text(encoding="utf-8"))
        if version_payload.get("version") != metadata.get("application_version"):
            raise RuntimeError("app/atlas/version.json does not match canonical application version.")
        state["last_completed_step"] = "version_sources_validated"

        with tempfile.TemporaryDirectory(prefix="eoat_atlas_ci_smoke_") as temporary:
            os.environ.update(
                {
                    "QT_QPA_PLATFORM": "offscreen",
                    "EOAT_ATLAS_DATA_BACKEND": "mysql_api",
                    "EOAT_ATLAS_LOCALAPPDATA": temporary,
                    "EOAT_ATLAS_API_CACHE": str(Path(temporary) / "api-cache.db"),
                    "EOAT_ATLAS_WRITES_ENABLED": "false",
                }
            )
            from PySide6.QtWidgets import QApplication

            from app.atlas.minimalist import MinimalistAtlasWindow
            from app.atlas.settings import AtlasSettings
            from core.config import UserConfig
            from core.data_gateway.cache_repository import CacheRepository

            app = QApplication.instance() or QApplication([])
            cache = CacheRepository(os.environ["EOAT_ATLAS_API_CACHE"])
            cache.initialize()
            if not cache.path.exists() or cache.metadata().get("cache_schema_version") == "":
                raise RuntimeError("Disposable cache path was not initialized.")
            state["last_completed_step"] = "disposable_cache_created"
            window = MinimalistAtlasWindow(
                UserConfig(project_root=temporary), auto_refresh=False, settings=AtlasSettings()
            )
            state["last_completed_step"] = "minimalist_window_constructed"
            for name in ("home_page", "library_page", "fit_check_page"):
                if getattr(window, name, None) is None:
                    raise RuntimeError(f"Required page was not constructed: {name}")
                state["last_completed_step"] = f"{name}_validated"
            if not window.show_page("settings"):
                raise RuntimeError("Settings page could not be constructed.")
            state["current_page"] = window.current_page_key
            if window.settings_page.settings_content.admin_active:
                raise RuntimeError("Settings unexpectedly began unlocked.")
            state["last_completed_step"] = "settings_locked_validated"
            window.close()
            app.processEvents()
            state["last_completed_step"] = "window_closed_normally"
        emit("PASS " + json.dumps(state, sort_keys=True))
        return 0
    except Exception as exc:
        state["error"] = f"{type(exc).__name__}: {exc}"
        emit("FAIL " + json.dumps(state, sort_keys=True))
        return 1
    finally:
        watchdog.cancel()
        if window is not None:
            window.close()


if __name__ == "__main__":
    raise SystemExit(main())
