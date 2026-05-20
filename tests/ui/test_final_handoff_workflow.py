from __future__ import annotations

import json

import pytest

from app.pages.handoff import HandoffPage
from tests.ui.helpers import click_button, table_text, wait_for_background_tasks


pytestmark = pytest.mark.usability


def test_final_handoff_deliverable_assets_summary_dry_run_and_package(qapp, fake_config, fake_project):
    page = HandoffPage(fake_config)
    page.show()

    click_button(page, "Run Final Deliverable Check")
    wait_for_background_tasks()
    status_text = table_text(page.status_table)
    assert any(word in status_text for word in ["Found", "Partial", "Missing"])
    assert list((fake_project / "06_Final_Handoff" / "Handoff_Package").glob("Final_Deliverable_Check_*.md"))

    click_button(page, "Generate Presentation Assets")
    wait_for_background_tasks()
    assert list((fake_project / "06_Final_Handoff" / "Presentation" / "Auto_Exported_Content").glob("Presentation_Assets_*"))

    click_button(page, "Generate Final Project Summary Draft")
    wait_for_background_tasks()
    assert list((fake_project / "06_Final_Handoff" / "Final_Report").glob("Final_Project_Summary_Draft_*.md"))

    page.dry_run.setChecked(True)
    click_button(page, "Build Final Handoff Package")
    wait_for_background_tasks()
    assert list((fake_project / "06_Final_Handoff" / "Handoff_Package").glob("Final_Handoff_Dry_Run_*.md"))

    page.dry_run.setChecked(False)
    click_button(page, "Build Final Handoff Package")
    wait_for_background_tasks()
    package_root = fake_project / "06_Final_Handoff" / "Handoff_Package"
    assert list(package_root.glob("Final_Handoff_*"))
    assert list(package_root.rglob("HANDOFF_INDEX.md"))

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    entries = [json.loads(line) for line in activity_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry["tool_id"] == "final_handoff_builder" and entry["success"] for entry in entries)
