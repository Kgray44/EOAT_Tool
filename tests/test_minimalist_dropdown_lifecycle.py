from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel, QPushButton

from app.atlas.command_palette import resolve_atlas_commands
from app.atlas.minimalist.window import MinimalistAtlasWindow
from core.atlas_models import AtlasDataBundle, AtlasIndexes, EOATRecord, MachineRecord, ToolRecord
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.config import UserConfig
from core.fit_check_service import FitCheckRequest
from core.packet_builder_packets import PacketSetup


def test_home_lookup_closes_on_navigation_and_command_palette(qapp, tmp_path: Path) -> None:
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_dropdown_bundle(tmp_path))
    window.show()
    window.show_page("home")
    qapp.processEvents()

    card = window.home_page.home_content.card
    card.focus_search_text("620")
    qapp.processEvents()

    assert card.lookup_dropdown.isVisible()

    window.show_page("library")
    qapp.processEvents()

    assert not card.lookup_dropdown.isVisible()

    window.show_page("home")
    qapp.processEvents()

    assert not card.lookup_dropdown.isVisible()

    card.focus_search_text("620")
    qapp.processEvents()
    assert card.lookup_dropdown.isVisible()

    window._context_search_shortcut()
    qapp.processEvents()

    assert not card.lookup_dropdown.isVisible()
    assert window.home_page.shell.search_overlay.isVisible()
    _cleanup_widget(qapp, window)


def test_minimalist_menu_and_commands_hide_packet_builder(qapp, tmp_path: Path) -> None:
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_dropdown_bundle(tmp_path))
    window.show()
    qapp.processEvents()

    keys = set(window.home_page.shell.menu_overlay.buttons_by_key)
    assert keys == {"minimalist_home", "fit_check", "library", "settings"}

    commands = resolve_atlas_commands(window, "packet builder", limit=20)
    searchable = "\n".join(command.searchable_text() for command in commands)
    assert "packet builder" not in searchable
    assert "changeover" not in searchable

    commands = resolve_atlas_commands(window, "create packet", limit=20)
    assert all(command.command_id != "action.current_fit_packet" for command in commands)

    _cleanup_widget(qapp, window)


