from __future__ import annotations

from pathlib import Path

from core.atlas_data_loader import invalidate_atlas_data_cache, load_atlas_data
from core.atlas_information_library import (
    BANNED_GENERIC_PHRASES,
    build_information_entries,
    information_score,
    information_snippet,
    validate_information_library,
)
from tests.fixtures.fake_project import create_fake_eoat_project
from tests.fixtures.reference_workbooks import create_press_reference_workbooks


def test_information_library_seed_content_is_structured_and_valid(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    (root / "03_Standards").mkdir(exist_ok=True)
    (root / "03_Standards" / "EOAT Standard Design Guidelines.md").write_text(
        "# EOAT Standard Design Guidelines\n\nVacuum cups, sensors, and documentation should be auditable.\n",
        encoding="utf-8",
    )
    invalidate_atlas_data_cache(root)
    bundle = load_atlas_data(root, force_refresh=True)

    entries = build_information_entries(bundle)
    titles = {entry.title for entry in entries}

    assert not validate_information_library(entries)
    assert len(entries) >= 80
    assert {
        "Home / Command Deck",
        "What Do I Need?",
        "Vacuum Cup Selection",
        "Tool-to-Machine Fit Check",
        "EOAT Assembly ID",
        "Photos do not preview",
        "Documentation Gap Report",
        "Weekly EOAT Inspection",
        "Press Capacity Workbook",
    }.issubset(titles)

    off_machine = next(entry for entry in entries if entry.title == "Off-Machine EOAT Audit Handling")
    assert off_machine.entry_type == "compatibility_rule"
    assert off_machine.examples
    assert "Machine 12" in off_machine.examples[0].text

    data_field = next(entry for entry in entries if entry.title == "Fit Check Confidence")
    assert data_field.entry_type == "data_dictionary"
    assert {"Definition", "Source Of Truth", "Used By", "Repair Action"}.issubset(
        {section.title for section in data_field.sections}
    )

    body_text = "\n".join(entry.body for entry in entries)
    for phrase in BANNED_GENERIC_PHRASES:
        assert phrase not in body_text
    assert all(entry.source.file_label != "-" for entry in entries)
    assert all(entry.source.modified_label != "-" for entry in entries)


def test_information_library_search_includes_examples_sources_and_related_fields(tmp_path: Path) -> None:
    root = create_fake_eoat_project(tmp_path)
    create_press_reference_workbooks(root / "00_Project_Admin" / "reference_data")
    invalidate_atlas_data_cache(root)
    bundle = load_atlas_data(root, force_refresh=True)
    entries = build_information_entries(bundle)

    off_machine = next(entry for entry in entries if entry.title == "Off-Machine EOAT Audit Handling")
    cup_material = next(entry for entry in entries if entry.title == "Cup Material")
    source_doc = next(entry for entry in entries if entry.title == "Press Capacity Workbook")

    assert information_score(off_machine, "Machine 22") > 0
    assert information_score(cup_material, "Cleanroom Documentation") > 0
    assert information_score(source_doc, "tool machine compatibility") > 0
    assert "[Machine" in information_snippet(off_machine, "Machine 22")
