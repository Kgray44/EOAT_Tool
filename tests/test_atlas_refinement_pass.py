from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QPushButton, QToolButton

from app.atlas import pages as atlas_pages
from app.atlas.command_palette import build_atlas_commands, resolve_atlas_commands
from app.atlas.settings import AtlasSettings
from app.atlas.widgets import AccordionSection, DocumentCard
from core.atlas_health import (
    RelationshipHealth,
    eoat_relationship_health,
    machine_relationship_health,
    tool_relationship_health,
    validation_relationship_health,
)
from core.atlas_models import (
    AtlasDataBundle,
    AtlasIndexes,
    DocumentationStatus,
    EOATRecord,
    MachineRecord,
    PhotoItem,
    PhotoSet,
    StandardReference,
    ToolRecord,
    WarningItem,
)
from core.atlas_reports import atlas_report_catalog, generate_atlas_report
from core.atlas_search import search_atlas
from core.atlas_setup_packets import (
    COMPATIBILITY_CONFIRMED,
    COMPATIBILITY_NOT_CONFIRMED,
    selectable_eoats,
    selectable_machines,
    selectable_tools,
)
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.paths import resolve_project_paths


def test_machine_numeric_search_is_exact(tmp_path: Path) -> None:
    bundle = _indexed_bundle(tmp_path)

    assert _search_keys(bundle, "36") == [("machine", "36")]
    assert _search_keys(bundle, "6") == [("machine", "6")]
    assert _search_keys(bundle, "machine 36") == [("machine", "36")]


def test_tool_exact_search_ranks_exact_before_prefix_and_substring(tmp_path: Path) -> None:
    matches = search_atlas(_indexed_bundle(tmp_path), "5620040010")

    tool_matches = [match for match in matches if match.result_type == "tool"]

    assert tool_matches
    assert tool_matches[0].key == "5620040010"
    assert tool_matches[0].score > tool_matches[-1].score


def test_eoat_suffix_search_ranks_exact_suffix_first(tmp_path: Path) -> None:
    matches = search_atlas(_indexed_bundle(tmp_path), "0001")

    assert matches[0].result_type == "eoat"
    assert matches[0].key == "P4-EOAT-0001"


def test_selection_filters_are_order_independent_for_any_two_constraints(tmp_path: Path) -> None:
    bundle = _indexed_bundle(tmp_path)

    assert [tool.tool for tool in selectable_tools(bundle, machine_id="36", eoat_id="P4-EOAT-0001")] == ["5620040010"]
    assert [machine.machine for machine in selectable_machines(bundle, tool_id="5620040010", eoat_id="P4-EOAT-0001")] == ["36"]
    assert [eoat.eoat_id for eoat in selectable_eoats(bundle, machine_id="36", tool_id="5620040010")] == ["P4-EOAT-0001"]
    assert selectable_eoats(bundle, machine_id="36", tool_id="NO-LINK") == ()


def test_relationship_health_states_ignore_common_warnings_for_color_decisions(tmp_path: Path) -> None:
    bundle = _indexed_bundle(tmp_path)
    verified_eoat = bundle.eoats[0]
    common_warning_eoat = replace(
        verified_eoat,
        warnings=(WarningItem("warning", "Photo category cleanup", "Common cleanup warning."),),
    )

    assert eoat_relationship_health(common_warning_eoat) == RelationshipHealth.VERIFIED
    assert machine_relationship_health(bundle.machines[0]) == RelationshipHealth.VERIFIED
    assert tool_relationship_health(ToolRecord(tool="NO-EOAT", label="Tool NO-EOAT")) == RelationshipHealth.MISSING
    assert validation_relationship_health(COMPATIBILITY_CONFIRMED) == RelationshipHealth.VERIFIED
    assert validation_relationship_health(COMPATIBILITY_NOT_CONFIRMED) == RelationshipHealth.INVALID