def test_fit_check_create_packet_modal_from_valid_setup(qapp, tmp_path: Path) -> None:
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_dropdown_bundle(tmp_path))
    window.show()
    window.show_page("fit_check")
    qapp.processEvents()

    content = window.fit_check_page.fit_content
    assert content.open_setup_packet_overlay(PacketSetup(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052"))
    qapp.processEvents()

    assert content.setup_packet_overlay.isVisible()
    assert content.result_card.create_packet.isVisible()
    assert window.current_fit_check_setup() == PacketSetup(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052")

    commands = resolve_atlas_commands(window, "create packet", limit=20)
    assert any(command.command_id == "action.current_fit_packet" for command in commands)
    assert all("packet builder" not in command.searchable_text() for command in commands)

    window.show_page("library")
    qapp.processEvents()

    assert not content.setup_packet_overlay.isVisible()
    _cleanup_widget(qapp, window)


def test_fit_check_typed_incompatible_eoat_stays_selected_and_recommendation_clicks(qapp, tmp_path: Path) -> None:
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_dropdown_bundle(tmp_path))
    window.show()
    window.show_page("fit_check")
    qapp.processEvents()

    content = window.fit_check_page.fit_content
    content.input_card.apply_request(FitCheckRequest(tool_id="6201510010", machine_id="Machine 52"))
    content._sync_selector_options()
    content.input_card.eoat_selector.set_query_text("P4-EOAT-0099")
    qapp.processEvents()
    content._run_requested()
    qapp.processEvents()

    result = content.current_result
    assert result is not None
    assert result.status == "not_compatible"
    assert content.input_card.selected_key("eoat") == "P4-EOAT-0099"
    assert content.result_card.headline.text() == "Not Compatible"
    assert "Insufficient Data" not in content.result_card.headline.text()
    assert "Select EOAT" not in content.result_card.message.text()
    assert content.result_card.reco_label.text() == "Recommended EOAT"
    assert content.result_card.reco_id.text() == "P4-EOAT-0052"
    assert content.path_row.cards[0].title.text() == "6201510010"
    assert content.path_row.cards[1].title.text() == "Machine 52"
    assert content.path_row.cards[2].title.text() == "P4-EOAT-0099"
    assert content.path_row.links[0]._status == "confirmed"
    assert content.path_row.links[1]._status == "conflict"
    assert all(row.value != "Select EOAT" for row in result.requirements)

    content.input_card.clear_slot(2, emit=True)
    qapp.processEvents()

    cleared = content.current_result
    assert cleared is not None
    assert cleared.status == "insufficient_data"
    assert content.input_card.selected_key("eoat") == ""
    assert not content.path_row.cards[2].isVisible()
    assert any(row.value == "Select EOAT" for row in cleared.requirements)

    content.input_card.eoat_selector.set_query_text("P4-EOAT-0099")
    qapp.processEvents()
    content._run_requested()
    qapp.processEvents()
    assert content.current_result is not None
    assert content.current_result.status == "not_compatible"

    content.alternatives_card._set_tab("eoats")
    qapp.processEvents()
    _click_alternative_row(content.alternatives_card.rows, "P4-EOAT-0052")
    qapp.processEvents()

    repaired = content.current_result
    assert repaired is not None
    assert repaired.status in {"compatible", "warning"}
    assert content.input_card.selected_key("eoat") == "P4-EOAT-0052"
    assert content.path_row.cards[2].title.text() == "P4-EOAT-0052"
    assert content.path_row.links[1]._status == "confirmed"

    content.alternatives_card._set_tab("machines")
    qapp.processEvents()
    _click_alternative_row(content.alternatives_card.rows, "Machine 53")
    qapp.processEvents()

    assert content.input_card.selected_key("machine") == "53"
    assert content.path_row.cards[1].title.text() == "Machine 53"
    assert content.current_result is not None
    assert content.current_result.status in {"compatible", "warning"}
    _cleanup_widget(qapp, window)


def test_fit_check_lower_sections_stay_aligned_with_input_during_resize(qapp, tmp_path: Path) -> None:
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.resize(1400, 900)
    window._data_loaded(_dropdown_bundle(tmp_path))
    window.show()
    window.show_page("fit_check")
    qapp.processEvents()

    content = window.fit_check_page.fit_content
    content.input_card.apply_request(FitCheckRequest(tool_id="6201510010", machine_id="Machine 52", eoat_id="P4-EOAT-0099", eoat_mode="manual"))
    content._sync_selector_options()
    content._refresh_result(animate=True)
    qapp.processEvents()

    window.resize(1120, 900)
    qapp.processEvents()
    _assert_fit_check_sections_aligned(content)

    window.resize(900, 900)
    qapp.processEvents()
    _assert_fit_check_sections_aligned(content)

    _cleanup_widget(qapp, window)


def _dropdown_bundle(tmp_path: Path) -> AtlasDataBundle:
    eoat = EOATRecord(
        eoat_id="P4-EOAT-0052",
        display_id="P4-EOAT-0052",
        tools=("6201510010",),
        machines=("52", "53"),
        eoat_type="Vacuum",
        status="Installed",
    )
    other_eoat = EOATRecord(
        eoat_id="P4-EOAT-0099",
        display_id="P4-EOAT-0099",
        tools=("9999999999",),
        machines=("99",),
        eoat_type="Vacuum",
        status="Installed",
    )
    tool = ToolRecord(
        tool="6201510010",
        label="Tool 6201510010",
        compatible_eoats=(eoat.eoat_id,),
        compatible_machines=("52", "53"),
        part_description="Demo part",
    )
    other_tool = ToolRecord(
        tool="9999999999",
        label="Tool 9999999999",
        compatible_eoats=(other_eoat.eoat_id,),
        compatible_machines=("99",),
        part_description="Other demo part",
    )
    machine = MachineRecord(
        machine="52",
        label="Machine 52",
        robot_type="Engel Viper",
        compatible_eoats=(eoat.eoat_id,),
        compatible_tools=(tool.tool,),
        current_eoat=eoat.eoat_id,
    )
    alt_machine = MachineRecord(
        machine="53",
        label="Machine 53",
        robot_type="Engel Viper",
        compatible_eoats=(eoat.eoat_id,),
        compatible_tools=(tool.tool,),
        current_eoat=eoat.eoat_id,
    )
    other_machine = MachineRecord(
        machine="99",
        label="Machine 99",
        robot_type="Engel Viper",
        compatible_eoats=(other_eoat.eoat_id,),
        compatible_tools=(other_tool.tool,),
        current_eoat=other_eoat.eoat_id,
    )
    indexes = AtlasIndexes(
        eoat_by_id={
            normalized_eoat_key(eoat.eoat_id): eoat.eoat_id,
            normalized_eoat_key(other_eoat.eoat_id): other_eoat.eoat_id,
        },
        eoats_by_tool={
            normalized_tool_key(tool.tool): (eoat.eoat_id,),
            normalized_tool_key(other_tool.tool): (other_eoat.eoat_id,),
        },
        eoats_by_machine={
            normalized_machine_key(machine.machine): (eoat.eoat_id,),
            normalized_machine_key(alt_machine.machine): (eoat.eoat_id,),
            normalized_machine_key(other_machine.machine): (other_eoat.eoat_id,),
        },
        machines_by_tool={
            normalized_tool_key(tool.tool): (machine.machine, alt_machine.machine),
            normalized_tool_key(other_tool.tool): (other_machine.machine,),
        },
        machines_by_eoat={
            normalized_eoat_key(eoat.eoat_id): (machine.machine, alt_machine.machine),
            normalized_eoat_key(other_eoat.eoat_id): (other_machine.machine,),
        },
        tools_by_machine={
            normalized_machine_key(machine.machine): (tool.tool,),
            normalized_machine_key(alt_machine.machine): (tool.tool,),
            normalized_machine_key(other_machine.machine): (other_tool.tool,),
        },
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-07-07 12:00",
        eoats=(eoat, other_eoat),
        machines=(machine, alt_machine, other_machine),
        tools=(tool, other_tool),
        indexes=indexes,
    )


def _click_alternative_row(container, text: str) -> None:
    for button in container.findChildren(QPushButton):
        labels = [label.text() for label in button.findChildren(QLabel)]
        if text in labels:
            button.click()
            return
    raise AssertionError(f"Alternative row not found: {text}")


def _assert_fit_check_sections_aligned(content) -> None:
    input_geometry = content.input_card.geometry()
    area_geometry = content.result_area.geometry()
    assert area_geometry.left() == input_geometry.left()
    assert area_geometry.width() == input_geometry.width()

    for widget in (content.result_card, content.path_row):
        geometry = widget.geometry()
        assert geometry.left() == 0
        assert geometry.width() == area_geometry.width()

    area_left = area_geometry.left()
    area_right = area_geometry.right()
    details = (content.requirements_card, content.warnings_card, content.alternatives_card)
    assert area_left + content.requirements_card.geometry().left() == input_geometry.left()
    if content.alternatives_card.geometry().top() == content.requirements_card.geometry().top():
        assert area_left + content.alternatives_card.geometry().right() == area_right
    else:
        assert all(area_left + widget.geometry().left() == input_geometry.left() for widget in details)
        assert all(widget.geometry().width() == area_geometry.width() for widget in details)


def _cleanup_widget(qapp, widget) -> None:
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
