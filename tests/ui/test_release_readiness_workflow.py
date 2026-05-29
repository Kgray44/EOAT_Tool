from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from app.pages.backup_manager import BackupManagerPage
from app.pages.release_readiness import ReleaseReadinessPage
from tests.ui.helpers import click_button, wait_for_background_tasks

pytestmark = pytest.mark.usability


def test_backup_manager_page_previews_cleanup(qapp, fake_config, fake_project):
    page = BackupManagerPage(fake_config)
    page.show()

    click_button(page, "Preview Cleanup")
    wait_for_background_tasks()

    assert "Backup Count" in page.cards
    assert page.table.columnCount() > 0


def test_release_readiness_page_shows_checks_and_staged_files(qapp, fake_config):
    page = ReleaseReadinessPage(fake_config)
    page.show()

    assert any(label.text() == "Release Readiness" for label in page.findChildren(QLabel))
    assert page.table.rowCount() > 0

    click_button(page, "Show Staged Files")
    wait_for_background_tasks()
    assert page.staged_preview.toPlainText()