def test_applicable_standards_section_uses_clear_labels(qapp, tmp_path: Path) -> None:
    eoat = _indexed_bundle(tmp_path).eoats[0]

    section = atlas_pages._eoat_applicable_standards_section(eoat)
    text = _widget_text(section)

    assert "Applicable Standards (1)" in text
    assert "Standards: 1" in text
    assert "Tubing & Routing Standard" in text
    assert "Why it applies" in text
    assert "Status for this EOAT" in text
    assert "Source document/report path" in text


def test_report_catalog_registers_required_handoff_cards(tmp_path: Path) -> None:
    catalog = atlas_report_catalog()
    names = {definition.name for definition in catalog}
    sections = {definition.section for definition in catalog}

    assert {
        "Generate Changeover Packet PDF",
        "Export Compatibility Data Table CSV",
        "Missing Validated EOAT Report",
        "Documentation Gap Report",
        "Photo Coverage Report",
        "PM Checklist Package",
        "Build Final Handoff Package",
    }.issubset(names)
    assert {
        "Setup / Changeover",
        "Compatibility",
        "Documentation",
        "Photos",
        "PM / Inspection",
        "Analytics / Management",
        "Final Handoff",
    }.issubset(sections)

    path = generate_atlas_report(_indexed_bundle(tmp_path), "compatibility.csv")

    assert path.exists()
    assert path.suffix == ".csv"
    assert "P4-EOAT-0001" in path.read_text(encoding="utf-8")


def test_command_registry_contains_required_navigation_and_actions(tmp_path: Path) -> None:
    window = _PaletteWindow(_indexed_bundle(tmp_path))
    titles = {command.title for command in build_atlas_commands(window)}

    assert {
        "Open Home / Command Deck",
        "Open What Do I Need?",
        "Open Changeover Packet Builder",
        "Open EOAT Profiles",
        "Open Machine Profiles",
        "Open Tool/Mold/Part",
        "Open Photos",
        "Open Standards & Work Instructions",
        "Open Analytics Dashboard",
        "Open Reports & Handoff",
        "Open Settings / Diagnostics",
        "Generate Changeover Packet",
        "Generate Documentation Gap Report",
        "Generate Photo Coverage Report",
        "Generate Compatibility CSV",
        "Generate PM Checklist Package",
        "Build Final Handoff Package",
    }.issubset(titles)


def test_command_palette_resolves_common_query_examples(tmp_path: Path) -> None:
    window = _PaletteWindow(_indexed_bundle(tmp_path))

    expected = {
        "machine 36": "machine.36",
        "open machine 36": "machine.36",
        "tool 5620040010": "tool.5620040010",
        "eoat 0001": "eoat.p4eoat0001",
        "photos P4-EOAT-0001": "photos.p4eoat0001",
        "build packet machine 36": "dynamic.build_packet.machine.36",
        "missing photos": "question.missing_photos",
        "tools with no EOAT": "question.tools_no_eoat",
        "what standards apply to this EOAT?": "dynamic.standards.p4eoat0001",
        "what machines can run P4-EOAT-0001": "dynamic.eoat_machines.p4eoat0001",
        "what EOATs can run tool 5620040010": "dynamic.tool_eoats.5620040010",
        "what tools can run on machine 36": "dynamic.machine_tools.36",
        "refresh": "action.refresh",
    }

    for query, command_id in expected.items():
        commands = resolve_atlas_commands(window, query)
        assert commands, query
        assert commands[0].command_id == command_id


def test_setup_packet_selector_keeps_selected_record_and_clicks_exact_card(qapp) -> None:
    records = tuple(MachineRecord(str(index), f"Machine {index}") for index in range(1, 45))
    selected: list[str] = []
    selector = atlas_pages._SetupPacketRecordSelector(
        "Machine",
        "Search machines",
        lambda: records,
        lambda record: selected.append(record.machine),
        lambda _record: RelationshipHealth.VERIFIED,
    )

    selector.refresh("36", selected_record=records[35])
    selected_items = [selector.list.item(index) for index in range(selector.list.count()) if selector.list.item(index).isSelected()]
    selector._selected(selector.list.item(5))

    assert len(selected_items) == 1
    assert selected_items[0].data(atlas_pages.Qt.ItemDataRole.UserRole).machine == "36"
    assert selected == ["6"]


