from __future__ import annotations

from app.pages.audit import AuditPage
from core.annotations.service import AnnotationService
from core.workbook_io import row_dicts


def test_audit_coach_panel_renders_completion_and_hidden_reasons(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    page._set_field_value(page.audit_fields["EOAT Type"], "Mechanical / Gripper")
    page._set_field_value(page.audit_fields["# of Cups"], "N/A")
    page._set_field_value(page.audit_fields["Cup Type/Material"], "N/A")
    page._set_field_value(page.audit_fields["Cup Diameter/Size"], "N/A")
    page._set_field_value(page.audit_fields["Vacuum Generator Type"], "N/A")
    page._set_field_value(page.audit_fields["# of Grippers"], "2")
    page._set_field_value(page.audit_fields["Gripper Type"], "Single Pressure")
    page._set_field_value(page.audit_fields["Gripper Model"], "Demo Gripper")
    page._update_audit_field_visibility()
    page._refresh_audit_coach()

    assert "verified complete" in page.audit_coach_panel.summary_label.text()
    assert "EOAT Type and Tooling" in page.audit_coach_panel.section_text.toPlainText()
    hidden_text = page.audit_coach_panel.hidden_text.toPlainText()
    assert "# of Cups" in hidden_text
    assert "Cup Type/Material" in hidden_text
    assert "Vacuum tooling fields do not apply" in hidden_text


def test_audit_coach_open_and_mark_unknown_actions(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    page._set_field_value(page.audit_fields["Sensors Present?"], "Yes")
    page._set_field_value(page.audit_fields["Sensor Type"], "")
    page._update_audit_field_visibility()
    page.open_audit_coach_field("Sensor Type")

    current_title = page.audit_section_tabs.tabText(page.audit_section_tabs.currentIndex())
    assert current_title == "Sensors and Detection"

    page.mark_audit_coach_field_unknown("Sensor Type")

    assert page.audit_fields["Sensor Type"].text() == "Unknown / Not Checked"
    assert "not counted as verified complete" in page.result_panel.viewer.toPlainText()
    assert "Sensor Type" in page.audit_coach_panel.summary.unknown_not_checked_fields


def test_audit_coach_follow_up_and_needs_review_tag_use_existing_services(qapp, fake_config, fake_project):
    page = AuditPage(fake_config)
    page.show()
    audit_id = page.audit_fields["Audit ID"].text()

    page.create_audit_coach_follow_up("Sensor Brand/Model")
    page.tag_audit_coach_needs_review("Sensor Brand/Model")

    actions = row_dicts(fake_project / "01_EOAT_Audit" / "EOAT_Audit_Database" / "EOAT_Master_Tracker.xlsx", "Action Items")
    assert any("Sensor Brand/Model" in str(row.get("Action Item") or "") for row in actions)
    assert page.audit_fields["Follow-Up Needed"].currentText() == "Yes"

    service = AnnotationService(fake_project)
    assignments = service.list_tag_assignments(audit_id=audit_id, target_type="audit_field")
    assert any(assignment["tag_name"] == "Needs Review" and assignment["field_label"] == "Sensor Brand/Model" for assignment in assignments)
