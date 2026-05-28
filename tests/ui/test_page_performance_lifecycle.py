from __future__ import annotations

from app.command_registry import CommandRegistry, CommandSpec
from app.event_bus import AppEvent, EVENT_AUDIT_SAVED
from app.pages.backup_manager import BackupManagerPage
from app.pages.fmea import FmeaPage
from app.pages.handoff import HandoffPage
from app.pages.open_items import OpenItemsPage
from app.pages.performance import PerformancePage
from app.pages.pilot_candidates import PilotCandidatesPage
from app.pages.press_view import PressViewPage
from app.pages.release_readiness import ReleaseReadinessPage
from app.pages.standards_docs import StandardsDocsPage
from app.widgets.command_palette import CommandPalette
from core.backup_manager import BackupSummary
from core.open_items import OpenItem
from core.press_view import PressAuditEntry, PressViewGroup
from core.release_readiness import PASS, ReleaseCheck, ReleaseReadinessSummary
from tests.ui.helpers import wait_for_background_tasks


def test_slow_page_constructors_do_not_call_heavy_core_functions(qapp, fake_config, monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("constructor called heavy refresh function")

    monkeypatch.setattr("app.pages.open_items.list_open_items", fail)
    monkeypatch.setattr("app.pages.press_view.build_press_view_groups", fail)
    monkeypatch.setattr("app.pages.backup_manager.summarize_backups", fail)
    monkeypatch.setattr("app.pages.release_readiness.collect_release_readiness", fail)
    monkeypatch.setattr("app.pages.performance.read_recent_performance_events", fail)
    monkeypatch.setattr("app.pages.fmea.analyze_fmea", fail)
    monkeypatch.setattr("app.pages.pilot_candidates.rank_pilot_candidates", fail)
    monkeypatch.setattr("app.pages.standards_docs.scan_documentation_gaps", fail)
    monkeypatch.setattr("app.pages.standards_docs.analyze_standards_compliance", fail)
    monkeypatch.setattr("app.pages.handoff.build_final_handoff_readiness", fail)

    for page_class in [
        OpenItemsPage,
        PressViewPage,
        BackupManagerPage,
        ReleaseReadinessPage,
        PerformancePage,
        FmeaPage,
        PilotCandidatesPage,
        StandardsDocsPage,
        HandoffPage,
    ]:
        page = page_class(fake_config)
        assert page is not None


def test_open_items_background_refresh_updates_summary_and_debounces(qapp, fake_config, monkeypatch):
    item = OpenItem(id="note:1", source="note", severity="Critical", category="note", title="Async item", message="body", status="Open")
    calls = {"count": 0}

    def list_items(*_args, **_kwargs):
        calls["count"] += 1
        return [item]

    class EmptyAnnotationService:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_tags(self):
            return []

    monkeypatch.setattr("app.pages.open_items.list_open_items", list_items)
    monkeypatch.setattr("app.pages.open_items.AnnotationService", EmptyAnnotationService)

    page = OpenItemsPage(fake_config)
    assert calls["count"] == 0
    page.show()
    wait_for_background_tasks()

    assert page.summary_labels["Total Open"].text() == "1"
    assert page.table.rowCount() == 1

    page._refresh_running = True
    page.refresh(force=True)
    page.on_event(None)
    page._refresh_running = False
    page._refresh_queued = False
    assert calls["count"] == 1


def test_audit_saved_marks_heavy_pages_stale_without_refresh(qapp, fake_config, monkeypatch):
    item = OpenItem(id="note:1", source="note", severity="Warning", category="note", title="Async item", message="body", status="Open")
    group = PressViewGroup(machine="101", display_name="Press/Machine 101")
    calls = {"open_items": 0, "press_view": 0}

    def list_items(*_args, **_kwargs):
        calls["open_items"] += 1
        return [item]

    def build_groups(*_args, **_kwargs):
        calls["press_view"] += 1
        return [group]

    class EmptyAnnotationService:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_tags(self):
            return []

    monkeypatch.setattr("app.pages.open_items.list_open_items", list_items)
    monkeypatch.setattr("app.pages.open_items.AnnotationService", EmptyAnnotationService)
    monkeypatch.setattr("app.pages.press_view.build_press_view_groups", build_groups)

    open_items_page = OpenItemsPage(fake_config)
    press_view_page = PressViewPage(fake_config)
    open_items_page.show()
    press_view_page.show()
    wait_for_background_tasks()
    calls["open_items"] = 0
    calls["press_view"] = 0

    event = AppEvent(EVENT_AUDIT_SAVED, {"audit_id": "AUD-ASYNC-001", "refresh_mode": "invalidate_only"}, source="audit")
    open_items_page.on_event(event)
    press_view_page.on_event(event)
    wait_for_background_tasks()

    assert calls == {"open_items": 0, "press_view": 0}
    assert "marked stale" in open_items_page.status_label.text()
    assert "marked stale" in press_view_page.result_panel.viewer.toPlainText()


def test_press_view_shell_loads_in_background_and_filters_locally(qapp, fake_config, monkeypatch):
    entry = PressAuditEntry(audit_id="AUD-ASYNC-001", machine="101", entry_type="Physical", status="Audited")
    group = PressViewGroup(machine="101", display_name="Press/Machine 101", physical_audits=[entry])
    calls = {"count": 0}

    def build_groups(*_args, **_kwargs):
        calls["count"] += 1
        return [group]

    monkeypatch.setattr("app.pages.press_view.build_press_view_groups", build_groups)
    page = PressViewPage(fake_config)
    assert calls["count"] == 0

    page.show()
    wait_for_background_tasks()
    assert calls["count"] == 1
    assert page.group_table.rowCount() == 1

    page.search_edit.setText("AUD-ASYNC")
    page.status_filter.setCurrentText("Audited")
    qapp.processEvents()
    assert calls["count"] == 1


def test_backup_manager_scans_backups_in_background(qapp, fake_config, monkeypatch):
    summary = BackupSummary(2, 2048, "2026-05-01T08:00:00", "2026-05-02T08:00:00", {"EOAT.xlsx": 2}, (), (), (), ())
    calls = {"count": 0}

    def summarize(*_args, **_kwargs):
        calls["count"] += 1
        return summary

    monkeypatch.setattr("app.pages.backup_manager.summarize_backups", summarize)
    page = BackupManagerPage(fake_config)
    assert calls["count"] == 0

    page.show()
    wait_for_background_tasks()
    assert calls["count"] == 1
    assert page.cards["Backup Count"].value_label.text() == "2"


def test_release_readiness_page_open_skips_full_safety_audit(qapp, fake_config, monkeypatch):
    seen = {}
    summary = ReleaseReadinessSummary((ReleaseCheck("readme", "README", PASS, "ok", "blocker"),), (), (), "main")

    def collect(*_args, **kwargs):
        seen["include_staged_safety_scan"] = kwargs.get("include_staged_safety_scan")
        return summary

    def fail_audit(*_args, **_kwargs):
        raise AssertionError("full repo safety audit should not run on page open")

    monkeypatch.setattr("app.pages.release_readiness.collect_release_readiness", collect)
    monkeypatch.setattr("app.pages.release_readiness.run_repo_safety_audit", fail_audit)

    page = ReleaseReadinessPage(fake_config)
    page.show()
    wait_for_background_tasks()

    assert seen["include_staged_safety_scan"] is False
    assert page.table.rowCount() == 1


def test_command_palette_does_not_search_on_startup(qapp, fake_project, monkeypatch):
    calls = {"count": 0}

    def search(*_args, **_kwargs):
        calls["count"] += 1
        return []

    monkeypatch.setattr("app.widgets.command_palette.search_project", search)
    registry = CommandRegistry([CommandSpec("nav.home", "Open Home", category="Navigation")])

    palette = CommandPalette(registry, str(fake_project))
    palette.show()
    qapp.processEvents()

    assert calls["count"] == 0
