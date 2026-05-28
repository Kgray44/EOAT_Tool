from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.task_runner import TaskRequest, TaskResult, get_task_manager
from core.performance import log_performance


def log_page_performance(
    project_root,
    page_key: str,
    phase: str,
    duration_seconds: float,
    *,
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> None:
    log_performance(
        project_root,
        f"page.{page_key}.{phase}",
        duration_seconds,
        details=details or {},
        success=success,
        source="page_lifecycle",
        page_tool=page_key,
    )


class AsyncRefreshMixin:
    def _init_async_refresh(self, page_key: str) -> None:
        self._page_key = page_key
        self._refresh_running = False
        self._refresh_queued = False
        self._last_refresh_request_at = 0.0

    def _begin_background_refresh(
        self,
        *,
        task_id: str,
        name: str,
        load: Callable[[], Any],
        apply_result: Callable[[Any, float], None],
        button=None,
        force: bool = False,
        loading_text: str = "Loading...",
        debounce_seconds: float = 0.25,
    ) -> bool:
        now = time.monotonic()
        if self._refresh_running:
            if force:
                self._refresh_queued = True
            return False
        if not force and now - self._last_refresh_request_at < debounce_seconds:
            return False

        self._last_refresh_request_at = now
        self._refresh_running = True
        if loading_text:
            self._set_page_status(loading_text)
        started = time.perf_counter()

        def _finished(task_result: TaskResult) -> None:
            duration = task_result.duration_seconds or time.perf_counter() - started
            self._refresh_running = False
            if task_result.ok:
                apply_result(task_result.result_data, duration)
            else:
                self._set_page_status(f"{name} failed: {task_result.error or task_result.message}")
                config = getattr(self, "config", None)
                project_root = getattr(config, "project_root", None)
                if project_root:
                    log_page_performance(
                        project_root,
                        self._page_key,
                        "data_load",
                        duration,
                        success=False,
                        details={"message": task_result.message, "error": task_result.error},
                    )
            if self._refresh_queued:
                self._refresh_queued = False
                self._begin_background_refresh(
                    task_id=task_id,
                    name=name,
                    load=load,
                    apply_result=apply_result,
                    button=button,
                    force=True,
                    loading_text=loading_text,
                    debounce_seconds=debounce_seconds,
                )

        accepted = get_task_manager().run_task(
            TaskRequest(
                id=task_id,
                name=name,
                category="page_refresh",
                callable=load,
            ),
            on_finished=_finished,
            button=button,
        )
        if not accepted:
            self._refresh_running = False
        return accepted

    def _set_page_status(self, text: str) -> None:
        status_label = getattr(self, "status_label", None)
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText(text)
            return
        result_panel = getattr(self, "result_panel", None)
        if result_panel is not None and hasattr(result_panel, "show_text"):
            result_panel.show_text(text)
