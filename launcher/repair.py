from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigLoader, LauncherConfig, backup_existing_file, write_install_metadata
from .core import PathResolver
from .diagnostics import DiagnosticsWriter


@dataclass(frozen=True)
class RepairResult:
    ok: bool
    configPath: Path
    messages: list[str] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "configPath": str(self.configPath),
            "messages": self.messages,
            "backups": [str(path) for path in self.backups],
        }


class RepairService:
    def __init__(self, loader: ConfigLoader, diagnostics: DiagnosticsWriter):
        self.loader = loader
        self.diagnostics = diagnostics

    def repair(self, *, app_path: str | Path | None = None) -> RepairResult:
        messages: list[str] = []
        backups: list[Path] = []
        self.loader.path.parent.mkdir(parents=True, exist_ok=True)
        load_result = self.loader.load(create_if_missing=False)
        config = load_result.config
        if load_result.corrupt and self.loader.path.exists():
            backups.append(backup_existing_file(self.loader.path))
            messages.append("Backed up corrupt launcher config.")
            config = LauncherConfig()
        elif not self.loader.path.exists():
            messages.append("Created missing launcher config folder.")
        if app_path:
            config = LauncherConfig.from_dict({**config.to_dict(), "appInstallPath": str(Path(app_path).expanduser())})
            write_install_metadata(self.loader.path.parent, app_path)
            messages.append("Updated launcher config to point at the supplied app path.")
        self.loader.write(config, backup=bool(self.loader.path.exists() and not load_result.corrupt))
        messages.append("Launcher config was written from safe defaults.")
        resolved = PathResolver(config, self.loader).resolve()
        if resolved.found:
            messages.append(f"Verified EOAT Atlas target: {resolved.executable_path}")
        else:
            messages.append("EOAT Atlas executable was not found. Set appInstallPath to the installed app folder.")
        ok = self.loader.path.exists() and (resolved.found or not app_path)
        result = RepairResult(ok=ok, configPath=self.loader.path, messages=messages, backups=backups)
        self.diagnostics.log_event("repair_completed", **result.to_dict())
        return result