def test_document_preview_cleanup_strips_markdown_table_clutter() -> None:
    preview = atlas_pages.build_document_preview(
        {
            "title": "Documentation Gap Report",
            "type": "Generated Reports",
            "status": "Generated",
            "raw_preview": "## Executive Summary\n\n| Metric | Value |\n| --- | ---: |\n| EOATs scanned | 73 |\n| Documentation gaps | 30 |\n| Critical gaps | 0 |\n| Important gaps | 30 |",
            "is_blank": False,
        }
    )

    assert "##" not in preview
    assert "|" not in preview
    assert "73 EOATs scanned" in preview
    assert "30 documentation gaps" in preview


def test_standards_classifier_and_blank_detection(tmp_path: Path) -> None:
    standard = tmp_path / "Tubing_Routing_Standard.md"
    template = tmp_path / "Blank_PM_Template.md"
    report = tmp_path / "Documentation_Gap_Report.md"
    standard.write_text("# Tubing Standard\n\nControlled routing rules.\n", encoding="utf-8")
    template.write_text("template placeholder", encoding="utf-8")
    report.write_text("# Report\n\n73 EOATs scanned. 30 documentation gaps. 0 critical gaps.\n", encoding="utf-8")

    assert atlas_pages._classify_document("Tubing Routing Standard", "eoat standards", standard) == ("Controlled Standards", "Controlled")
    assert atlas_pages._classify_document("Blank PM Template", "template", template) == ("Templates", "Template")
    assert atlas_pages._classify_document("Documentation Gap Report", "Generated Reports", report) == ("Generated Reports", "Generated")
    assert atlas_pages._looks_blank_document(template) is True


def test_standards_page_hides_blank_templates_by_default(qapp, tmp_path: Path) -> None:
    standard = tmp_path / "Tubing_Routing_Standard.md"
    template = tmp_path / "Blank_PM_Template.md"
    standard.write_text("# Tubing Standard\n\nControlled routing rules.\n", encoding="utf-8")
    template.write_text("template placeholder", encoding="utf-8")
    bundle = replace(
        _indexed_bundle(tmp_path),
        standards=(
            StandardReference("Tubing Routing Standard", str(standard), "eoat standards", "Controlled routing rules."),
            StandardReference("Blank PM Template", str(template), "template", ""),
        ),
    )
    page = atlas_pages.StandardsPage(_SettingsController())
    page.set_bundle(bundle)
    text = _widget_text(page)

    assert "Tubing Routing Standard" in text
    assert "Blank PM Template" not in text
    assert any(isinstance(widget, DocumentCard) for widget in page.findChildren(DocumentCard))


def test_standards_documents_replace_stale_cached_path_with_live_revised_file(tmp_path: Path) -> None:
    paths = resolve_project_paths(tmp_path)
    paths.standards.mkdir(parents=True, exist_ok=True)
    old_standard = paths.standards / "EOAT_Standardization_Work_Instruction_Spaced_Annotated.pdf"
    revised_standard = paths.standards / "EOAT_Standardization_Work_Instruction_Revised.pdf"
    revised_standard.write_bytes(b"revised standard document")
    bundle = AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-06-25 08:00",
        standards=(
            StandardReference(
                "Eoat Standardization Work Instruction Spaced Annotated",
                str(old_standard),
                "eoat standards",
                "Old cached reference.",
            ),
        ),
    )

    titles = {document["title"] for document in atlas_pages._standards_documents(bundle)}

    assert "Eoat Standardization Work Instruction Revised" in titles
    assert "Eoat Standardization Work Instruction Spaced Annotated" not in titles


