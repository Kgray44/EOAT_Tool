from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StatePaths:
    root: Path
    mysql_base: Path
    mysql_data: Path
    mysql_executable: Path
    mysql_client: Path
    mysql_admin: Path
    mysql_log: Path
    mysql_pid: Path
    database_environment: Path
    api_pid: Path
    api_metadata: Path
    api_log: Path

    @classmethod
    def local(cls) -> StatePaths:
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        root = local / "EOAT Atlas Development"
        base = root / "mysql-8.4.9-winx64"
        return cls(
            root=root,
            mysql_base=base,
            mysql_data=root / "mysql-data",
            mysql_executable=base / "bin" / "mysqld.exe",
            mysql_client=base / "bin" / "mysql.exe",
            mysql_admin=base / "bin" / "mysqladmin.exe",
            mysql_log=root / "mysql-error.log",
            mysql_pid=root / "mysql.pid",
            database_environment=root / "database.env",
            api_pid=root / "eoat_api.pid",
            api_metadata=root / "eoat_api_metadata.json",
            api_log=root / "eoat_api.log",
        )


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    executable_path: str
    command_line: str


def _powershell_json(command: str):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def listener_pid(port: int) -> int | None:
    payload = _powershell_json(
        "$x=Get-NetTCPConnection -State Listen -LocalPort "
        f"{int(port)} -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if($x){$x.OwningProcess | ConvertTo-Json -Compress}"
    )
    try:
        return int(payload) if payload is not None else None
    except (TypeError, ValueError):
        return None


def process_info(pid: int) -> ProcessInfo | None:
    payload = _powershell_json(
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" -ErrorAction SilentlyContinue; "
        "if($p){$p | Select-Object ProcessId,Name,ExecutablePath,CommandLine | ConvertTo-Json -Compress}"
    )
    if not isinstance(payload, dict):
        return None
    return ProcessInfo(
        pid=int(payload.get("ProcessId") or pid),
        name=str(payload.get("Name") or ""),
        executable_path=str(payload.get("ExecutablePath") or ""),
        command_line=str(payload.get("CommandLine") or ""),
    )


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_environment_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        if key.startswith("EOAT_"):
            values[key] = value.strip()
    return values
