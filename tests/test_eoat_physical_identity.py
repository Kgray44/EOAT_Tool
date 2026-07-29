from __future__ import annotations

from tools.eoat_physical_identity import build_crosswalk, validate_crosswalk


def _governed_rows():
    rows = [
        (44, {"Audit ID": "AUD-0018-A", "Entry Type": "Audited", "EOAT Assembly ID": "P4-EOAT-0018"}),
        (70, {"Audit ID": "AUD-0018-B", "Entry Type": "Audited", "EOAT Assembly ID": "P4-EOAT-0018"}),
        *[(number, {"Audit ID": f"AUD-{number}", "Entry Type": "Audited", "EOAT Assembly ID": "CL-EOAT-0050"}) for number in (81, 82, 83)],
        *[(number, {"Audit ID": f"AUD-{number}", "Entry Type": "Audited", "EOAT Assembly ID": "CL-EOAT-0052"}) for number in (85, 86, 89)],
        *[(number, {"Audit ID": f"AUD-{number}", "Entry Type": "Audited", "EOAT Assembly ID": "CL-EOAT-0054"}) for number in (88, 92, 93)],
        *[(number, {"Audit ID": f"AUD-{number}", "Entry Type": "Audited", "EOAT Assembly ID": "P4-EOAT-0057"}) for number in (94, 95, 96, 97)],
    ]
    rows.extend(
        (number, {"Audit ID": f"AUD-UNIQUE-{number}", "Entry Type": "Audited", "EOAT Assembly ID": f"TEST-EOAT-{number:04d}"})
        for number in range(100, 152)
    )
    rows.append((200, {"Audit ID": "COMPAT-1", "Entry Type": "Compatible", "EOAT Assembly ID": "CL-EOAT-0050"}))
    return rows


def test_governed_crosswalk_enforces_67_audits_to_66_physical_units():
    crosswalk = build_crosswalk(_governed_rows(), source_workbook_sha256="a" * 64)
    validation = validate_crosswalk(crosswalk)
    assert validation.audited_rows == 67
    assert validation.physical_units == 66
    assert validation.canonical_identifiers == 66
    assert validation.duplicate_physical_identifier == "P4-EOAT-0018"
    assert validation.duplicate_audit_rows == 2
    compatibility = next(row for row in crosswalk if row["entry_type"] == "Compatible")
    assert compatibility["canonical_physical_eoat_identifier"] is None


def test_governed_crosswalk_rejects_an_unapproved_many_to_one_mapping():
    rows = _governed_rows()
    rows.append((201, {"Audit ID": "AUD-EXTRA", "Entry Type": "Audited", "EOAT Assembly ID": "P4-EOAT-0018"}))
    try:
        build_crosswalk(rows, source_workbook_sha256="b" * 64)
    except RuntimeError as exc:
        assert "Expected 67 audited rows" in str(exc)
    else:
        raise AssertionError("expected crosswalk validation failure")
