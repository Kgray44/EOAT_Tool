from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .paths import resolve_project_paths
from .safe_files import ensure_directory


def performance_log_path(project_root: str | Path) -> Path:
    return resolve_project_paths(project_root).logs / "performance.log"


def log_performance(project_root: str | Path, operation: str, elapsed_seconds: float, details: str = "") -> str | None:
    try:
        if not Path(project_root).exists():
            return f"Performance logging skipped because project root does not exist: {project_root}"
        path = performance_log_path(project_root)
        ensure_directory(path.parent)
        suffix = f" {details.strip()}" if details.strip() else ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] [PERF] {operation}: {elapsed_seconds:.2f}s{suffix}\n")
    except Exception as exc:
        return f"Performance logging failed: {exc}"
    return None


@contextmanager
def timed_operation(project_root: str | Path, operation: str, details: str = "") -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        log_performance(project_root, operation, time.perf_counter() - started, details)
