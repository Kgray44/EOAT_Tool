from __future__ import annotations

from app.task_runner import TaskRequest, get_task_manager


def run_tool_background(
    panel,
    task_id: str,
    name: str,
    func,
    on_tool_result=None,
    modifies_files: bool = False,
    workbook_lock: bool = False,
    project_lock: bool | None = None,
    button=None,
    progress_text: str | None = None,
) -> None:
    if panel is not None:
        panel.show_text(progress_text or f"Running: {name}...")

    def _finished(task_result):
        tool_result = task_result.to_tool_result()
        if panel is not None:
            panel.show_result(tool_result)
        if on_tool_result is not None:
            on_tool_result(tool_result)

    get_task_manager().run_task(
        TaskRequest(
            id=task_id,
            name=name,
            category="page",
            callable=func,
            modifies_files=modifies_files,
            requires_project_lock=modifies_files if project_lock is None else project_lock,
            requires_workbook_lock=workbook_lock,
        ),
        on_finished=_finished,
        button=button,
    )
