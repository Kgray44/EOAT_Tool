from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest

from app.atlas import command_palette as command_palette_module
from app.atlas.minimalist.data import load_recent_searches, recent_entries, record_recent_search
from app.atlas.minimalist.library import PDFPreviewOverlay
from app.atlas.minimalist.overlays import SearchResultRow, SearchSuggestionRow
from app.atlas.minimalist.window import MinimalistAtlasWindow
from core.atlas_models import AtlasDataBundle, AtlasIndexes, EOATRecord, MachineRecord, ToolRecord
from core.atlas_record_details import RecordDetailData
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.config import UserConfig
from core.reporting.pdf_preview_session import PdfPreviewSession


def test_empty_palette_library_suggestion_navigates_without_recent_search(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_palette_bundle(tmp_path))
    window.show()
    window.show_page("home")
    qapp.processEvents()

    window._context_search_shortcut()
    qapp.processEvents()
    overlay = window.home_page.shell.search_overlay
    library_rows = [row for row in overlay.findChildren(SearchSuggestionRow) if row.text() == "Library"]

    assert library_rows

    QTest.mouseClick(library_rows[0], Qt.MouseButton.LeftButton)
    qapp.processEvents()
    qapp.processEvents()

    assert window.current_page_key == "library"
    assert overlay.search_box.input.text() == ""
    assert load_recent_searches() == []
    _cleanup_widget(qapp, window)


def test_refresh_command_does_not_pollute_recent_searches(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_palette_bundle(tmp_path))
    window.show()
    qapp.processEvents()
    refreshed: list[bool] = []
    window.refresh_data = lambda *, force=False: refreshed.append(force)

    window._context_search_shortcut()
    qapp.processEvents()
    overlay = window.home_page.shell.search_overlay
    overlay.set_search_text("refresh")
    qapp.processEvents()
    overlay.run_first_result()
    qapp.processEvents()

    assert refreshed == [False]
    assert load_recent_searches() == []
    assert overlay.search_box.input.text() == ""

    window._context_search_shortcut()
    qapp.processEvents()
    assert overlay.search_box.input.text() == ""
    _cleanup_widget(qapp, window)


def test_palette_records_successful_entity_searches_only(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_palette_bundle(tmp_path))
    window.show()
    qapp.processEvents()
    opened: list[tuple[str, str]] = []
    window.open_eoat = lambda eoat_id, **_kwargs: opened.append(("eoat", eoat_id))
    window.open_machine = lambda machine, **_kwargs: opened.append(("machine", machine))
    window.open_tool = lambda tool, **_kwargs: opened.append(("tool", tool))

    window._context_search_shortcut()
    qapp.processEvents()
    overlay = window.home_page.shell.search_overlay
    overlay.set_search_text("6201510010")
    qapp.processEvents()
    overlay.run_first_result()
    qapp.processEvents()

    searches = load_recent_searches()
    assert opened == [("tool", "6201510010")]
    assert searches[0]["query"] == "6201510010"
    assert searches[0]["kind"] == "Tool / Mold"

    window._context_search_shortcut()
    qapp.processEvents()
    overlay.set_search_text("not-a-real-atlas-record")
    qapp.processEvents()
    overlay.run_first_result()
    qapp.processEvents()

    assert [item["query"] for item in load_recent_searches()] == ["6201510010"]
    _cleanup_widget(qapp, window)


