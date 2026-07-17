from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.eoat_api.database import models as db

FIXTURE_SOURCE = "sanctioned_synthetic_fixture"
EVALUATION_TIME = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

EXPECTED_COUNTS = {
    "plants": 2,
    "areas": 4,
    "eoats": 57,
    "machines": 12,
    "tools": 12,
    "robots": 4,
    "eoat_machine_compatibility": 12,
    "eoat_tool_compatibility": 12,
    "tool_machine_compatibility": 12,
    "documents": 4,
    "photos": 2,
    "document_links": 4,
    "audit_records": 1,
    "entity_history_events": 4,
    "eoat_installations": 1,
    "eoat_storage_assignments": 1,
    "fit_check_records": 3,
    "application_releases": 1,
    "application_instances": 1,
    "import_batches": 1,
    "import_issues": 1,
}

STATUS_SCENARIOS = (
    "compatible",
    "verified_compatible",
    "approved",
    "incompatible",
    "failed",
    "not_compatible",
    "unknown",
    "needs_review",
    "pending",
    "unrecognized_status",
    "compatible",
    "compatible",
)


def deterministic_uuid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://example.invalid/eoat-atlas-fixture/{name}"))


def _lookup(session: Session, model: type, code: str, display_name: str | None = None):
    value = session.scalar(select(model).where(model.code == code))
    if value is None:
        value = model(code=code, display_name=display_name or code.replace("_", " ").title())
        session.add(value)
        session.flush()
    return value


def _fixture_count(session: Session, model: type) -> int:
    if hasattr(model, "source_system"):
        return int(session.scalar(select(func.count(model.id)).where(model.source_system == FIXTURE_SOURCE)) or 0)
    return int(session.scalar(select(func.count(model.id))) or 0)


