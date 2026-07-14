from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import LAUNCHER_NAME, LAUNCHER_VERSION


class DiagnosticsWriter:
    def __init__(self, log_dir: str | Path, *, verbose: bool = False):
        self.log_dir = Path(log_dir)
        self.verbose = verbose
        self.log_path = self.log_dir / "launcher.log"
        self.diagnostics_dir = self.log_dir / "Diagnostics"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: str, **payload: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "launcher": LAUNCHER_NAME,
            "launcherVersion": LAUNCHER_VERSION,
            "event": event,
            **_json_safe(payload),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")

    def write_report(self, title: str, sections: dict[str, Any]) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.diagnostics_dir / f"eoat_atlas_launcher_diagnostics_{stamp}.txt"
        lines = [
            title,
            "=" * len(title),
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            f"Launcher version: {LAUNCHER_VERSION}",
            "",
        ]
        for heading, value in sections.items():
            lines.append(str(heading))
            lines.append("-" * len(str(heading)))
            if isinstance(value, str):
                lines.append(value)
            else:
                lines.append(json.dumps(_json_safe(value), indent=2, sort_keys=True))
            lines.append("")
        target.write_text("\n".join(lines), encoding="utf-8")
        self.log_event("diagnostics_report_written", path=str(target))
        return target

    def open_logs(self) -> bool:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(self.log_dir))  # type: ignore[attr-defined]
            elif sys_platform_is_macos():
                subprocess.Popen(["open", str(self.log_dir)], shell=False)
            else:
                subprocess.Popen(["xdg-open", str(self.log_dir)], shell=False)
        except OSError as exc:
            self.log_event("open_logs_failed", error=str(exc), path=str(self.log_dir))
            return False
        self.log_event("open_logs_requested", path=str(self.log_dir))
        return True


def sys_platform_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