def test_shared_search_handler_navigates_exact_entities(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window._data_loaded(_palette_bundle(tmp_path))
    opened: list[tuple[str, str, str]] = []
    window.open_eoat = lambda eoat_id, **kwargs: opened.append(("eoat", eoat_id, kwargs.get("source", "")))
    window.open_machine = lambda machine, **kwargs: opened.append(("machine", machine, kwargs.get("source", "")))
    window.open_tool = lambda tool, **kwargs: opened.append(("tool", tool, kwargs.get("source", "")))

    window.run_search_query("6201510010", source="home-search")
    window.run_search_query("P4-EOAT-0052", source="global-search")
    window.run_search_query("machine52", source="recent-search")

    assert opened == [
        ("tool", "6201510010", "home-search"),
        ("eoat", "P4-EOAT-0052", "global-search"),
        ("machine", "52", "recent-search"),
    ]
    _cleanup_widget(qapp, window)


def test_recent_search_entry_uses_shared_navigation(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window._data_loaded(_palette_bundle(tmp_path))
    opened: list[tuple[str, str]] = []
    window.open_tool = lambda tool, **_kwargs: opened.append(("tool", tool))
    window.run_search_query = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recent entity click reran search"))
    record_recent_search("6201510010", kind="Tool / Mold", bundle=window.bundle)

    entries = recent_entries(window, window.bundle, limit=1)
    entries[0].opener()

    assert opened == [("tool", "6201510010")]
    _cleanup_widget(qapp, window)


def test_fit_check_profile_navigation_keeps_fit_check_back_context(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_palette_bundle(tmp_path))

    window.open_tool("6201510010", source="fit_check")
    qapp.processEvents()

    assert window.current_page_key == "library"
    assert window.library_page.library_content.back_button_label() == "Back to Fit Check"
    _cleanup_widget(qapp, window)


def test_recent_searches_filter_commands_and_navigation_labels(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))

    record_recent_search("refresh", kind="Search")
    record_recent_search("Library", kind="Search")
    record_recent_search("P4-EOAT-0052", kind="EOAT")

    assert [item["query"] for item in load_recent_searches()] == ["P4-EOAT-0052"]


def test_command_palette_rows_have_room_for_two_lines(qapp) -> None:
    row = SearchResultRow("Open Tool 6201510010", "Tool", "Demo part | Machines: 52")
    compact = SearchResultRow("P4-EOAT-0052", "EOAT", "", compact=True)
    suggestion = SearchSuggestionRow("Library", "library")

    assert row.minimumHeight() >= 56
    assert compact.minimumHeight() >= 44
    assert suggestion.minimumHeight() >= 44
    for button in (row, compact, suggestion):
        clicked_methods = [
            button.metaObject().method(index)
            for index in range(button.metaObject().methodCount())
            if bytes(button.metaObject().method(index).methodSignature()).decode().startswith("clicked(")
        ]
        assert {bytes(method.methodSignature()).decode() for method in clicked_methods} == {"clicked()", "clicked(bool)"}
        assert {method.enclosingMetaObject().className() for method in clicked_methods} == {"QAbstractButton"}
        assert button.metaObject().methodOffset() == button.metaObject().methodCount()


def test_deep_refresh_palette_filters_without_running_then_clicks_once(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    calls: list[tuple[str, bool]] = []
    window.deep_refresh_data = lambda: calls.append(("deep_refresh", overlay.isVisible()))

    overlay.set_search_text("Deep Refresh")
    qapp.processEvents()

    assert calls == []
    row = _result_row(overlay, "Deep Refresh")
    QTest.mouseClick(row, Qt.MouseButton.LeftButton)
    qapp.processEvents()

    assert calls == [("deep_refresh", False)]
    assert overlay.search_box.input.text() == ""
    _cleanup_widget(qapp, window)


def test_deep_refresh_palette_enter_runs_once(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    calls: list[str] = []
    window.deep_refresh_data = lambda: calls.append("deep_refresh")
    overlay.set_search_text("Deep Refresh")
    overlay.search_box.input.setFocus()

    QTest.keyClick(overlay.search_box.input, Qt.Key.Key_Return)
    qapp.processEvents()

    assert calls == ["deep_refresh"]
    _cleanup_widget(qapp, window)


def test_palette_logging_failure_is_best_effort_and_non_recursive(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    calls: list[str] = []
    warnings: list[tuple[object, ...]] = []
    window.deep_refresh_data = lambda: calls.append("deep_refresh")

    def fail_activity_log(*_args, **_kwargs):
        raise OSError("simulated activity log failure")

    monkeypatch.setattr(command_palette_module, "log_activity_event", fail_activity_log)
    monkeypatch.setattr(command_palette_module.LOGGER, "warning", lambda *args, **_kwargs: warnings.append(args))
    overlay.set_search_text("Deep Refresh")
    qapp.processEvents()

    QTest.mouseClick(_result_row(overlay, "Deep Refresh"), Qt.MouseButton.LeftButton)
    qapp.processEvents()

    assert calls == ["deep_refresh"]
    assert warnings == []
    assert overlay._command_dispatch_in_progress is False
    _cleanup_widget(qapp, window)


def test_palette_command_failure_logs_once_and_keeps_window_usable(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    logged: list[tuple[object, ...]] = []
    statuses: list[str] = []

    def fail_deep_refresh() -> None:
        raise RuntimeError("simulated refresh failure")

    window.deep_refresh_data = fail_deep_refresh
    window.show_status = statuses.append
    monkeypatch.setattr("app.atlas.minimalist.overlays.LOGGER.exception", lambda *args, **_kwargs: logged.append(args))
    overlay.set_search_text("Deep Refresh")
    QTest.qWait(300)
    qapp.processEvents()
    QTest.mouseClick(_result_row(overlay, "Deep Refresh"), Qt.MouseButton.LeftButton)
    qapp.processEvents()

    assert len(logged) == 1
    assert statuses == ["Command Palette action failed: RuntimeError: simulated refresh failure"]
    assert overlay._command_dispatch_in_progress is False
    assert overlay._callback_dispatch_pending is False
    assert window.isVisible()
    _cleanup_widget(qapp, window)


def test_palette_reopen_does_not_accumulate_command_connections(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    calls: list[str] = []
    window.deep_refresh_data = lambda: calls.append("deep_refresh")

    for _ in range(8):
        window.close_all_search_overlays()
        window._context_search_shortcut()
        overlay.set_search_text("Deep Refresh")
        qapp.processEvents()
    QTest.mouseClick(_result_row(overlay, "Deep Refresh"), Qt.MouseButton.LeftButton)
    qapp.processEvents()

    assert calls == ["deep_refresh"]
    _cleanup_widget(qapp, window)


def test_deep_refresh_palette_can_run_twenty_times_without_nesting(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    calls: list[int] = []
    nesting = 0
    max_nesting = 0

    def deep_refresh() -> None:
        nonlocal nesting, max_nesting
        nesting += 1
        max_nesting = max(max_nesting, nesting)
        calls.append(len(calls))
        nesting -= 1

    window.deep_refresh_data = deep_refresh
    for index in range(20):
        window._context_search_shortcut()
        overlay.set_search_text("Deep Refresh")
        qapp.processEvents()
        if index % 2:
            QTest.keyClick(overlay.search_box.input, Qt.Key.Key_Return)
        else:
            QTest.mouseClick(_result_row(overlay, "Deep Refresh"), Qt.MouseButton.LeftButton)
        qapp.processEvents()

    assert len(calls) == 20
    assert max_nesting == 1
    assert overlay._command_dispatch_in_progress is False
    _cleanup_widget(qapp, window)


def test_palette_navigation_mouse_keyboard_and_unknown_query(qapp, tmp_path: Path, monkeypatch) -> None:
    window, overlay = _open_palette_window(qapp, tmp_path, monkeypatch)
    pages: list[str] = []
    activity_events: list[str] = []
    window.show_page = lambda key: pages.append(key) or True
    monkeypatch.setattr(
        command_palette_module,
        "log_activity_event",
        lambda _root, event_name, _payload: activity_events.append(event_name) or None,
    )

    overlay.set_search_text("Open Settings")
    qapp.processEvents()
    QTest.mouseClick(_result_row(overlay, "Open Settings"), Qt.MouseButton.LeftButton)
    qapp.processEvents()
    window._context_search_shortcut()
    overlay.set_search_text("Open Settings")
    qapp.processEvents()
    QTest.keyClick(overlay.search_box.input, Qt.Key.Key_Return)
    qapp.processEvents()

    assert pages == ["settings", "settings"]
    assert activity_events == ["command_palette_selection", "command_palette_selection"]

    window._context_search_shortcut()
    overlay.set_search_text("not-a-real-command-or-record")
    qapp.processEvents()
    QTest.keyClick(overlay.search_box.input, Qt.Key.Key_Return)
    qapp.processEvents()

    assert pages == ["settings", "settings"]
    assert activity_events == ["command_palette_selection", "command_palette_selection"]
    _cleanup_widget(qapp, window)


def test_non_palette_deep_refresh_still_uses_real_refresh_entrypoint(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    calls: list[dict[str, bool]] = []
    window.refresh_data = lambda **kwargs: calls.append(kwargs)

    window.deep_refresh_data()

    assert calls == [{"deep_refresh": True}]
    _cleanup_widget(qapp, window)


def test_palette_deep_refresh_rebuilds_once_with_stale_settings_generation_removed(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    initial = _palette_bundle(tmp_path)
    replacement = replace(initial, loaded_at="2026-07-13 13:30", metrics={"deep_refresh": True})
    window._data_loaded(initial)
    window.show()
    window.show_page("settings")
    settings = window.settings_page.settings_content
    settings.select_section("refresh_cache")
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert settings.source_rows == {}

    started = threading.Event()
    release = threading.Event()
    loader_calls: list[bool] = []

    def fake_load(*_args, **kwargs):
        loader_calls.append(bool(kwargs.get("force_refresh")))
        started.set()
        release.wait(2.0)
        return replacement

    monkeypatch.setattr("core.atlas_data_loader.load_atlas_data", fake_load)
    window.show_page("home")
    window._context_search_shortcut()
    qapp.processEvents()
    overlay = window.home_page.shell.search_overlay
    overlay.set_search_text("Deep Refresh")
    QTest.qWait(300)
    qapp.processEvents()
    QTest.mouseClick(_result_row(overlay, "Deep Refresh"), Qt.MouseButton.LeftButton)

    assert _wait_for_qt(qapp, lambda: started.is_set() and window._refresh_in_progress)
    window.deep_refresh_data()
    assert loader_calls == [True]
    release.set()
    assert _wait_for_qt(qapp, lambda: not window._refresh_in_progress and window.bundle is replacement)
    assert settings.bundle is replacement
    assert settings.source_rows == {}
    window.show_page("settings")
    settings.select_section("data_sources")
    qapp.processEvents()
    assert all(row.is_live() for row in settings.source_rows.values())
    _cleanup_widget(qapp, window)


def test_repeated_preview_settings_refresh_and_palette_stress_in_one_session(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    bundle = _palette_bundle(tmp_path)
    window._data_loaded(bundle)
    window.show()
    window.show_page("settings")
    settings = window.settings_page.settings_content
    deep_refresh_calls: list[int] = []
    window.deep_refresh_data = lambda: deep_refresh_calls.append(len(deep_refresh_calls))
    detail = RecordDetailData(
        record_type="setup_packet",
        record_id="Tool 6201510010 / Machine 52 / EOAT P4-EOAT-0052",
        title="Setup Packet",
        subtitle="Stress preview",
        condition="Compatible",
        plant_area="",
        hero_fields=(),
        detail_sections=(),
        documentation_fields=(),
        photo_groups=(),
        history_fields=(),
        summary_fields=(),
        report_sections=(),
    )
    preview_root = tmp_path / "eoat_atlas_setup_packet_previews"

    for index in range(3):
        settings.select_section("data_sources")
        settings._start_admin_session()
        settings.set_bundle(None)
        settings.select_section("refresh_cache")
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        settings.set_bundle(bundle)
        settings.admin_active = False
        settings._sync_admin_state(rerender=True)
        qapp.processEvents()
        assert settings.source_rows == {}

        temp_pdf = _write_minimal_pdf(preview_root / f"stress_{index}.pdf")
        session = PdfPreviewSession(
            "setup_packet",
            detail.record_id,
            temp_pdf,
            tmp_path / "exports" / temp_pdf.name,
            temp_preview_dir=preview_root,
            auto_save_close_seconds=0,
        )
        preview = PDFPreviewOverlay.open_for(window, session, detail, project_root=str(tmp_path))
        qapp.processEvents()
        preview.close_preview()
        assert _wait_for_qt(qapp, lambda path=temp_pdf: not path.exists(), timeout_ms=2000)

        window._apply_bundle_to_pages(None)
        window._apply_bundle_to_pages(bundle)
        window.show_page("home")
        window._context_search_shortcut()
        qapp.processEvents()
        overlay = window.home_page.shell.search_overlay
        overlay.set_search_text("Deep Refresh")
        QTest.qWait(300)
        QTest.mouseClick(_result_row(overlay, "Deep Refresh"), Qt.MouseButton.LeftButton)
        qapp.processEvents()
        window.show_page("settings")

    assert deep_refresh_calls == [0, 1, 2]
    settings.select_section("data_sources")
    qapp.processEvents()
    assert all(row.is_live() for row in settings.source_rows.values())
    _cleanup_widget(qapp, window)


def _palette_bundle(tmp_path: Path) -> AtlasDataBundle:
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0052",
        display_id="P4-EOAT-0052",
        tools=("6201510010",),
        machines=("52",),
        eoat_type="Vacuum",
        status="Installed",
    )
    tool = ToolRecord(
        tool="6201510010",
        label="Tool 6201510010",
        compatible_eoats=(eoat.eoat_id,),
        compatible_machines=("52",),
        part_description="Demo part",
    )
    machine = MachineRecord(
        machine="52",
        label="Machine 52",
        robot_type="Engel Viper",
        compatible_eoats=(eoat.eoat_id,),
        compatible_tools=(tool.tool,),
        current_eoat=eoat.eoat_id,
    )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat.eoat_id): eoat.eoat_id},
        eoats_by_tool={normalized_tool_key(tool.tool): (eoat.eoat_id,)},
        eoats_by_machine={normalized_machine_key(machine.machine): (eoat.eoat_id,)},
        machines_by_tool={normalized_tool_key(tool.tool): (machine.machine,)},
        machines_by_eoat={normalized_eoat_key(eoat.eoat_id): (machine.machine,)},
        tools_by_machine={normalized_machine_key(machine.machine): (tool.tool,)},
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-07 12:00",
        eoats=(eoat,),
        machines=(machine,),
        tools=(tool,),
        indexes=indexes,
    )


def _open_palette_window(qapp, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_palette_bundle(tmp_path))
    window.show()
    window._context_search_shortcut()
    qapp.processEvents()
    return window, window.home_page.shell.search_overlay


def _result_row(overlay, title: str) -> SearchResultRow:
    for row in overlay.findChildren(SearchResultRow):
        if row._title.text() == title and row.isVisible():
            return row
    raise AssertionError(f"No visible command-palette row titled {title!r}")


def _wait_for_qt(qapp, predicate, *, timeout_ms: int = 3000) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        qapp.processEvents()
        if predicate():
            return True
        QTest.qWait(10)
        elapsed += 10
    qapp.processEvents()
    return bool(predicate())


def _write_minimal_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    return path


def _cleanup_widget(qapp, widget) -> None:
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
