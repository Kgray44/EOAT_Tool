from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import func, select, text

from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from tests.fixtures.mysql_sanctioned import (
    EXPECTED_COUNTS,
    FIXTURE_SOURCE,
    STATUS_SCENARIOS,
    reset_and_load_sanctioned_fixture,
)

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Sanctioned fixture tests require EOAT_DB_NAME=eoat_atlas_test",
)


@pytest.fixture(scope="module", autouse=True)
def sanctioned_database():
    reset_and_load_sanctioned_fixture()


@pytest.fixture(scope="module")
def session():
    with create_session_factory(migration=True)() as value:
        yield value


def test_exact_fixture_counts_and_deterministic_identifiers(session):
    model_map = {
        "plants": db.Plant,
        "areas": db.Area,
        "eoats": db.EOAT,
        "machines": db.Machine,
        "tools": db.Tool,
        "robots": db.Robot,
        "eoat_machine_compatibility": db.EOATMachineCompatibility,
        "eoat_tool_compatibility": db.EOATToolCompatibility,
        "tool_machine_compatibility": db.ToolMachineCompatibility,
        "documents": db.Document,
        "photos": db.Photo,
        "document_links": db.DocumentLink,
        "audit_records": db.AuditRecord,
        "entity_history_events": db.EntityHistoryEvent,
        "eoat_installations": db.EOATInstallation,
        "eoat_storage_assignments": db.EOATStorageAssignment,
        "fit_check_records": db.FitCheckRecord,
        "application_releases": db.ApplicationRelease,
        "application_instances": db.ApplicationInstance,
        "import_batches": db.ImportBatch,
        "import_issues": db.ImportIssue,
    }
    for name, model in model_map.items():
        query = select(func.count(model.id))
        if hasattr(model, "source_system"):
            query = query.where(model.source_system == FIXTURE_SOURCE)
        assert session.scalar(query) == EXPECTED_COUNTS[name]
    identifiers = session.scalars(select(db.EOAT.business_identifier).order_by(db.EOAT.id)).all()
    assert identifiers[:2] == ["DEMO-P4-EOAT-0001", "DEMO-P4-EOAT-0002"]
    assert identifiers[-1] == "DEMO-P5-EOAT-0028"


def test_fixture_contains_no_private_strings_or_internal_paths(session):
    prohibited = re.compile(r"(?i)gwplastics|[a-z]:[\\/]users[\\/]|eoat_master_tracker|CL-EOAT-")
    values = []
    values.extend(session.scalars(select(db.EOAT.business_identifier)).all())
    values.extend(session.scalars(select(db.Document.storage_path)).all())
    values.extend(session.scalars(select(db.Document.title)).all())
    values.extend(session.scalars(select(db.ImportIssue.description)).all())
    assert not [value for value in values if value and prohibited.search(str(value))]


def test_fixture_foreign_keys_have_no_orphans(session):
    orphan_queries = (
        "SELECT COUNT(*) FROM machines m LEFT JOIN plants p ON p.id=m.plant_id WHERE p.id IS NULL",
        "SELECT COUNT(*) FROM eoat_machine_compatibility c LEFT JOIN eoats e ON e.id=c.eoat_id LEFT JOIN machines m ON m.id=c.machine_id WHERE e.id IS NULL OR m.id IS NULL",
        "SELECT COUNT(*) FROM eoat_tool_compatibility c LEFT JOIN eoats e ON e.id=c.eoat_id LEFT JOIN tools t ON t.id=c.tool_id WHERE e.id IS NULL OR t.id IS NULL",
        "SELECT COUNT(*) FROM document_links l LEFT JOIN documents d ON d.id=l.document_id WHERE d.id IS NULL",
    )
    assert all(session.scalar(text(query)) == 0 for query in orphan_queries)


def test_fixture_status_date_ambiguity_and_evidence_coverage(session):
    statuses = session.scalars(
        select(db.CompatibilityStatus.code)
        .join(db.EOATMachineCompatibility, db.EOATMachineCompatibility.compatibility_status_id == db.CompatibilityStatus.id)
        .where(db.EOATMachineCompatibility.source_system == FIXTURE_SOURCE)
    ).all()
    assert set(STATUS_SCENARIOS) <= set(statuses)
    duplicate_040 = session.scalars(
        select(db.Plant.plant_code).join(db.Machine).where(db.Machine.machine_number == "040").order_by(db.Plant.plant_code)
    ).all()
    assert duplicate_040 == ["DEMO-P4", "DEMO-P5"]
    assert session.scalar(select(func.count(db.Photo.id))) == 2
    assert session.scalar(select(func.count(db.DocumentLink.id))) == 4
    assert session.scalar(select(func.count(db.Photo.id)).where(db.Photo.is_profile_photo.is_(True))) == 1