def load_sanctioned_fixture(session: Session) -> dict[str, int]:
    """Load the deterministic public-safe MySQL fixture into a migrated empty test database."""
    if session.scalar(select(db.Plant.id).where(db.Plant.plant_code == "DEMO-P4")) is not None:
        raise RuntimeError("The sanctioned fixture is already loaded; reset eoat_atlas_test before loading it again.")

    statuses = {
        code: _lookup(session, db.CompatibilityStatus, code)
        for code in set(STATUS_SCENARIOS) | {"review_required"}
    }
    source = _lookup(session, db.CompatibilitySource, "synthetic_fixture", "Synthetic Fixture")
    document_type = _lookup(session, db.DocumentType, "document", "Document")
    photo_type = _lookup(session, db.DocumentType, "photo", "Photo")
    history_type = _lookup(session, db.HistoryEventType, "record_created", "Record Created")
    audit_history_type = _lookup(session, db.HistoryEventType, "audit_completed", "Audit Completed")
    active_status = _lookup(session, db.AssetStatus, "completed", "Active")
    archived_status = _lookup(session, db.AssetStatus, "archived", "Archived")

    release = db.ApplicationRelease(
        application_version="0.15.0",
        release_id="eoat-atlas-0.15.0-fixture",
        build_id="eoat-atlas-0.15.0-synthetic-fixture",
        commit_sha="0" * 40,
        release_channel="test",
        database_schema_revision="20260717_0007",
        api_contract_version="1.4.0",
        launcher_version="0.1.0",
        installer_version="0.1.0",
    )
    session.add(release)
    session.flush()

    batch = db.ImportBatch(
        batch_uuid=deterministic_uuid("import-batch"),
        batch_name="Sanctioned synthetic fixture",
        source_type="SYNTHETIC_TEST_FIXTURE",
        source_file_name="sanctioned_fixture.json",
        source_file_checksum=hashlib.sha256(b"sanctioned-fixture-v1").hexdigest(),
        started_at=EVALUATION_TIME,
        completed_at=EVALUATION_TIME,
        application_release_id=release.id,
        status="COMPLETED",
        dry_run=False,
        records_discovered=57,
        records_imported=57,
        warnings_count=1,
        notes="Unmistakably synthetic public test data.",
    )
    session.add(batch)
    session.flush()

    plants = []
    areas = []
    for plant_code in ("DEMO-P4", "DEMO-P5"):
        plant = db.Plant(
            plant_code=plant_code,
            plant_name=f"Synthetic {plant_code} Plant",
            description="Public-safe deterministic fixture plant.",
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(plant)
        session.flush()
        plants.append(plant)
        for suffix in ("MOLDING", "STORAGE"):
            area = db.Area(
                plant_id=plant.id,
                area_code=f"{plant_code}-{suffix}",
                area_name=f"Synthetic {suffix.title()}",
                area_type=suffix.casefold(),
                source_system=FIXTURE_SOURCE,
                source_import_batch_id=batch.id,
            )
            session.add(area)
            session.flush()
            areas.append(area)

    storage_locations = []
    for index, plant in enumerate(plants):
        location = db.StorageLocation(
            plant_id=plant.id,
            area_id=areas[index * 2 + 1].id,
            location_code=f"{plant.plant_code}-DEMO-STORAGE",
            location_name="Synthetic Fixture Storage",
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(location)
        storage_locations.append(location)

    machines = []
    machine_numbers = ("040", "041", "042", "043", "044", "045", "040", "046", "047", "048", "049", "050")
    for index, number in enumerate(machine_numbers):
        plant_index = 0 if index < 6 else 1
        machine = db.Machine(
            plant_id=plants[plant_index].id,
            area_id=areas[plant_index * 2].id,
            machine_number=number,
            machine_name=f"Synthetic Machine {plants[plant_index].plant_code}-{number}",
            status_id=archived_status.id if index == 11 else active_status.id,
            is_active=index != 11,
            archived_at=EVALUATION_TIME if index == 11 else None,
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(machine)
        session.flush()
        machines.append(machine)

    tools = []
    for index in range(1, 13):
        tool = db.Tool(
            business_identifier=f"DEMO-TOOL-{index:04d}",
            tool_number=f"DEMO-T{index:04d}",
            display_name=f"Synthetic Tool {index:04d}",
            status_id=archived_status.id if index == 12 else active_status.id,
            is_active=index != 12,
            archived_at=EVALUATION_TIME if index == 12 else None,
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(tool)
        session.flush()
        tools.append(tool)

    robots = []
    for index in range(1, 5):
        plant_index = (index - 1) // 2
        robot = db.Robot(
            plant_id=plants[plant_index].id,
            area_id=areas[plant_index * 2].id,
            robot_number=f"DEMO-ROBOT-{index:02d}",
            robot_name=f"Synthetic Robot {index:02d}",
            status_id=active_status.id,
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(robot)
        session.flush()
        robots.append(robot)

    session.add_all(
        [
            db.MachineRobotAssignment(
                machine_id=machines[index].id,
                robot_id=robots[index % 4].id,
                assigned_at=EVALUATION_TIME - timedelta(days=30),
                assignment_reason="Synthetic fixture assignment",
            )
            for index in range(4)
        ]
    )

    eoats = []
    for index in range(1, 58):
        plant_prefix = "P4" if index <= 29 else "P5"
        local_index = index if index <= 29 else index - 29
        eoat = db.EOAT(
            business_identifier=f"DEMO-{plant_prefix}-EOAT-{local_index:04d}",
            display_name=f"Synthetic {plant_prefix} EOAT {local_index:04d}",
            description="Public-safe deterministic EOAT fixture record.",
            status_id=archived_status.id if index == 57 else active_status.id,
            is_active=index != 57,
            archived_at=EVALUATION_TIME if index == 57 else None,
            number_of_parts_picked=(index % 4) + 1,
            sensors_present=index % 2 == 0,
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(eoat)
        session.flush()
        eoats.append(eoat)

    for index, status_code in enumerate(STATUS_SCENARIOS):
        effective_from = EVALUATION_TIME - timedelta(days=30)
        effective_to = None
        is_active = True
        if index == 10:
            effective_from = EVALUATION_TIME + timedelta(days=1)
        elif index == 11:
            effective_to = EVALUATION_TIME - timedelta(seconds=1)
        common = {
            "compatibility_status_id": statuses[status_code].id,
            "verification_source_id": source.id,
            "verified_at": EVALUATION_TIME - timedelta(days=1),
            "effective_from": effective_from,
            "effective_to": effective_to,
            "reason": f"Synthetic {status_code} scenario",
            "is_active": is_active,
            "source_system": FIXTURE_SOURCE,
            "source_import_batch_id": batch.id,
        }
        session.add(db.EOATMachineCompatibility(eoat_id=eoats[index].id, machine_id=machines[index].id, **common))
        session.add(db.EOATToolCompatibility(eoat_id=eoats[index].id, tool_id=tools[index].id, **common))
        session.add(db.ToolMachineCompatibility(tool_id=tools[index].id, machine_id=machines[index].id, **common))

    instance = db.ApplicationInstance(
        instance_uuid=deterministic_uuid("application-instance"),
        computer_name="DEMO-WORKSTATION",
        installation_name="Sanctioned Fixture",
        plant_id=plants[0].id,
        area_id=areas[0].id,
        application_version=release.application_version,
        release_id=release.release_id,
        build_id=release.build_id,
        application_release_id=release.id,
        launcher_version=release.launcher_version,
        operating_system="Synthetic Windows",
    )
    session.add(instance)
    session.flush()

    demo_user = db.User(
        external_identity="demo.engineer@example.invalid",
        external_subject="synthetic-demo-engineer",
        username="demo.engineer",
        display_name="Synthetic Demo Engineer",
        email="demo.engineer@example.invalid",
        authentication_provider="development",
        source_system=FIXTURE_SOURCE,
        source_import_batch_id=batch.id,
    )
    session.add(demo_user)
    session.flush()
    engineer_role = session.scalar(select(db.Role).where(db.Role.role_code == "ENGINEER"))
    if engineer_role is not None:
        session.add(db.UserRole(user_id=demo_user.id, role_id=engineer_role.id, assigned_at=EVALUATION_TIME))

    documents = []
    for index in range(1, 5):
        is_photo = index > 2
        file_name = f"demo-evidence-{index:02d}.{'png' if is_photo else 'pdf'}"
        document = db.Document(
            document_uuid=deterministic_uuid(f"document-{index}"),
            document_type_id=photo_type.id if is_photo else document_type.id,
            document_number=f"DEMO-DOC-{index:04d}",
            title=f"Synthetic Evidence {index:02d}",
            file_name=file_name,
            file_extension="png" if is_photo else "pdf",
            storage_path=f"https://example.invalid/eoat-atlas/{file_name}",
            storage_provider="synthetic_fixture",
            checksum_sha256=hashlib.sha256(file_name.encode()).hexdigest(),
            status_id=active_status.id,
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
        session.add(document)
        session.flush()
        documents.append(document)
        session.add(
            db.DocumentLink(
                document_id=document.id,
                entity_type="eoat",
                entity_id=eoats[index - 1].id,
                relationship_type="photo" if is_photo else "document",
                is_primary=index in {1, 3},
                created_by_user_id=demo_user.id,
            )
        )
        if is_photo:
            session.add(
                db.Photo(
                    document_id=document.id,
                    photo_view_type="profile" if index == 3 else "overview",
                    captured_at=EVALUATION_TIME - timedelta(days=index),
                    captured_by_user_id=demo_user.id,
                    caption=f"Synthetic photo {index}",
                    is_profile_photo=index == 3,
                    sort_order=index,
                    width_pixels=1200,
                    height_pixels=800,
                )
            )

    for index in range(4):
        session.add(
            db.EntityHistoryEvent(
                event_uuid=deterministic_uuid(f"history-{index}"),
                entity_type="eoat",
                entity_id=eoats[0].id,
                event_type_id=audit_history_type.id if index < 3 else history_type.id,
                occurred_at=EVALUATION_TIME - timedelta(hours=index),
                actor_user_id=demo_user.id,
                application_instance_id=instance.id,
                application_release_id=release.id,
                request_id=deterministic_uuid(f"history-request-{index}"),
                event_category="AUDITS" if index < 3 else "SYNTHETIC_FIXTURE",
                summary=f"Synthetic history event {index}",
                metadata_json={
                    "fixture": True,
                    "sequence": index,
                    "audit_id": f"DEMO-AUDIT-{index:04d}",
                },
                source_table="sanctioned_fixture",
                source_record_id=index + 1,
            )
        )

    session.add(
        db.AuditRecord(
            audit_identifier="DEMO-AUDIT-PROFILE-0001",
            eoat_id=eoats[1].id,
            machine_id=machines[1].id,
            tool_id=tools[1].id,
            robot_id=robots[0].id,
            audit_date=EVALUATION_TIME - timedelta(days=2),
            performed_by_user_id=demo_user.id,
            status_id=active_status.id,
            details_json={"fixture": True, "result": "synthetic-pass"},
            notes="Synthetic profile audit evidence.",
            source_system=FIXTURE_SOURCE,
            source_import_batch_id=batch.id,
        )
    )

    session.add(
        db.EOATInstallation(
            eoat_id=eoats[20].id,
            machine_id=machines[4].id,
            tool_id=tools[4].id,
            robot_id=robots[0].id,
            installed_at=EVALUATION_TIME - timedelta(days=1),
            installed_by_user_id=demo_user.id,
            application_instance_id=instance.id,
            installation_reason="Synthetic active installation",
            source="synthetic_fixture",
        )
    )
    session.add(
        db.EOATStorageAssignment(
            eoat_id=eoats[21].id,
            storage_location_id=storage_locations[0].id,
            stored_at=EVALUATION_TIME - timedelta(days=1),
            stored_by_user_id=demo_user.id,
            reason="Synthetic storage assignment",
        )
    )

    fit_statuses = ("compatible", "incompatible", "needs_review")
    for index, status_code in enumerate(fit_statuses):
        status = statuses[status_code]
        session.add(
            db.FitCheckRecord(
                machine_id=machines[index + 1].id,
                tool_id=tools[index + 1].id,
                eoat_id=eoats[index + 1].id,
                overall_status_id=status.id,
                machine_tool_status_id=status.id,
                machine_eoat_status_id=status.id,
                tool_eoat_status_id=status.id,
                evaluation_engine_version="synthetic-fixture-v1",
                performed_at=EVALUATION_TIME + timedelta(minutes=index),
                performed_by_user_id=demo_user.id,
                application_instance_id=instance.id,
                request_id=deterministic_uuid(f"fit-check-{index}"),
                result_summary=f"Synthetic {status_code} Fit Check",
                result_details_json={"fixture": True, "status": status_code},
            )
        )

    issue = db.ImportIssue(
        import_batch_id=batch.id,
        severity="REVIEW",
        issue_code="SYNTHETIC_AMBIGUITY",
        field_name="machine_number",
        source_value="040",
        description="Synthetic duplicate machine number across demo plants.",
        suggested_resolution="Provide plant_code.",
    )
    session.add(issue)
    session.flush()

    models = {
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
    counts = {name: _fixture_count(session, model) for name, model in models.items()}
    for name, expected in EXPECTED_COUNTS.items():
        if counts[name] != expected:
            raise RuntimeError(f"Fixture count mismatch for {name}: expected {expected}, found {counts[name]}")
    return counts


def reset_and_load_sanctioned_fixture() -> dict[str, int]:
    """Drop, migrate, and load the sanctioned database for module-isolated integration tests."""
    from server.eoat_api.database.session import create_database_engine, dispose_database_engines

    root = Path(__file__).resolve().parents[2]
    dispose_database_engines()
    subprocess.run(
        [sys.executable, str(root / "scripts" / "database" / "reset_mysql_test_database.py")],
        cwd=root,
        check=True,
    )
    engine = create_database_engine(migration=True)
    with Session(engine) as session, session.begin():
        return load_sanctioned_fixture(session)