def test_analytics_snapshot_is_chart_ready(tmp_path: Path) -> None:
    snapshot = atlas_pages.build_analytics_snapshot(_indexed_bundle(tmp_path))

    assert set(snapshot["documentation_bins"]) == {"0-49%", "50-74%", "75-89%", "90-100%"}
    assert snapshot["eoat_type_counts"]["Vacuum"] == 1
    assert snapshot["warnings_by_category"]["Compatibility"] >= 0
    assert snapshot["coverage_metrics"]["tools_missing_validated_eoat"] == 2
    assert snapshot["machine_health_tiles"]


def test_settings_accordions_are_collapsed_by_default(qapp, tmp_path: Path) -> None:
    page = atlas_pages.DiagnosticsPage(_SettingsController())
    page.set_bundle(_indexed_bundle(tmp_path))
    sections = {section.header.text(): section for section in page.findChildren(AccordionSection)}

    assert {"QR Code Settings", "Photo Loading / Cache", "Data Sources", "Performance", "Reports & Export", "Advanced Diagnostics"}.issubset(sections)
    assert all(not section.body.isVisible() for section in sections.values())
    assert "General Settings" in _widget_text(page)
    assert "Data Refresh" in _widget_text(page)


def test_accordion_component_uses_clickable_header_without_clipped_body(qapp) -> None:
    section = AccordionSection("Photo Loading / Cache", "127 decoded images, 1347.7 / 1928 MB cache", status_text="Paused")

    assert section.header.isCheckable()
    assert section.header.minimumHeight() >= 58
    assert section.maximumHeight() > 1000
    assert section.body.maximumHeight() > 1000
    assert section.body.isVisible() is False


def _search_keys(bundle: AtlasDataBundle, query: str) -> list[tuple[str, str]]:
    return [(match.result_type, match.key) for match in search_atlas(bundle, query)]


def _indexed_bundle(tmp_path: Path) -> AtlasDataBundle:
    standard = StandardReference(
        "Tubing & Routing Standard",
        str(tmp_path / "Tubing_And_Routing_Standard.md"),
        "Tubing / Routing",
        "Use for pneumatic line routing and strain relief.",
    )
    photo = PhotoItem(path=str(tmp_path / "P4-EOAT-0001_overall.png"), filename="P4-EOAT-0001_overall.png")
    eoats = (
        EOATRecord(
            eoat_id="P4-EOAT-0001",
            display_id="P4-EOAT-0001",
            tools=("5620040010",),
            machines=("36",),
            eoat_type="Vacuum",
            status="Active",
            connection_type="M12 pneumatic quick disconnect",
            tubing_notes="Pneumatic lines routed along the wrist.",
            documentation=DocumentationStatus(score=88, status_label="Good"),
            photos=PhotoSet(eoat_id="P4-EOAT-0001", folder_exists=True, photos=(photo,)),
            standards=(standard,),
        ),
        EOATRecord(
            eoat_id="P4-EOAT-0010",
            display_id="P4-EOAT-0010",
            tools=("5620040010-REV",),
            machines=("6",),
            eoat_type="Gripper",
            status="Review",
            documentation=DocumentationStatus(score=72, status_label="Review"),
        ),
    )
    machines = (
        MachineRecord("36", "Machine 36", robot_type="Wittmann", compatible_eoats=("P4-EOAT-0001",), compatible_tools=("5620040010",), documentation_score=92),
        MachineRecord("6", "Machine 6", robot_type="Engel", compatible_eoats=("P4-EOAT-0010",), compatible_tools=("5620040010-REV",), documentation_score=85),
        MachineRecord("136", "Machine 136", robot_type="Fanuc", compatible_eoats=(), compatible_tools=("M36-SOMETHING",), documentation_score=70),
    )
    tools = (
        ToolRecord("5620040010", "Tool 5620040010", compatible_eoats=("P4-EOAT-0001",), compatible_machines=("36",), part_description="Exact part"),
        ToolRecord("5620040010-REV", "Tool 5620040010-REV", compatible_eoats=("P4-EOAT-0010",), compatible_machines=("6",), part_description="Prefix part"),
        ToolRecord("M36-SOMETHING", "Tool M36-SOMETHING", compatible_eoats=(), compatible_machines=("136",), part_description="Numeric noise guard"),
        ToolRecord("NO-LINK", "Tool NO-LINK", compatible_eoats=(), compatible_machines=("36",), part_description="Missing validated EOAT"),
    )
    indexes = AtlasIndexes(
        eoat_by_id={normalized_eoat_key(eoat.eoat_id): eoat.eoat_id for eoat in eoats},
        eoats_by_tool={
            normalized_tool_key("5620040010"): ("P4-EOAT-0001",),
            normalized_tool_key("5620040010-REV"): ("P4-EOAT-0010",),
        },
        eoats_by_machine={
            normalized_machine_key("36"): ("P4-EOAT-0001",),
            normalized_machine_key("6"): ("P4-EOAT-0010",),
        },
        machines_by_tool={
            normalized_tool_key("5620040010"): ("36",),
            normalized_tool_key("5620040010-REV"): ("6",),
            normalized_tool_key("NO-LINK"): ("36",),
        },
        machines_by_eoat={
            normalized_eoat_key("P4-EOAT-0001"): ("36",),
            normalized_eoat_key("P4-EOAT-0010"): ("6",),
        },
        tools_by_machine={
            normalized_machine_key("36"): ("5620040010", "NO-LINK"),
            normalized_machine_key("6"): ("5620040010-REV",),
        },
    )
    return AtlasDataBundle(
        project_root=str(tmp_path),
        loaded_at="2026-06-25 08:00",
        eoats=eoats,
        machines=machines,
        tools=tools,
        standards=(standard,),
        indexes=indexes,
    )


