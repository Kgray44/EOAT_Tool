from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from core.data_gateway.mappings import snapshot_to_bundle
from scripts.database.import_eoat_location_observations import build_plan, read_rows


HEADERS = [
    "Audit ID", "Audit Date", "Entry Type", "EOAT Assembly ID", "Press/Machine #",
    "Audit Context", "Physical Audit Verified", "Notes",
]


def _workbook(path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "EOAT Inventory"
    sheet.append(HEADERS)
    sheet.append(["A-1", "2026-06-18", "Audited", "EOAT-1", "101", "Installed on Machine", "Yes", ""])
    sheet.append(["A-2", "2026-06-18", "Audited", "EOAT-2", "102", "Installed on Machine", "Yes", "EOAT is in cabinet"])
    book.save(path)


def test_observation_plan_is_deterministic_and_keeps_date_only_precision(tmp_path: Path) -> None:
    path = tmp_path / "EOAT_Master_Tracker.xlsx"
    _workbook(path)
    database = {
        "eoats": [
            {"business_identifier": "EOAT-1", "is_active": True},
            {"business_identifier": "EOAT-2", "is_active": True},
        ],
        "relationships": {"installations": [], "storage_assignments": []},
    }
    first = build_plan(read_rows(path), database, path)
    second = build_plan(read_rows(path), database, path)
    assert first == second
    assert [row["state"] for row in first["observations"]] == ["INSTALLED", "STORED"]
    assert all("observed_on" in row and "observed_at" not in row for row in first["observations"])
    assert first["observations"][1]["storage_location"] is None
    assert len(first["assertions"]) == 2


def test_client_mapping_keeps_compatibility_separate_from_current_location() -> None:
    bundle = snapshot_to_bundle({
        "eoats": [{
            "business_identifier": "EOAT-1", "relationships": [
                {"relationship_type": "machine", "identifier": "101"},
                {"relationship_type": "machine", "identifier": "102"},
            ],
            "current_location": "STORED — cabinet/location unspecified",
            "current_location_detail": {"state": "STORED", "source": "OBSERVATION", "confidence": "High"},
        }],
        "machines": [
            {"machine_number": "101", "relationships": [], "current_eoat": "NONE_OBSERVED"},
            {"machine_number": "102", "relationships": [], "current_eoat": "NONE_OBSERVED"},
        ],
    })
    assert bundle.eoats[0].machines == ("101", "102")
    assert bundle.eoats[0].current_location.startswith("STORED")
    assert all(not machine.current_eoat for machine in bundle.machines)


def test_migration_does_not_convert_observations_into_lifecycle_history() -> None:
    migration = Path("server/migrations/versions/20260717_0007_eoat_location_observations.py").read_text(encoding="utf-8")
    assert "eoat_location_observations" in migration
    assert "eoat_location_assertions" in migration
    assert "eoat_installations" not in migration
    assert "eoat_storage_assignments" not in migration
    assert "observation_precision = 'DATE' AND observed_at IS NULL" in migration
