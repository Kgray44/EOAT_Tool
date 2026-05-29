from __future__ import annotations

from dataclasses import dataclass

from app.search_routes import open_search_result
from core.search import SearchResult


class _AuditPage:
    def __init__(self):
        self.loaded: list[str] = []

    def load_existing_audit(self, audit_id: str, loaded_message: str = "") -> None:
        self.loaded.append(audit_id)


@dataclass
class _StatusBar:
    messages: list[str]

    def showMessage(self, message: str, _timeout: int = 0) -> None:
        self.messages.append(message)


class _Window:
    def __init__(self):
        self.page_specs = {"audit": object(), "press_view": object(), "open_items": object()}
        self.pages = {"audit": _AuditPage()}
        self.navigated: list[str] = []
        self.messages: list[tuple[str, str]] = []
        self.status = _StatusBar([])

    def navigate_to_page(self, page_key: str) -> None:
        self.navigated.append(page_key)

    def page(self, page_key: str):
        return self.pages.get(page_key)

    def show_page_message(self, page_key: str, message: str) -> None:
        self.messages.append((page_key, message))

    def statusBar(self):
        return self.status


def test_search_route_opens_audit_result():
    window = _Window()
    result = SearchResult("audit:EOAT-1", "audit", "Audit EOAT-1", audit_id="EOAT-1", action="open_audit")

    route = open_search_result(window, result)

    assert route.success is True
    assert window.navigated == ["audit"]
    assert window.pages["audit"].loaded == ["EOAT-1"]


def test_search_route_unknown_action_fails_gracefully():
    window = _Window()

    route = open_search_result(window, {"action": "launch_missing_thing"})

    assert route.success is False
    assert "Unknown search route" in route.message
    assert window.navigated == []
