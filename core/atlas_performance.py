from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .performance import log_performance


@dataclass
class AtlasDiagnostics:
    timings_ms: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def record_timing(self, name: str, seconds: float) -> None:
        self.timings_ms[name] = round(seconds * 1000, 2)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def to_metrics(self) -> dict[str, Any]:
        return {
            **{f"{key}_ms": value for key, value in self.timings_ms.items()},
            **self.counters,
            "diagnostic_warnings": len(self.warnings),
        }


@contextmanager
def timed_step(diagnostics: AtlasDiagnostics, name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        diagnostics.record_timing(name, time.perf_counter() - started)


def time_call(
    diagnostics: AtlasDiagnostics,
    name: str,
    callback: Callable[..., Any],
    *args: Any,
    project_root: str = "",
    **kwargs: Any,
) -> Any:
    started = time.perf_counter()
    try:
        return callback(*args, **kwargs)
    finally:
        elapsed = time.perf_counter() - started
        diagnostics.record_timing(name, elapsed)
        if project_root:
            log_performance(
                project_root,
                f"atlas.{name}",
                elapsed,
                source="atlas",
                page_tool="atlas_backend",
            )


__all__ = ["AtlasDiagnostics", "time_call", "timed_step"]
