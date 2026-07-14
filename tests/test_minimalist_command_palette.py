from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest

from app.atlas.minimalist.data import load_recent_searches, recent_entries, record_recent_search
from app.atlas.minimalist.overlays import SearchResultRow, SearchSuggestionRow
from app.atlas.minimalist.window import MinimalistAtlasWindow
from core.atlas_models import AtlasDataBundle, AtlasIndexes, EOATRecord, MachineRecord, ToolRecord
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.config import UserConfig


def test_empty_palette_library_suggestion_navigates_without_recent_search(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))
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
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))
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

    assert refreshed == [True]
    assert load_recent_searches() == []
    assert overlay.search_box.input.text() == ""

    window._context_search_shortcut()
    qapp.processEvents()
    assert overlay.search_box.input.text() == ""
    _cleanup_widget(qapp, window)


def test_palette_records_successful_entity_searches_only(qapp, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))
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
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))
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
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))
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
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_palette_bundle(tmp_path))

    window.open_tool("6201510010", source="fit_check")
    qapp.processEvents()

    assert window.current_page_key == "library"
    assert window.library_page.library_content.back_button_label() == "Back to Fit Check"
    _cleanup_widget(qapp, window)


def test_recent_searches_filter_commands_and_navigation_labels(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EOAT_COMMAND_CENTER_USER_DATA_DIR", str(tmp_path / "user_data"))

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


def _cleanup_widget(qapp, widget) -> None:
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
