from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox

from app.pages.audit import AuditPage
from core.audit_constants import AUDIT_CONTEXT_FIELD, AUDIT_CONTEXT_INSTALLED
from core.audit_entries import save_audit_entry
from core.eoat_ids import EOAT_ASSEMBLY_ID_FIELD
from tests.ui.helpers import click_button

pytestmark = pytest.mark.usability


def test_audit_page_defaults_audit_context_to_installed(qapp, fake_config):
    page = AuditPage(fake_config)
    page.show()

    assert page.audit_fields[AUDIT_CONTEXT_FIELD].currentText() == AUDIT_CONTEXT_INSTALLED


def test_audit_page_has_existing_eoat_dropdown_and_generate_button(qapp, fake_config, fake_project):
    assert save_audit_entry(
        fake_project,
        {
            "Audit Date": "2026-06-08",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "26",
            EOAT_ASSEMBLY_ID_FIELD: "P4-EOAT-0007",
            "Tool #": "5116830010",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Status": "Audited",
        },
    ).success

    page = AuditPage(fake_config)
    page.show()
    widget = page.audit_fields[EOAT_ASSEMBLY_ID_FIELD]

    assert isinstance(widget, QComboBox)
    assert widget.findText("P4-EOAT-0007") >= 0

    click_button(page, "Generate New EOAT ID")

    assert widget.currentText() == "P4-EOAT-0008"