def _widget_text(widget) -> str:
    widgets = [*widget.findChildren(QLabel), *widget.findChildren(QPushButton), *widget.findChildren(QToolButton)]
    return "\n".join(child.text() for child in widgets if child.text())


class _PaletteWindow:
    def __init__(self, bundle: AtlasDataBundle):
        self.bundle = bundle
        self.settings = AtlasSettings()
        self.pages = {"eoats": SimpleNamespace(current=bundle.eoats[0] if bundle.eoats else None), "setup_packet": SimpleNamespace(reset_selection=lambda: None)}
        self.current_page_key = "eoats"
        self.status_messages: list[str] = []

    def show_page(self, key: str) -> None:
        self.current_page_key = key

    def open_eoat(self, _eoat_id: str) -> None:
        return None

    def open_machine(self, _machine_id: str) -> None:
        return None

    def open_tool(self, _tool_id: str) -> None:
        return None

    def open_photos(self, _eoat_id: str) -> None:
        return None

    def open_setup_packet(self, **_kwargs) -> None:
        return None

    def generate_install_packet_current_context(self) -> None:
        return None

    def refresh_data(self, *, force: bool = False) -> None:
        return None

    def toggle_dark_mode(self) -> None:
        return None

    def show_status(self, message: str) -> None:
        self.status_messages.append(message)


class _SettingsController(_PaletteWindow):
    def __init__(self, bundle: AtlasDataBundle | None = None):
        super().__init__(bundle or AtlasDataBundle(project_root="", loaded_at=""))
        self.photo_loader = SimpleNamespace(
            stats=lambda: {
                "cache_status": "Ready",
                "preload_mode": "balanced",
                "cache_entries": 0,
                "decoded_images": 0,
                "thumbnail_entries": 0,
                "full_entries": 0,
                "cache_memory_mb": 0,
                "cache_memory_limit_mb": 1928,
                "jobs_queued": 0,
                "active_jobs": 0,
                "last_decode_ms": 0,
                "failed_loads": 0,
                "event_loop_lag_ms": 0,
                "idle": True,
                "app_active": True,
                "last_preload_reason": "Ready",
                "last_completed_file": "",
            },
            clear_cache=lambda: None,
            prime_photo_cache=lambda: 0,
        )

    def update_settings(self, settings: AtlasSettings) -> None:
        self.settings = settings

    def refresh_data(self, *, force: bool = False) -> None:
        return None
