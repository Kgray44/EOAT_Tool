from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.openers import open_path
from core.search import SearchResult


@dataclass(frozen=True)
class SearchRouteResult:
    success: bool
    action: str
    message: str = ""


def open_search_result(window: Any, result: SearchResult | dict) -> SearchRouteResult:
    data = result.to_dict() if isinstance(result, SearchResult) else dict(result)
    action = str(data.get("action") or "")
    if action == "open_page":
        return _open_page(window, str(data.get("target_id") or data.get("page_key") or ""))
    if action == "open_audit":
        return _open_audit(window, data)
    if action == "open_press":
        return _open_press(window, data)
    if action == "open_note":
        return _open_note(window, data)
    if action == "open_tag":
        return _open_tag(window, data)
    if action == "open_open_item":
        _navigate(window, "open_items")
        _show_message(window, "open_items", f"Opened Open Items from search: {data.get('title') or data.get('target_id') or ''}")
        return SearchRouteResult(True, action, "Opened Open Items.")
    if action == "open_validation":
        _navigate(window, "workbook_health")
        _show_message(window, "workbook_health", f"Opened Workbook Health from search: {data.get('title') or ''}")
        return SearchRouteResult(True, action, "Opened Workbook Health.")
    if action == "open_report":
        return _open_path_route(window, data, action)
    if action == "open_photo":
        route = _open_path_route(window, data, action)
        if route.success:
            return route
        _navigate(window, "photos")
        _show_message(window, "photos", f"Opened Photos from search: {data.get('title') or ''}")
        return SearchRouteResult(True, action, route.message or "Opened Photos page.")
    return SearchRouteResult(False, action or "unknown", f"Unknown search route: {action or 'missing action'}")


def _open_page(window: Any, page_key: str) -> SearchRouteResult:
    if not page_key:
        return SearchRouteResult(False, "open_page", "No page key supplied.")
    page_specs = getattr(window, "page_specs", {})
    if page_specs and page_key not in page_specs:
        return SearchRouteResult(False, "open_page", f"Unknown page: {page_key}")
    _navigate(window, page_key)
    return SearchRouteResult(True, "open_page", f"Opened page: {page_key}")


def _open_audit(window: Any, data: dict[str, Any]) -> SearchRouteResult:
    _navigate(window, "audit")
    page = _page(window, "audit")
    audit_id = str(data.get("audit_id") or "")
    if audit_id and hasattr(page, "load_existing_audit"):
        page.load_existing_audit(audit_id, loaded_message=f"Opened from global search: {audit_id}")
    field = str(data.get("field") or "")
    if field and hasattr(page, "focus_annotation_target"):
        page.focus_annotation_target({"audit_id": audit_id, "field_key": field, "field_label": field, "target_type": "audit_field"})
    return SearchRouteResult(True, "open_audit", f"Opened audit: {audit_id}" if audit_id else "Opened Audit page.")


def _open_press(window: Any, data: dict[str, Any]) -> SearchRouteResult:
    _navigate(window, "press_view")
    page = _page(window, "press_view")
    machine = str(data.get("machine") or "")
    if hasattr(page, "select_machine"):
        page.select_machine(machine)
    return SearchRouteResult(True, "open_press", f"Opened press: {machine}" if machine else "Opened Press View.")


def _open_note(window: Any, data: dict[str, Any]) -> SearchRouteResult:
    _navigate(window, "notes")
    page = _page(window, "notes")
    note_id = str(data.get("target_id") or "")
    if note_id and hasattr(page, "select_note"):
        page.select_note(note_id)
    return SearchRouteResult(True, "open_note", f"Opened note: {note_id}" if note_id else "Opened Notes.")


def _open_tag(window: Any, data: dict[str, Any]) -> SearchRouteResult:
    _navigate(window, "tags")
    page = _page(window, "tags")
    target_id = str(data.get("target_id") or "")
    if hasattr(page, "select_tag_or_assignment"):
        if str(data.get("result_id") or "").startswith("tag_assignment:"):
            page.select_tag_or_assignment(assignment_id=target_id)
        else:
            page.select_tag_or_assignment(tag_id=target_id)
    return SearchRouteResult(True, "open_tag", f"Opened tag target: {target_id}" if target_id else "Opened Tags.")


def _open_path_route(window: Any, data: dict[str, Any], action: str) -> SearchRouteResult:
    path = str(data.get("path") or "")
    if not path:
        return SearchRouteResult(False, action, "No path supplied.")
    result = open_path(path)
    status_bar = window.statusBar() if hasattr(window, "statusBar") else None
    if status_bar is not None and hasattr(status_bar, "showMessage"):
        status_bar.showMessage(result.summary, 9000)
    return SearchRouteResult(bool(result.success), action, result.summary)


def _navigate(window: Any, page_key: str) -> None:
    if hasattr(window, "navigate_to_page"):
        window.navigate_to_page(page_key)
    else:
        window._navigate_to_page(page_key)


def _page(window: Any, page_key: str) -> Any:
    if hasattr(window, "page"):
        return window.page(page_key)
    return getattr(window, "pages", {}).get(page_key)


def _show_message(window: Any, page_key: str, message: str) -> None:
    if hasattr(window, "show_page_message"):
        window.show_page_message(page_key, message)
        return
    status_bar = window.statusBar() if hasattr(window, "statusBar") else None
    if status_bar is not None and hasattr(status_bar, "showMessage"):
        status_bar.showMessage(message, 9000)


__all__ = ["SearchRouteResult", "open_search_result"]
