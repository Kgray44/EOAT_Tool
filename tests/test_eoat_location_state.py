from tools.eoat_location_state import (
    STATE_CONFLICT,
    STATE_INSTALLED,
    STATE_STORED,
    STATE_UNKNOWN,
    classify_eoat_locations,
)


def _row(eoat, machine, *, notes="N/A", context="Installed on Machine", date="2026-06-01", tool="T1"):
    return {
        "EOAT Assembly ID": eoat,
        "Press/Machine #": machine,
        "Tool #": tool,
        "Entry Type": "Audited",
        "Audit Date": date,
        "Audit Context": context,
        "Physical Audit Verified": "Yes",
        "Notes": notes,
    }


def _database(eoats, *, installations=(), storage=(), machine_pairs=(), tool_pairs=()):
    return {
        "eoats": [{"business_identifier": item, "is_active": True, "status": "Active"} for item in eoats],
        "relationships": {
            "installations": list(installations),
            "storage_assignments": list(storage),
            "eoat_machine": [
                {"eoat_identifier": eoat, "machine_number": machine} for eoat, machine in machine_pairs
            ],
            "eoat_tool": [{"eoat_identifier": eoat, "tool_number": tool} for eoat, tool in tool_pairs],
        },
    }


def test_state_aware_classification_does_not_treat_compatibility_as_installation():
    rows = {
        2: _row("E-1", "1"),
        3: {**_row("E-1", "2"), "Entry Type": "Compatible", "Audit Date": None,
            "Audit Context": "Compatibility row", "Physical Audit Verified": "No"},
    }
    report = classify_eoat_locations(
        rows,
        _database(["E-1"], machine_pairs=[("E-1", "1"), ("E-1", "2")], tool_pairs=[("E-1", "T1")]),
    )
    record = report["records"][0]
    assert record["determined_physical_state"] == STATE_INSTALLED
    assert record["machine_number"] == "1"
    assert report["metrics"]["machine_compatibility_parity"]["source_assertions"] == 2


def test_explicit_cabinet_note_overrides_generic_installed_context_without_inventing_cabinet():
    rows = {2: _row("E-2", "12", notes="EOAT in cabinet.\nEOAT Not Installed.")}
    record = classify_eoat_locations(rows, _database(["E-2"]))["records"][0]
    assert record["determined_physical_state"] == STATE_STORED
    assert record["machine_number"] == ""
    assert "cabinet identifier not recorded" in record["storage_location"]
    assert "note governs" in record["unresolved_ambiguity"]


def test_removed_or_not_installed_without_storage_is_unknown():
    rows = {2: _row("E-3", "13", notes="EOAT was removed from machine before completed.")}
    record = classify_eoat_locations(rows, _database(["E-3"]))["records"][0]
    assert record["determined_physical_state"] == STATE_UNKNOWN
    assert record["normalized_location_parity"] == "PASS"


def test_simultaneous_latest_verified_machines_are_conflicting():
    rows = {2: _row("E-4", "1"), 3: _row("E-4", "2")}
    record = classify_eoat_locations(rows, _database(["E-4"]))["records"][0]
    assert record["determined_physical_state"] == STATE_CONFLICT
    assert record["normalized_location_parity"] == "UNRESOLVED"


def test_same_physical_eoat_cross_reference_is_an_identity_conflict():
    rows = {
        2: _row("E-5", "N/A", context="Not Installed / Bench Audit", notes="Same EOAT as tool # 200. EOAT Not Installed.", tool="100"),
        3: _row("E-6", "N/A", context="Not Installed / Bench Audit", notes="Same EOAT as tool # 100. EOAT Not Installed.", tool="200"),
    }
    records = classify_eoat_locations(rows, _database(["E-5", "E-6"]))["records"]
    assert {record["determined_physical_state"] for record in records} == {STATE_CONFLICT}


def test_normalized_parity_requires_matching_install_or_storage_but_unknown_requires_neither():
    rows = {
        2: _row("E-7", "7"),
        3: _row("E-8", "N/A", context="Not Installed / Bench Audit", notes="EOAT in cabinet. EOAT Not Installed."),
        4: _row("E-9", "N/A", context="Not Installed / Bench Audit", notes="EOAT Not Installed."),
    }
    database = _database(
        ["E-7", "E-8", "E-9"],
        installations=[{"eoat_identifier": "E-7", "machine_number": "7", "is_current": 1}],
        storage=[{"eoat_identifier": "E-8", "location_code": "GENERIC", "is_current": 1}],
    )
    records = classify_eoat_locations(rows, database)["records"]
    assert [record["normalized_location_parity"] for record in records] == ["PASS", "PASS", "PASS"]
